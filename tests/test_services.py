"""
Tests for the shared operations layer (multi_aws_tool.services)
"""

import subprocess
from unittest.mock import patch

import pytest

from multi_aws_tool.aws import profile_config
from multi_aws_tool.aws.account_manager import AccountManager
from multi_aws_tool.config.manager import ConfigManager
from multi_aws_tool.models.account import Account, AccountCollection, AccountStatus, Role
from multi_aws_tool.output import AccountResult, MultiAWSExecutionSummary
from multi_aws_tool.services import MultiAWS, OperationError, summarize_execution


def _role(name, account_id):
    return Role(name, f"arn:aws:iam::{account_id}:role/{name}")


@pytest.fixture
def aws_config(tmp_path, monkeypatch):
    path = tmp_path / "aws-config"
    path.write_text("[sso-session acme]\nsso_start_url = https://acme.awsapps.com/start\nsso_region = eu-west-1\n")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(path))
    return path


@pytest.fixture
def ops(tmp_path, aws_config):
    config = ConfigManager(str(tmp_path / "config.ini"))
    config.set("general", "prefix", "mat")
    config.set("general", "sso-session", "acme")
    config.set("general", "region", "eu-west-1")
    config.set("general", "account-file", str(tmp_path / "accounts.json"))
    config.set("general", "templates-file", str(tmp_path / "templates.json"))
    o = MultiAWS(config)
    collection = AccountCollection()
    collection.add_account(Account(id="111111111111", name="Prod Account", product_team="core",
                                   tags={"env": "prod"},
                                   roles=[_role("ReadOnly", "111111111111"), _role("Admin", "111111111111")]))
    collection.add_account(Account(id="222222222222", name="Dev Account", product_team="core",
                                   tags={"env": "dev"}, roles=[_role("ReadOnly", "222222222222")]))
    collection.add_account(Account(id="333333333333", name="Old Account", product_team="core",
                                   tags={"env": "prod"}, status=AccountStatus.DISABLED))
    collection.add_account(Account(id="444444444444", name="Data Account", product_team="data",
                                   tags={"env": "prod"}))
    o.accounts.data_manager.save_accounts(collection)
    return o


def _logged_in(value=True):
    return patch.object(AccountManager, "is_authenticated", return_value=value)


# ---------------------------------------------------------------------------
# Account selection
# ---------------------------------------------------------------------------

class TestSelectAccounts:
    def test_requires_a_selector(self, ops):
        with pytest.raises(OperationError):
            ops.select_accounts()

    def test_ids_and_names(self, ops):
        assert ops.select_accounts(["111111111111", "dev account"]) == ["111111111111", "222222222222"]

    def test_comma_string(self, ops):
        assert ops.select_accounts("111111111111, Dev Account") == ["111111111111", "222222222222"]

    def test_unknown_name_raises(self, ops):
        with pytest.raises(OperationError):
            ops.select_accounts(["Nope"])

    def test_unknown_id_kept_for_error_reporting(self, ops):
        assert ops.select_accounts(["999999999999"]) == ["999999999999"]

    def test_team_skips_inactive(self, ops):
        assert ops.select_accounts(team="core") == ["111111111111", "222222222222"]
        assert "333333333333" in ops.select_accounts(team="core", include_inactive=True)

    def test_multiple_teams(self, ops):
        assert ops.select_accounts(team="core, data") == ["111111111111", "222222222222", "444444444444"]

    def test_tags_alone_select_from_all(self, ops):
        assert ops.select_accounts(tags={"env": "prod"}) == ["111111111111", "444444444444"]

    def test_tag_strings(self, ops):
        assert ops.select_accounts(tags=["env=dev"]) == ["222222222222"]

    def test_tags_narrow_team(self, ops):
        assert ops.select_accounts(team="core", tags={"env": "dev"}) == ["222222222222"]

    def test_all(self, ops):
        assert ops.select_accounts("all") == ["111111111111", "222222222222", "444444444444"]

    def test_explicit_inactive_account_kept(self, ops):
        assert ops.select_accounts(["333333333333"]) == ["333333333333"]

    def test_empty_result_raises(self, ops):
        with pytest.raises(OperationError):
            ops.select_accounts(team="core", tags={"env": "staging"})


def test_list_accounts_filters(ops):
    assert [a["id"] for a in ops.list_accounts(role="Admin")] == ["111111111111"]
    assert [a["name"] for a in ops.list_accounts(team="core")] == ["Dev Account", "Prod Account"]


