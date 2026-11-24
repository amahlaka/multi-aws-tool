"""
Tests for the local MCP server (multi_aws_tool.mcp_server)
"""

import asyncio
import json
import subprocess
from unittest.mock import patch

import pytest

from multi_aws_tool.aws.account_manager import AccountManager
from multi_aws_tool.config.manager import ConfigManager
from multi_aws_tool.mcp_server import (
    SelectionError,
    install_claude_desktop,
    select_accounts,
    summarize_execution,
)
from multi_aws_tool.models.account import Account, AccountCollection, AccountStatus
from multi_aws_tool.output import AccountResult, MultiAWSExecutionSummary


@pytest.fixture
def manager(tmp_path):
    mgr = AccountManager(account_file_path=str(tmp_path / "accounts.json"), profile_prefix="mat")
    collection = AccountCollection()
    collection.add_account(Account(id="111111111111", name="Prod Account", product_team="core",
                                   tags={"env": "prod"}, profile_name="mat-Prod-Account-ReadOnly"))
    collection.add_account(Account(id="222222222222", name="Dev Account", product_team="core",
                                   tags={"env": "dev"}, profile_name="mat-Dev-Account-ReadOnly"))
    collection.add_account(Account(id="333333333333", name="Old Account", product_team="core",
                                   tags={"env": "prod"}, status=AccountStatus.DISABLED))
    collection.add_account(Account(id="444444444444", name="Data Account", product_team="data",
                                   tags={"env": "prod"}))
    mgr.data_manager.save_accounts(collection)
    return mgr


class TestSelectAccounts:
    def test_requires_a_selector(self, manager):
        with pytest.raises(SelectionError):
            select_accounts(manager)

    def test_ids_and_names(self, manager):
        assert select_accounts(manager, ["111111111111", "dev account"]) == ["111111111111", "222222222222"]

    def test_unknown_name_raises(self, manager):
        with pytest.raises(SelectionError):
            select_accounts(manager, ["Nope"])

    def test_unknown_id_kept_for_error_reporting(self, manager):
        assert select_accounts(manager, ["999999999999"]) == ["999999999999"]

    def test_team_skips_inactive(self, manager):
        assert select_accounts(manager, team="core") == ["111111111111", "222222222222"]
        assert "333333333333" in select_accounts(manager, team="core", include_inactive=True)

    def test_multiple_teams(self, manager):
        assert select_accounts(manager, team="core, data") == ["111111111111", "222222222222", "444444444444"]

    def test_tags_alone_select_from_all(self, manager):
        assert select_accounts(manager, tags={"env": "prod"}) == ["111111111111", "444444444444"]

    def test_tags_narrow_team(self, manager):
        assert select_accounts(manager, team="core", tags={"env": "dev"}) == ["222222222222"]

    def test_all(self, manager):
        assert select_accounts(manager, ["all"]) == ["111111111111", "222222222222", "444444444444"]

    def test_explicit_inactive_account_kept(self, manager):
        assert select_accounts(manager, ["333333333333"]) == ["333333333333"]

    def test_empty_result_raises(self, manager):
        with pytest.raises(SelectionError):
            select_accounts(manager, team="core", tags={"env": "staging"})


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
        assert out["successful"] == 2

    def test_truncates_long_output(self):
        out = summarize_execution(_summary(["x" * 5000]), 1000)
        assert out["truncated"] is True
        assert out["results"][0]["output_truncated"] is True
        assert out["results"][0]["output_total_chars"] == 5000
        assert len(out["results"][0]["output"]) == 1000


class TestInstallClaudeDesktop:
    def test_preserves_existing_config(self, tmp_path):
        path = tmp_path / "claude_desktop_config.json"
        path.write_text(json.dumps({"preferences": {"a": 1}, "mcpServers": {"other": {"command": "x"}}}))
        install_claude_desktop(path)
        data = json.loads(path.read_text())
        assert data["preferences"] == {"a": 1}
        assert data["mcpServers"]["other"] == {"command": "x"}
        assert data["mcpServers"]["multi-aws"]["args"] == ["-m", "multi_aws_tool.mcp_server"]
        assert (tmp_path / "claude_desktop_config.json.bak").exists()

    def test_creates_missing_config(self, tmp_path):
        path = tmp_path / "Claude" / "claude_desktop_config.json"
        install_claude_desktop(path)
        assert "multi-aws" in json.loads(path.read_text())["mcpServers"]


class TestServerTools:
    """Exercise the registered tools through the MCP SDK."""

    @pytest.fixture
    def server(self, manager, tmp_path):
        from multi_aws_tool import mcp_server

        config = ConfigManager(str(tmp_path / "config.ini"))
        config.set("output", "path", str(tmp_path / "out"))
        with patch.object(mcp_server, "_account_manager_from_config", return_value=manager):
            yield mcp_server.build_server(config)

    @staticmethod
    def _call(server, name, args=None):
        result = asyncio.run(server.call_tool(name, args or {}))
        # SDK versions differ: (content, structured) tuple, CallToolResult, or content list
        if isinstance(result, tuple):
            result = result[1] if result[1] is not None else result[0]
        structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
        if structured is not None:
            return structured.get("result", structured)
        content = getattr(result, "content", result)
        if isinstance(content, dict):
            return content.get("result", content)
        texts = [json.loads(c.text) for c in content]
        return texts[0] if len(texts) == 1 else texts

    def test_lists_tools(self, server):
        tools = asyncio.run(server.list_tools())
        tools = getattr(tools, "tools", tools)
        assert {t.name for t in tools} == {"get_status", "list_accounts", "run_aws_command", "sso_login"}

    def test_list_accounts_filters(self, server):
        accounts = self._call(server, "list_accounts", {"team": "core"})
        assert [a["id"] for a in accounts] == ["222222222222", "111111111111"]  # sorted by name

    def test_run_requires_login(self, server, manager):
        with patch.object(AccountManager, "is_authenticated", return_value=False):
            out = self._call(server, "run_aws_command", {"command": "sts get-caller-identity",
                                                         "accounts": ["111111111111"]})
        assert "sso_login" in out["error"]

    def test_run_executes(self, server, manager):
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"Account": "111111111111"}', stderr="")
        with patch.object(AccountManager, "is_authenticated", return_value=True), \
                patch.object(AccountManager, "_available_profiles", return_value={"mat-Prod-Account-ReadOnly"}), \
                patch("multi_aws_tool.execution.subprocess.run", return_value=done) as run:
            out = self._call(server, "run_aws_command", {"command": "sts get-caller-identity",
                                                         "accounts": ["Prod Account"],
                                                         "regions": ["eu-west-1"]})
        assert out["successful"] == 1
        assert out["results"][0]["output"] == {"Account": "111111111111"}
        assert run.call_args.args[0][:5] == ["aws", "--profile", "mat-Prod-Account-ReadOnly", "--region", "eu-west-1"]

    def test_run_blocks_destructive(self, server):
        with patch.object(AccountManager, "is_authenticated", return_value=True):
            out = self._call(server, "run_aws_command", {"command": "ec2 terminate-instances --instance-ids i-1",
                                                         "accounts": ["111111111111"]})
        assert "destructive" in out["error"]
