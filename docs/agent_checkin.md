# 残酷共学 Agent 每日打卡说明

本文件用于指导 AI Agent 将本项目的每日学习笔记发布到「链上套利残酷共学」。

## 使用方式

用户可以对 AI Agent 说：

> 按 `docs/agent_checkin.md` 发布今天的打卡，笔记内容使用 `docs/daily/day_XX.md`。

只有当用户在当前对话中明确要求“发布”时，Agent 才能执行外部发布操作。仅要求撰写、检查或预览笔记时，不得发布。

## 固定配置

- Program：链上套利残酷共学
- Program ID：`b43d2e97-ed88-4ca3-b12f-7ef672b01205`
- API Base URL：`https://intensivecolearn.ing/api/v1`
- Agent API 文档：`https://intensivecolearn.ing/llms.txt`
- OpenAPI：`https://intensivecolearn.ing/api/v1/openapi.json`
- API Contract Version：`1.3.0`
- Access Key 环境变量：`ICL_ACCESS_KEY`
- Access Key 文件：项目根目录 `.env`
- User-Agent：`onchain-arbitrage-study/0.1`
- 笔记格式：Markdown
- 单篇最大长度：20,000 字符
- Public Repository：`https://github.com/ZeroNullNone/onchain_arbitrage_study`
- Public Note Base：`https://github.com/ZeroNullNone/onchain_arbitrage_study/blob/main/`

## 安全规则

1. 不得在终端输出、日志、异常消息、提交记录或回复中显示 `ICL_ACCESS_KEY`。
2. 不得把 `.env`、Access Key 或带有认证 Header 的调试输出提交到 Git。
3. 不得将 Access Key 写入源代码、Markdown、测试 Fixture 或命令参数示例中的明文位置。
4. 只把 Key 发送到 `https://intensivecolearn.ing/api/v1/*`。
5. 发布前必须向用户展示最终 Markdown 内容或明确指出将发布的文件。
6. 发布成功后只报告 Check-in ID、URL、时间和 HTTP 状态，不回显认证信息。
7. 如果 Key 无效或权限不足，停止操作并报告 HTTP 状态及安全处理后的错误信息。
8. Repository 内部的 Markdown 链接继续使用相对路径；发布到 ICL 前，在请求正文中临时转换成指向 `main` 的绝对 GitHub URL，不回写成绝对链接。

## 每日发布流程

### 1. 确认笔记

发布前检查：

- 文件存在且不为空。
- 内容确实属于当天。
- 内容不包含 Access Key、私钥、助记词、密码或其他秘密。
- 内容不超过 20,000 字符。
- Markdown 图片使用可公开访问的 URL；本地图片路径不会自动上传。

发布到 ICL 的正文顶部应包含当天笔记的 Canonical GitHub URL，例如：

```text
https://github.com/ZeroNullNone/onchain_arbitrage_study/blob/main/docs/daily/day_01.md
```

外部发布时还应把正文中的 Repository-relative Links 转换成完整 GitHub URL。Repository 文件本身继续保留相对链接，确保 Fork、Branch 和本地预览仍然可导航。

建议每日笔记路径：

```text
docs/daily/day_01.md
docs/daily/day_02.md
...
docs/daily/day_21.md
```

### 2. 验证认证

使用只读接口验证 Access Key：

```http
GET /api/v1/me
Authorization: Bearer <ICL_ACCESS_KEY>
User-Agent: onchain-arbitrage-study/0.1
```

预期结果为 HTTP 200。不要输出响应中的个人资料，除非用户明确要求查看。
所有 API 请求都必须发送上述显式 `User-Agent`；Python 默认 User-Agent 会被前置服务返回非 JSON HTTP 403。

### 3. 检查当天是否已经打卡

查询本课程的个人打卡记录：

```http
GET /api/v1/me/check-ins?page=1&pageSize=20&programId=b43d2e97-ed88-4ca3-b12f-7ef672b01205
Authorization: Bearer <ICL_ACCESS_KEY>
User-Agent: onchain-arbitrage-study/0.1
```

响应位于 `data.items`，分页信息位于 `data.pagination`。若 `totalPages > 1`，继续读取后续页，不能只检查第一页便假设没有重复记录。

按 UTC+8 判断当天是否已有记录：

- 没有当天记录：执行 Create。
- 已有当天记录：不要重复 Create；显示现有记录并询问用户是否 Update。

### 4. 创建打卡

```http
POST /api/v1/me/check-ins
Authorization: Bearer <ICL_ACCESS_KEY>
User-Agent: onchain-arbitrage-study/0.1
Content-Type: application/json
Idempotency-Key: <8-128 个允许字符>
```

请求正文：

```json
{
  "programId": "b43d2e97-ed88-4ca3-b12f-7ef672b01205",
  "content": "完整的 Markdown 笔记"
}
```

`Idempotency-Key` 只能包含字母、数字、`.`、`_`、`:`、`-`。建议格式：

```text
onchain_arb_day_01_20260805_v1
```

相同 Method、Path 和 Body 的重试必须复用同一个 Key。笔记内容发生变化时必须使用新的 Key，例如把结尾从 `_v1` 改为 `_v2`。

创建成功的预期状态为 HTTP 201。
创建成功后重新读取 check-in list，并按返回 ID 确认记录可见；不要只依赖 POST response 判断持久化成功。

### 5. 更新已有打卡

只有用户确认更新后才执行：

```http
PATCH /api/v1/me/check-ins/{checkinId}
Authorization: Bearer <ICL_ACCESS_KEY>
User-Agent: onchain-arbitrage-study/0.1
Content-Type: application/json
```

请求正文：

```json
{
  "content": "更新后的完整 Markdown 笔记"
}
```

只能更新属于当前 Access Key 用户自己的打卡。

### 6. 发布结果

发布完成后报告：

```text
发布状态：成功 / 失败
操作：Create / Update
HTTP 状态：201 / 200 / 其他
Program ID：b43d2e97-ed88-4ca3-b12f-7ef672b01205
Check-in ID：<服务端返回值>
Web URL：<服务端返回值，如有>
笔记来源：docs/daily/day_XX.md
```

## 常见错误

- `400`：请求字段、正文或 Idempotency-Key 不合法。
- `401`：Access Key 缺失、无效或已撤销。
- `403`：当前账号不是已批准参与者，或没有该操作权限。
- `404`：Program、Check-in 或 Endpoint 不存在。
- `409`：当天可能已经打卡，或幂等请求仍在处理中。
- `413`：JSON Body 超过 64 KiB。
- `415`：请求不是 `application/json`。
- `429`：超过每个 Access Key 的持久化限流。
- `503`：审计存储不可用，写操作已回滚；不要假设发布成功。

遇到不确定的响应时，先使用只读 GET 接口确认服务器状态，不要盲目重复 POST。
API 权限错误遵循 `{"apiVersion":"v1","error":{"code":"...","message":"..."}}`。若 403 不是此 JSON envelope，先确认请求使用了显式 User-Agent；不得把前置服务的非 JSON 403 误判为 Key 无效。