# ---------------------------------------------------------------------------
# Setup status, config and SSO
# ---------------------------------------------------------------------------

class TestSetupStatus:
    def test_reports_next_step(self, ops):
        with _logged_in(False), patch("shutil.which", return_value="/usr/bin/aws"):
            status = ops.setup_status()
        steps = {s["step"]: s["done"] for s in status["steps"]}
        assert steps["aws_cli"] and steps["sso_session"]
        assert not steps["config"]  # tmp config never saved
        assert status["next_step"]["step"] == "config"
        assert status["teams"] == ["core", "data"]
        assert status["common_roles"]["ReadOnly"] == 2

    def test_missing_session(self, ops, aws_config):
        aws_config.write_text("")
        with _logged_in(False):
            steps = {s["step"]: s for s in ops.setup_status()["steps"]}
        assert not steps["sso_session"]["done"]
        assert not steps["sso_login"]["done"]


class TestConfig:
    def test_update_and_persist(self, ops, tmp_path):
        result = ops.update_config({"general.region": "us-east-1", "output.format": "yaml"})
        assert result["previous"]["general.region"] == "eu-west-1"
        reread = ConfigManager(str(tmp_path / "config.ini"))
        reread.load_config()
        assert reread.get("general", "region") == "us-east-1"

    def test_rejects_protected_and_unknown_keys(self, ops):
        with pytest.raises(OperationError, match="directly"):
            ops.update_config({"security.allow-destructive-commands": "true"})
        with pytest.raises(OperationError, match="Unknown setting"):
            ops.update_config({"general.nope": "x"})

    def test_invalid_value_is_rolled_back(self, ops):
        with pytest.raises(OperationError, match="Invalid configuration"):
            ops.update_config({"output.format": "xml"})
        assert ops.config.get("output", "format") == "json"

    def test_prefix_change_rebuilds_account_manager(self, ops):
        ops.update_config({"general.prefix": "acme"})
        assert ops.prefix == "acme"


class TestSSO:
    def test_add_session(self, ops, aws_config):
        result = ops.add_sso_session("other", "https://other.awsapps.com/start", "us-east-1")
        assert result["created"] and result["now_default"]
        assert profile_config.list_sso_sessions(aws_config.read_text())["other"]["sso_region"] == "us-east-1"
        assert ops.sso_session == "other"

    def test_add_session_validates(self, ops):
        with pytest.raises(OperationError, match="start_url"):
            ops.add_sso_session("x", "acme.awsapps.com", "eu-west-1")
        with pytest.raises(OperationError, match="region"):
            ops.add_sso_session("x", "https://acme.awsapps.com/start", "europe")
        with pytest.raises(OperationError, match="already exists"):
            ops.add_sso_session("acme", "https://acme.awsapps.com/start", "eu-west-1")

    def test_login_runs_aws_cli(self, ops):
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch.object(AccountManager, "is_authenticated", side_effect=[False, True]), \
                patch("multi_aws_tool.services.subprocess.run", return_value=done) as run:
            assert ops.sso_login()["authenticated"]
        assert run.call_args.args[0] == ["aws", "sso", "login", "--sso-session", "acme"]


# ---------------------------------------------------------------------------
# Discovery, roles and profiles
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_requires_login(self, ops):
        with _logged_in(False), pytest.raises(OperationError, match="not logged in"):
            ops.discover_accounts()

    def test_discover_sanitizes_and_reports_new(self, ops):
        sso_accounts = [{"accountId": "111111111111", "accountName": "Prod Account"},
                        {"accountId": "555555555555", "accountName": "New.Account"}]
        with _logged_in(), patch.object(ops.accounts.sso_client, "list_accounts", return_value=sso_accounts):
            result = ops.discover_accounts()
        assert result["new_accounts"] == [{"id": "555555555555", "name": "New-Account"}]
        assert {"id": "555555555555", "from": "New.Account", "to": "New-Account"} in result["sanitized_names"]
        assert ops.accounts.get_account("222222222222").status == AccountStatus.DISABLED

    def test_fetch_roles_in_parallel_and_saves_once(self, ops):
        def roles(account_id):
            if account_id == "444444444444":
                from multi_aws_tool.aws.account_manager import AccountManagerError
                raise AccountManagerError("denied")
            return [_role("ReadOnly", account_id), _role("Billing", account_id)]

        with _logged_in(), patch.object(AccountManager, "discover_roles_for_account", side_effect=roles):
            result = ops.fetch_roles(["111111111111", "444444444444", "999999999999"])
        assert result["updated"] == 1
        assert result["failed"] == {"444444444444": "denied"}
        assert result["not_found"] == ["999999999999"]
        assert [r.name for r in ops.accounts.get_account("111111111111").roles] == ["ReadOnly", "Billing"]


