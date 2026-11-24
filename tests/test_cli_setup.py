"""
CLI tests for commands backed by multi_aws_tool.services (init, roles, profiles,
sync, clean-duplicates) and the guided `multi-aws setup` wizard.
"""

import subprocess
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from multi_aws_tool.aws import profile_config
from multi_aws_tool.aws.account_manager import AccountManager
from multi_aws_tool.cli.commands import cli
from multi_aws_tool.models.account import Account, AccountCollection, Role
from multi_aws_tool.utils.account_data import AccountDataManager


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".multi-aws").mkdir(parents=True)
    account_file = home / ".multi-aws" / "accounts.json"
    (home / ".multi-aws" / "config.ini").write_text(
        "[general]\nprefix = mat\nsso-session = acme\nregion = eu-west-1\n"
        f"account-file = {account_file}\n[logging]\nconsole = false\nfile =\n")
    aws_config = tmp_path / "aws-config"
    aws_config.write_text("[sso-session acme]\nsso_start_url = https://acme.awsapps.com/start\nsso_region = eu-west-1\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(aws_config))

    collection = AccountCollection()
    collection.add_account(Account(id="111111111111", name="Prod Account",
                                   roles=[Role("ReadOnly", "arn:aws:iam::111111111111:role/ReadOnly")]))
    collection.add_account(Account(id="222222222222", name="Dev Account"))
    AccountDataManager(str(account_file)).save_accounts(collection)
    return {"aws_config": aws_config, "accounts": AccountDataManager(str(account_file))}


def invoke(args, input=None):
    with patch("os.get_terminal_size", return_value=(120, 40)):
        return CliRunner().invoke(cli, args, input=input, catch_exceptions=False)


def test_profiles_append_writes_and_persists(env):
    result = invoke(["profiles", "--accounts", "all", "--role", "ReadOnly", "--append-to-config"])
    assert "Created: mat-Prod-Account-ReadOnly" in result.output
    assert "Skipping Dev Account (222222222222): roles not fetched" in result.output
    assert "[profile mat-Prod-Account-ReadOnly]" in env["aws_config"].read_text()
    assert env["accounts"].get_account("111111111111").profile_name == "mat-Prod-Account-ReadOnly"

    # running again updates in place instead of appending a duplicate
    result = invoke(["profiles", "--accounts", "111111111111", "--role", "ReadOnly", "--append-to-config"])
    assert "Updated: mat-Prod-Account-ReadOnly" in result.output
    assert env["aws_config"].read_text().count("[profile mat-Prod-Account-ReadOnly]") == 1


def test_profiles_print_only(env):
    before = env["aws_config"].read_text()
    result = invoke(["profiles", "--accounts", "Prod Account", "--role", "ReadOnly"])
    assert "[profile mat-Prod-Account-ReadOnly]" in result.output
    assert "sso_account_id = 111111111111" in result.output
    assert env["aws_config"].read_text() == before


def test_sync_and_clean_duplicates(env):
    invoke(["profiles", "--accounts", "111111111111", "--role", "ReadOnly", "--append-to-config"])
    env["aws_config"].write_text(env["aws_config"].read_text() + (
        "\n[profile legacy]\nsso_session = acme\nsso_account_id = 111111111111\nsso_role_name = ReadOnly\n"))

    result = invoke(["clean-duplicates", "--dry-run"])
    assert "Duplicate: legacy" in result.output and "[profile legacy]" in env["aws_config"].read_text()

    result = invoke(["clean-duplicates", "--yes"])
    assert "removed 1 duplicate" in result.output
    assert "[profile legacy]" not in env["aws_config"].read_text()

    result = invoke(["sync", "--dry-run"])
    assert "Profiles found: 1" in result.output


def test_init_reports_missing_session(env):
    result = invoke(["init", "--sso-session", "nope"])
    assert "SSO session 'nope' not found" in result.output
    assert "multi-aws setup" in result.output


def test_roles_fetches_in_parallel(env):
    with patch.object(AccountManager, "is_authenticated", return_value=True), \
            patch.object(AccountManager, "discover_roles_for_account",
                         side_effect=lambda aid: [Role("Admin", f"arn:aws:iam::{aid}:role/Admin")]):
        result = invoke(["roles", "--accounts", "all"])
    assert "Fetched roles for 2 account(s)" in result.output
    assert "Admin (2 account(s))" in result.output


def test_setup_wizard_happy_path(env, tmp_path):
    sso_accounts = [{"accountId": "111111111111", "accountName": "Prod Account"},
                    {"accountId": "222222222222", "accountName": "Dev Account"}]
    identity = subprocess.CompletedProcess(
        args=[], returncode=0, stdout='{"Arn": "arn:aws:sts::111111111111:assumed-role/ReadOnly/me"}', stderr="")

    with patch("shutil.which", return_value="/usr/local/bin/aws"), \
            patch.object(AccountManager, "is_authenticated", return_value=True), \
            patch("multi_aws_tool.aws.sso_client.SSOClient.list_accounts", return_value=sso_accounts), \
            patch.object(AccountManager, "discover_roles_for_account",
                         side_effect=lambda aid: [Role("ReadOnly", f"arn:aws:iam::{aid}:role/ReadOnly"),
                                                  Role("Admin", f"arn:aws:iam::{aid}:role/Admin")]), \
            patch("multi_aws_tool.execution.subprocess.run", return_value=identity), \
            patch("multi_aws_tool.mcp_server.claude_desktop_config_path",
                  return_value=tmp_path / "no-claude" / "config.json"):
        # review config? n / refresh accounts? n / role (default) / write profiles? y
        result = invoke(["setup"], input="n\nn\n\ny\n")

    out = result.output
    assert "Using session 'acme'" in out
    assert "Roles fetched for 1 account(s)" in out  # Prod already had roles
    assert "2 profiles for 'ReadOnly'" in out
    assert "assumed-role/ReadOnly/me" in out
    assert "All set!" in out
    assert len(profile_config.list_profiles(env["aws_config"].read_text())) == 2
