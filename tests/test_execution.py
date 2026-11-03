"""
Tests for the library execution API (execute) and AccountManager profile/session helpers
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from multi_aws_tool.aws.account_manager import AccountManager, AccountManagerError
from multi_aws_tool.config.manager import ConfigManager
from multi_aws_tool.execution import ExecutionError, execute
from multi_aws_tool.models.account import Account, AccountCollection, AccountStatus
from multi_aws_tool.output import OutputParser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager(tmp_path):
    mgr = AccountManager(account_file_path=str(tmp_path / "accounts.json"), profile_prefix="mat")
    collection = AccountCollection()
    collection.add_account(Account(id="111111111111", name="Prod Account",
                                   status=AccountStatus.ACTIVE, profile_name="mat-Prod-Account-ReadOnly"))
    collection.add_account(Account(id="222222222222", name="Dev Account", status=AccountStatus.ACTIVE))
    mgr.data_manager.save_accounts(collection)
    return mgr


@pytest.fixture
def config(tmp_path):
    return ConfigManager(str(tmp_path / "config.ini"))  # defaults only, not loaded from disk


def _profiles(*names):
    return patch.object(AccountManager, "_available_profiles", return_value=set(names))


def _completed(stdout="{}", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# get_profile_name / get_session
# ---------------------------------------------------------------------------

class TestGetProfileName:
    def test_stored_profile_without_role(self, manager):
        with _profiles("mat-Prod-Account-ReadOnly"):
            assert manager.get_profile_name("111111111111") == "mat-Prod-Account-ReadOnly"

    def test_stored_profile_matching_role(self, manager):
        with _profiles("mat-Prod-Account-ReadOnly"):
            assert manager.get_profile_name("111111111111", "ReadOnly") == "mat-Prod-Account-ReadOnly"

    def test_conventional_name_for_other_role(self, manager):
        with _profiles("mat-Prod-Account-ReadOnly", "mat-Prod-Account-Admin"):
            assert manager.get_profile_name("111111111111", "Admin") == "mat-Prod-Account-Admin"

    def test_missing_profile_returns_none(self, manager):
        with _profiles():
            assert manager.get_profile_name("111111111111") is None
            assert manager.get_profile_name("222222222222", "ReadOnly") is None
            assert manager.get_profile_name("999999999999") is None


class TestGetSession:
    def test_uses_profile(self, manager):
        with _profiles("mat-Prod-Account-ReadOnly"), \
                patch("multi_aws_tool.aws.account_manager.boto3.Session") as session_cls:
            manager.get_session("111111111111", region="eu-west-1")
        session_cls.assert_called_once_with(profile_name="mat-Prod-Account-ReadOnly", region_name="eu-west-1")

    def test_falls_back_to_sso_role_credentials(self, manager):
        sso = MagicMock()
        sso.get_role_credentials.return_value = {"roleCredentials": {
            "accessKeyId": "AK", "secretAccessKey": "SK", "sessionToken": "TOK"}}
        with _profiles(), \
                patch.object(manager.sso_client, "_get_sso_client", return_value=sso), \
                patch.object(manager.sso_client, "get_access_token", return_value="token"), \
                patch("multi_aws_tool.aws.account_manager.boto3.Session") as session_cls:
            manager.get_session("222222222222", role="ReadOnly")
        sso.get_role_credentials.assert_called_once_with(
            roleName="ReadOnly", accountId="222222222222", accessToken="token")
        session_cls.assert_called_once_with(
            aws_access_key_id="AK", aws_secret_access_key="SK",
            aws_session_token="TOK", region_name="us-east-1")

    def test_no_profile_and_no_role_raises(self, manager):
        with _profiles(), pytest.raises(AccountManagerError):
            manager.get_session("222222222222")

    def test_unknown_account_raises(self, manager):
        with pytest.raises(AccountManagerError):
            manager.get_session("999999999999")


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

class TestExecute:
    def test_runs_each_account_region_pair(self, manager, config):
        with patch("multi_aws_tool.execution.subprocess.run",
                   return_value=_completed('{"Account": "111111111111"}')) as run:
            summary = execute("sts get-caller-identity", ["111111111111"],
                              regions=["eu-west-1", "us-east-1"],
                              account_manager=manager, config_manager=config)

        assert summary.total_accounts == 2
        assert summary.successful_accounts == 2
        assert summary.execution_mode == "parallel"
        assert [r.region for r in summary.results] == ["eu-west-1", "us-east-1"]
        assert summary.results[0].output_json() == {"Account": "111111111111"}
        assert run.call_args_list[0].args[0] == [
            "aws", "--profile", "mat-Prod-Account-ReadOnly", "--region", "eu-west-1",
            "--output", "json", "sts", "get-caller-identity"]

    def test_string_command_is_shell_split(self, manager, config):
        with patch("multi_aws_tool.execution.subprocess.run", return_value=_completed()) as run:
            execute("aws ec2 describe-instances --query 'Reservations[].Instances[]'",
                    ["111111111111"], account_manager=manager, config_manager=config)
        assert run.call_args.args[0][-4:] == [
            "ec2", "describe-instances", "--query", "Reservations[].Instances[]"]

    def test_missing_profile_and_unknown_account_are_errors(self, manager, config):
        with patch("multi_aws_tool.execution.subprocess.run", return_value=_completed()) as run:
            summary = execute("sts get-caller-identity", ["222222222222", "999999999999"],
                              account_manager=manager, config_manager=config)
        run.assert_not_called()
        assert summary.failed_accounts == 2
        assert {r.account_id for r in summary.get_failed_results()} == {"222222222222", "999999999999"}

    def test_failure_and_timeout_statuses(self, manager, config):
        effects = [_completed(stderr="AccessDenied", returncode=255),
                   subprocess.TimeoutExpired(cmd="aws", timeout=5)]
        with patch("multi_aws_tool.execution.subprocess.run", side_effect=effects):
            summary = execute(["s3", "ls"], ["111111111111"], regions=["a", "b"], parallel=False,
                              timeout=5, account_manager=manager, config_manager=config)
        assert [r.status for r in summary.results] == ["ERROR", "TIMEOUT"]
        assert summary.results[0].exit_code == 255
        assert summary.timeout_accounts == 1

    def test_destructive_command_blocked(self, manager, config):
        with pytest.raises(ExecutionError):
            execute("ec2 terminate-instances --instance-ids i-123", ["111111111111"],
                    account_manager=manager, config_manager=config)

    def test_dry_run_does_not_execute(self, manager, config):
        with patch("multi_aws_tool.execution.subprocess.run") as run:
            summary = execute("s3 ls", ["111111111111"], dry_run=True,
                              account_manager=manager, config_manager=config)
        run.assert_not_called()
        assert summary.successful_accounts == 1

    def test_on_result_callback(self, manager, config):
        seen = []
        with patch("multi_aws_tool.execution.subprocess.run", return_value=_completed()):
            execute("s3 ls", ["111111111111"], regions=["a", "b", "c"], on_result=seen.append,
                    account_manager=manager, config_manager=config)
        assert sorted(r.region for r in seen) == ["a", "b", "c"]

    def test_summary_save_round_trip(self, manager, config, tmp_path):
        with patch("multi_aws_tool.execution.subprocess.run", return_value=_completed('{"ok": 1}')):
            summary = execute("s3 ls", ["111111111111"], regions="eu-north-1",
                              account_manager=manager, config_manager=config)
        path = summary.save(tmp_path / "out")
        parsed = OutputParser().parse_execution_summary(path)
        assert parsed.successful_accounts == 1
        assert parsed.results[0].region == "eu-north-1"
        assert json.loads(path.read_text())["command"] == "s3 ls"


# ---------------------------------------------------------------------------
# CLI `run` (now backed by execute)
# ---------------------------------------------------------------------------

class TestRunCommand:
    def _invoke(self, args, tmp_path, stdout='{"ok": 1}'):
        from click.testing import CliRunner
        from multi_aws_tool.cli.commands import AppContext, cli

        collection = AccountCollection()
        collection.add_account(Account(id="111111111111", name="Prod Account", status=AccountStatus.ACTIVE,
                                       profile_name="mat-Prod-Account-ReadOnly", product_team="core"))
        am = MagicMock()
        am.get_account.side_effect = collection.get_account

        config_mock = MagicMock()
        config_mock.get.side_effect = lambda s, k, fallback=None: {
            ('general', 'region'): 'eu-west-1',
            ('output', 'format'): 'json',
            ('output', 'pattern'): '!A/!S-!C-!R',
            ('output', 'path'): str(tmp_path),
        }.get((s, k), fallback)
        config_mock.get_bool.return_value = False

        with patch('multi_aws_tool.cli.commands.get_account_manager', return_value=am), \
                patch('multi_aws_tool.cli.commands.load_or_create_config', return_value=config_mock), \
                patch.object(AppContext, 'ensure_authenticated', return_value=None), \
                patch('os.get_terminal_size', return_value=(120, 40)), \
                patch('multi_aws_tool.execution.subprocess.run', return_value=_completed(stdout)) as run:
            result = CliRunner().invoke(cli, ['run', '--accounts', '111111111111', *args],
                                        catch_exceptions=False)
        return result, run

    @pytest.mark.parametrize("cmd_args", [
        # separate arguments after --
        ['--', 'ec2', 'describe-instances', '--query', 'Reservations[?State == `running`]'],
        # one quoted string, as shown in the README
        ["ec2 describe-instances --query 'Reservations[?State == `running`]'"],
    ])
    def test_arguments_with_spaces_are_not_quoted(self, tmp_path, cmd_args):
        result, run = self._invoke(cmd_args, tmp_path)
        assert result.exit_code == 0, result.output
        aws_cmd = run.call_args.args[0]
        assert aws_cmd[-4:] == ['ec2', 'describe-instances', '--query', 'Reservations[?State == `running`]']
        assert not any(part.startswith('"') for part in aws_cmd)

    def test_save_writes_result_file_and_legacy_summary(self, tmp_path):
        result, _ = self._invoke(['--save', 'sts get-caller-identity'], tmp_path)
        assert result.exit_code == 0, result.output
        assert "Successful: 1" in result.output

        result_file = tmp_path / "Prod_Account" / "sts-get-caller-identity-eu-west-1.json"
        assert json.loads(result_file.read_text()) == {"ok": 1}

        [summary_file] = tmp_path.glob("execution_summary_*.json")
        records = json.loads(summary_file.read_text())
        assert isinstance(records, list)
        assert records[0]["status"] == "success"
        assert records[0]["team"] == "core"
        assert records[0]["command"] == "sts get-caller-identity"
        assert records[0]["region"] == "eu-west-1"
        assert records[0]["output_file"] == str(result_file)
        # Still readable by the output parser
        assert OutputParser().parse_execution_summary(summary_file).successful_accounts == 1


class TestNoTerminal:
    def test_cli_runs_without_a_tty(self, tmp_path):
        """Commands must not crash when stdout isn't a terminal (pipes, CI, cron)."""
        from click.testing import CliRunner
        from multi_aws_tool.cli.commands import _terminal_columns, cli

        with patch('os.get_terminal_size', side_effect=OSError(25, "Inappropriate ioctl for device")):
            assert _terminal_columns() > 0
            result = CliRunner().invoke(cli, ['clean-duplicates', '--dry-run'],
                                        env={'HOME': str(tmp_path)})
        assert result.exit_code == 0, result.output
        assert "SET SIZE" not in result.output