class TestProfiles:
    def test_generate_writes_and_persists(self, ops, aws_config):
        result = ops.generate_profiles(["111111111111", "222222222222", "444444444444"], "ReadOnly")
        assert result["created"] == ["mat-Prod-Account-ReadOnly", "mat-Dev-Account-ReadOnly"]
        assert result["skipped"][0]["id"] == "444444444444"
        profiles = profile_config.list_profiles(aws_config.read_text())
        assert profiles["mat-Prod-Account-ReadOnly"] == {
            "sso_session": "acme", "sso_account_id": "111111111111",
            "sso_role_name": "ReadOnly", "region": "eu-west-1"}
        # stored on the accounts (the old CLI lost this)
        assert ops.accounts.get_account("111111111111").profile_name == "mat-Prod-Account-ReadOnly"
        assert result["backup"]

    def test_regenerate_updates_in_place(self, ops, aws_config):
        ops.generate_profiles(["111111111111"], "ReadOnly")
        result = ops.generate_profiles(["111111111111"], "ReadOnly", region="us-east-1")
        assert result["updated"] == ["mat-Prod-Account-ReadOnly"]
        assert aws_config.read_text().count("[profile mat-Prod-Account-ReadOnly]") == 1

    def test_dry_run_writes_nothing(self, ops, aws_config):
        before = aws_config.read_text()
        result = ops.generate_profiles(["111111111111"], "Admin", dry_run=True)
        assert result["created"] == ["mat-Prod-Account-Admin"]
        assert aws_config.read_text() == before
        assert ops.accounts.get_account("111111111111").profile_name is None

    def test_role_missing(self, ops):
        result = ops.generate_profiles(["222222222222"], "Admin")
        assert result["created"] == [] and "not available" in result["skipped"][0]["reason"]

    def test_sync_profiles(self, ops, aws_config):
        aws_config.write_text(aws_config.read_text() + (
            "\n[profile mat-Dev-Account-ReadOnly]\nsso_session = acme\nsso_account_id = 222222222222\n"
            "sso_role_name = ReadOnly\n\n[profile mat-x]\nsso_account_id = 999999999999\n"))
        preview = ops.sync_profiles(dry_run=True)
        assert preview["changes"][0]["to"] == "mat-Dev-Account-ReadOnly"
        assert ops.accounts.get_account("222222222222").profile_name is None
        ops.sync_profiles()
        assert ops.accounts.get_account("222222222222").profile_name == "mat-Dev-Account-ReadOnly"
        assert ops.sync_profiles()["unknown_accounts"] == [{"id": "999999999999", "profile": "mat-x"}]

    def test_clean_duplicates(self, ops, aws_config):
        ops.generate_profiles(["111111111111"], "ReadOnly")
        aws_config.write_text(aws_config.read_text() + (
            "\n[profile old]\nsso_session = acme\nsso_account_id = 111111111111\nsso_role_name = ReadOnly\n"))
        preview = ops.clean_duplicate_profiles()
        assert preview["duplicates"][0]["remove"] == ["old"] and preview["removed"] == 0
        assert "[profile old]" in aws_config.read_text()
        assert ops.clean_duplicate_profiles(dry_run=False)["removed"] == 1
        assert "[profile old]" not in aws_config.read_text()

    def test_sanitize_names(self, ops):
        collection = ops.accounts.data_manager.load_accounts()
        collection.get_account("444444444444").name = "Data Account (EU)"
        ops.accounts.data_manager.save_accounts(collection)
        changes = {c["id"]: c["to"] for c in ops.sanitize_names()["changes"]}
        assert changes["444444444444"] == "Data-Account-EU"
        assert ops.accounts.get_account("444444444444").name == "Data-Account-EU"


# ---------------------------------------------------------------------------
# Teams, tags, templates, run, cleanup
# ---------------------------------------------------------------------------

