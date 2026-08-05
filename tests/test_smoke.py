"""Day 1 package smoke test."""

import onchain_arb


def test_package_import_exposes_version() -> None:
    # Arrange: importing the package is the Day 1 setup under test.
    expected_version = "0.1.0"

    # Act: read the smallest public package value.
    actual_version = onchain_arb.__version__

    # Assert: the src-layout package is discoverable and initialized.
    assert actual_version == expected_version

