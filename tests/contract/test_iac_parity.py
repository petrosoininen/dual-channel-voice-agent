"""Infrastructure implementations must preserve one logical contract."""

from scripts.validate_iac_parity import validate


def test_bicep_and_terraform_have_logical_parity() -> None:
    assert validate() == []