class TestTeamsAndTags:
    def test_assign_team_respects_overwrite(self, ops):
        result = ops.assign_team(["111111111111", "444444444444"], "platform")
        assert result["skipped_existing_team"][0]["team"] == "core"
        assert ops.list_teams() == {"core": 3, "data": 1}
        ops.assign_team(["111111111111"], "platform", overwrite=True)
        assert ops.list_teams()["platform"] == 1

    def test_clear_team(self, ops):
        ops.assign_team(["444444444444"], None)
        assert "data" not in ops.list_teams()

    def test_set_and_remove_tags(self, ops):
        result = ops.set_tags(["111111111111"], {"env": "staging", "owner": "me"})
        assert result["skipped_existing"] == [{"id": "111111111111", "key": "env", "existing": "prod"}]
        assert ops.accounts.get_account("111111111111").tags == {"env": "prod", "owner": "me"}
        ops.set_tags(["111111111111"], ["env=staging"], overwrite=True)
        assert ops.accounts.get_account("111111111111").tags["env"] == "staging"
        removed = ops.remove_tags(["111111111111", "222222222222"], ["owner", "missing"])
        assert removed["removed"] == [{"id": "111111111111", "name": "Prod Account", "key": "owner", "value": "me"}]

    def test_sync_tags_requires_profile(self, ops):
        with pytest.raises(OperationError, match="no working profile"):
            ops.sync_tags("111111111111")


class TestTemplates:
    def test_save_list_run_delete(self, ops):
        ops.save_template("ids", "aws ec2 describe-instances", "Instance IDs", team="core",
                          tags={"env": "prod"}, region="us-east-1", timeout=30)
        [tmpl] = ops.list_templates()
        assert tmpl["command"] == "ec2 describe-instances" and tmpl["tags"] == ["env=prod"]

        kwargs = ops.template_run_kwargs("@ids")
        assert kwargs["team"] == "core" and kwargs["regions"] == ["us-east-1"] and kwargs["timeout"] == 30
        # overriding the selection replaces the template's whole selection
        kwargs = ops.template_run_kwargs("ids", accounts=["111111111111"])
        assert kwargs["accounts"] == ["111111111111"] and kwargs["team"] is None and kwargs["tags"] is None

        with pytest.raises(OperationError, match="already exists"):
            ops.save_template("ids", "sts get-caller-identity")
        ops.delete_template("ids")
        assert ops.list_templates() == []

    def test_destructive_template_blocked(self, ops):
        with pytest.raises(OperationError, match="destructive"):
            ops.save_template("boom", "ec2 terminate-instances --instance-ids i-1")


class TestRun:
    def test_run_uses_selection_and_profiles(self, ops):
        ops.generate_profiles(["111111111111"], "ReadOnly")
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"Account": "1"}', stderr="")
        with _logged_in(), patch("multi_aws_tool.execution.subprocess.run", return_value=done) as run:
            summary = ops.run("sts get-caller-identity", accounts=["Prod Account"])
        assert summary.successful_accounts == 1
        assert run.call_args.args[0][:3] == ["aws", "--profile", "mat-Prod-Account-ReadOnly"]

    def test_run_requires_login(self, ops):
        with _logged_in(False), pytest.raises(OperationError, match="not logged in"):
            ops.run("sts get-caller-identity", accounts=["111111111111"])


def test_cleanup_profiles_and_account_data(ops, aws_config):
    ops.generate_profiles(["111111111111"], "ReadOnly")
    result = ops.cleanup(profiles=True, account_data=True)
    assert result["profiles_removed"] == ["mat-Prod-Account-ReadOnly"]
    assert "sso-session acme" in aws_config.read_text()
    assert result["account_file_removed"]
    assert ops.accounts.get_accounts() == []


def _summary(outputs):
    results = [AccountResult(account_id=str(i), account_name=f"acc{i}", profile_name="p",
                             command="sts get-caller-identity", status="SUCCESS",
                             output=out, region="eu-west-1", exit_code=0)
               for i, out in enumerate(outputs)]
    return MultiAWSExecutionSummary(
        execution_id="x", command="sts get-caller-identity", timestamp="t",
        total_accounts=len(results), successful_accounts=len(results), failed_accounts=0,
        timeout_accounts=0, execution_mode="parallel", total_execution_time=1.234,
        results=results, config_used={"regions": ["eu-west-1"], "role": None},
    )


class TestSummarizeExecution:
    def test_parses_json(self):
        out = summarize_execution(_summary(['{"Account": "1"}', "plain text"]), 10000)
        assert out["results"][0]["output"] == {"Account": "1"}
        assert out["results"][1]["output"] == "plain text"
        assert out["truncated"] is False

    def test_truncates_long_output(self):
        out = summarize_execution(_summary(["x" * 5000]), 1000)
        assert out["truncated"] is True
        assert out["results"][0]["output_total_chars"] == 5000
        assert len(out["results"][0]["output"]) == 1000
