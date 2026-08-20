"""Publish daily note to Intensive Co-learning (ICL) 2.0 Agent API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
import urllib.error
from uuid import uuid4

PROGRAM_ID = "b43d2e97-ed88-4ca3-b12f-7ef672b01205"
API_BASE_URL = "https://intensivecolearn.ing/api/v1"
USER_AGENT = "onchain-arbitrage-study/0.1"
GITHUB_BASE = "https://github.com/ZeroNullNone/onchain_arbitrage_study/blob/main/"

RAW_CHECKINS_DIR = Path("data/raw/checkins")


def load_env() -> dict[str, str]:
    env_vars: dict[str, str] = {}
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip().strip("'\"")
    return env_vars


def save_raw_evidence(
    *,
    request_id: str,
    method: str,
    url: str,
    headers: dict[str, str],
    req_body: str | None,
    resp_status: int,
    resp_headers: dict[str, str],
    resp_body: str,
    latency_ms: float,
    observed_at: datetime,
) -> Path:
    RAW_CHECKINS_DIR.mkdir(parents=True, exist_ok=True)
    ts = observed_at.strftime("%Y%m%dT%H%M%SZ")
    filename = f"{ts}_{request_id}.json"
    file_path = RAW_CHECKINS_DIR / filename

    redacted_headers = dict(headers)
    if "Authorization" in redacted_headers:
        redacted_headers["Authorization"] = "Bearer <redacted>"

    record = {
        "request_id": request_id,
        "observed_at": observed_at.isoformat(),
        "latency_ms": latency_ms,
        "request": {
            "method": method,
            "url": url,
            "headers": redacted_headers,
            "body": req_body,
        },
        "response": {
            "status": resp_status,
            "headers": resp_headers,
            "body": resp_body,
        },
    }

    file_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return file_path


def api_request(
    method: str,
    path: str,
    key: str,
    body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict, dict[str, str]]:
    url = f"{API_BASE_URL}{path}"
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {key}",
    }
    if extra_headers:
        headers.update(extra_headers)

    req_body_str = None
    req_data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        req_body_str = json.dumps(body, ensure_ascii=False)
        req_data = req_body_str.encode("utf-8")

    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    request_id = str(uuid4())
    observed_at = datetime.now(UTC)
    start = time.perf_counter()

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_status = resp.status
            resp_headers = dict(resp.headers)
            resp_body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        resp_status = err.code
        resp_headers = dict(err.headers)
        resp_body = err.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"Network request failed: {exc}") from exc

    latency_ms = (time.perf_counter() - start) * 1000.0

    save_raw_evidence(
        request_id=request_id,
        method=method,
        url=url,
        headers=headers,
        req_body=req_body_str,
        resp_status=resp_status,
        resp_headers=resp_headers,
        resp_body=resp_body,
        latency_ms=latency_ms,
        observed_at=observed_at,
    )

    try:
        parsed_body = json.loads(resp_body)
    except json.JSONDecodeError:
        parsed_body = {"raw": resp_body}

    return resp_status, parsed_body, resp_headers


def convert_relative_links(content: str, daily_rel_dir: str = "docs/daily") -> str:
    """Convert relative repository markdown links to absolute GitHub URLs."""
    def replacer(match: re.Match) -> str:
        label = match.group(1)
        target = match.group(2)
        if target.startswith("http://") or target.startswith("https://") or target.startswith("#"):
            return match.group(0)
        # Resolve path relative to daily_rel_dir
        norm = os.path.normpath(os.path.join(daily_rel_dir, target))
        if norm.startswith("/"):
            norm = norm.lstrip("/")
        return f"[{label}]({GITHUB_BASE}{norm})"

    # Match markdown link [label](url)
    pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    return pattern.sub(replacer, content)


def main() -> None:
    day_str = "16"
    if len(sys.argv) > 1:
        day_str = sys.argv[1].replace("day_", "").replace("day", "")
    day_int = int(day_str)
    day_file = Path(f"docs/daily/day_{day_int:02d}.md")

    if not day_file.exists():
        print(f"Error: {day_file} does not exist", file=sys.stderr)
        sys.exit(1)

    raw_note = day_file.read_text(encoding="utf-8")
    if not raw_note.strip():
        print(f"Error: {day_file} is empty", file=sys.stderr)
        sys.exit(1)

    env = load_env()
    key = os.environ.get("ICL_ACCESS_KEY") or env.get("ICL_ACCESS_KEY")
    if not key:
        print("Error: ICL_ACCESS_KEY not found in environment or .env", file=sys.stderr)
        sys.exit(1)

    # 1. Verify Auth
    status, body, _ = api_request("GET", "/me", key)
    if status != 200:
        print(f"Auth verification failed with HTTP {status}: {body}", file=sys.stderr)
        sys.exit(1)

    # 2. Check existing check-ins
    status, checkins_resp, _ = api_request(
        "GET",
        f"/me/check-ins?page=1&pageSize=20&programId={PROGRAM_ID}",
        key,
    )
    if status != 200:
        print(f"Failed to query check-ins: HTTP {status}: {checkins_resp}", file=sys.stderr)
        sys.exit(1)

    # Compute today's date in UTC+8
    utc8 = timezone(timedelta(hours=8))
    today_utc8 = datetime.now(utc8).strftime("%Y-%m-%d")
    items = checkins_resp.get("data", {}).get("items", [])
    today_existing = [item for item in items if item.get("dayKey") == today_utc8]

    # Convert content for publish
    canonical_header = f"{GITHUB_BASE}docs/daily/day_{day_int:02d}.md\n\n"
    converted_body = convert_relative_links(raw_note)
    final_content = canonical_header + converted_body

    if len(final_content) > 20000:
        print(f"Error: Content length ({len(final_content)}) exceeds 20,000 characters", file=sys.stderr)
        sys.exit(1)

    if today_existing:
        existing_id = today_existing[0]["id"]
        print(f"Existing check-in found for today ({today_utc8}): {existing_id}. Updating...")
        status, patch_resp, _ = api_request(
            "PATCH",
            f"/me/check-ins/{existing_id}",
            key,
            body={"content": final_content},
        )
        op = "Update"
        result_id = existing_id
        web_url = patch_resp.get("data", {}).get("webUrl", f"https://intensivecolearn.ing/programs/{PROGRAM_ID}")
    else:
        idempotency_key = f"onchain_arb_day_{day_int:02d}_{datetime.now(UTC).strftime('%Y%m%d')}_v1"
        print(f"Creating new check-in for {today_utc8} with Idempotency-Key: {idempotency_key}")
        status, post_resp, _ = api_request(
            "POST",
            "/me/check-ins",
            key,
            body={
                "programId": PROGRAM_ID,
                "content": final_content,
            },
            extra_headers={"Idempotency-Key": idempotency_key},
        )
        op = "Create"
        if status in (200, 201):
            result_id = post_resp.get("data", {}).get("id", "unknown")
            web_url = post_resp.get("data", {}).get("webUrl", f"https://intensivecolearn.ing/programs/{PROGRAM_ID}")
        else:
            print(f"Failed to create check-in: HTTP {status}: {post_resp}", file=sys.stderr)
            sys.exit(1)

    # 3. Verify publication by querying check-ins list again
    status, verify_resp, _ = api_request(
        "GET",
        f"/me/check-ins?page=1&pageSize=20&programId={PROGRAM_ID}",
        key,
    )

    print("\n--- Check-in Summary ---")
    print(f"发布状态：成功")
    print(f"操作：{op}")
    print(f"HTTP 状态：{status}")
    print(f"Program ID：{PROGRAM_ID}")
    print(f"Check-in ID：{result_id}")
    print(f"Web URL：{web_url}")
    print(f"笔记来源：docs/daily/day_{day_int:02d}.md")


if __name__ == "__main__":
    main()
