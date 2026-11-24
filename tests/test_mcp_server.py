"""
Tests for the local MCP server (multi_aws_tool.mcp_server)
"""

import asyncio
import json
import subprocess
from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from multi_aws_tool.aws.account_manager import AccountManager
from multi_aws_tool.config.manager import ConfigManager
from multi_aws_tool.mcp_server import build_server, install_claude_desktop
from multi_aws_tool.models.account import Account, AccountCollection, Role
from multi_aws_tool.services import MultiAWS

EXPECTED_TOOLS = {
    "get_status", "get_config", "update_config", "list_sso_sessions", "add_sso_session", "sso_login",
    "discover_accounts", "list_accounts", "fetch_roles", "generate_profiles", "sync_profiles",
    "sanitize_account_names", "clean_duplicate_profiles", "list_teams", "assign_team", "set_tags",
    "remove_tags", "sync_tags", "list_templates", "save_template", "delete_template",
    "run_aws_command", "run_template", "cleanup",
}


@pytest.fixture
def server(tmp_path, monkeypatch):
    aws_config = tmp_path / "aws-config"
    aws_config.write_text("[sso-session acme]\nsso_start_url = https://acme.awsapps.com/start\nsso_region = eu-west-1\n")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(aws_config))

    config = ConfigManager(str(tmp_path / "config.ini"))
    config.set("general", "prefix", "mat")
    config.set("general", "sso-session", "acme")
    config.set("general", "account-file", str(tmp_path / "accounts.json"))
    config.set("general", "templates-file", str(tmp_path / "templates.json"))
    config.set("output", "path", str(tmp_path / "out"))

    ops = MultiAWS(config)
    collection = AccountCollection()
    collection.add_account(Account(id="111111111111", name="Prod Account", product_team="core",
                                   roles=[Role("ReadOnly", "arn:aws:iam::111111111111:role/ReadOnly")]))
    collection.add_account(Account(id="222222222222", name="Dev Account", product_team="core"))
    ops.accounts.data_manager.save_accounts(collection)
    return build_server(ops_factory=lambda: MultiAWS(config))


def call(server, name, args=None):
    result = asyncio.run(server.call_tool(name, args or {}))
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured.get("result", structured)
    texts = [json.loads(c.text) for c in result.content]
    return texts[0] if len(texts) == 1 else texts


def test_registers_all_tools_and_prompt(server):
    tools = asyncio.run(server.list_tools())
    tools = getattr(tools, "tools", tools)
    assert {t.name for t in tools} == EXPECTED_TOOLS
    by_name = {t.name: t for t in tools}
    assert by_name["list_accounts"].annotations.read_only_hint is True
    assert by_name["run_aws_command"].annotations.destructive_hint is True
    assert "settings" in by_name["update_config"].input_schema["properties"]

    prompts = asyncio.run(server.list_prompts())
    prompts = getattr(prompts, "prompts", prompts)
    assert [p.name for p in prompts] == ["getting_started"]


def test_getting_started_prompt(server):
    result = asyncio.run(server.get_prompt("getting_started", {}))
    text = result.messages[0].content.text
    assert "add_sso_session" in text and "generate_profiles" in text


def test_status_and_accounts(server):
    with patch.object(AccountManager, "is_authenticated", return_value=False):
        status = call(server, "get_status")
    assert status["next_step"]["step"] in ("aws_cli", "config", "sso_login")
    accounts = call(server, "list_accounts", {"team": "core"})
    assert [a["id"] for a in accounts] == ["222222222222", "111111111111"]


def test_expected_errors_become_tool_errors(server):
    with pytest.raises(ToolError, match="security.allow-destructive-commands"):
        call(server, "update_config", {"settings": {"security.allow-destructive-commands": "true"}})
    with pytest.raises(ToolError, match="No account"):
        call(server, "fetch_roles", {"accounts": ["Nope"]})
    with pytest.raises(ToolError, match="confirm"):
        call(server, "cleanup", {"confirm": False, "tokens": True})


def test_generate_profiles_and_run(server):
    out = call(server, "generate_profiles", {"role": "ReadOnly", "team": "core"})
    assert out["created"] == ["mat-Prod-Account-ReadOnly"]
    assert out["skipped"][0]["id"] == "222222222222"

    done = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"Account": "111111111111"}', stderr="")
    with patch.object(AccountManager, "is_authenticated", return_value=True), \
            patch("multi_aws_tool.execution.subprocess.run", return_value=done) as run:
        out = call(server, "run_aws_command", {"command": "sts get-caller-identity",
                                               "accounts": ["Prod Account"], "regions": ["eu-west-1"]})
    assert out["successful"] == 1
    assert out["results"][0]["output"] == {"Account": "111111111111"}
    assert run.call_args.args[0][:5] == ["aws", "--profile", "mat-Prod-Account-ReadOnly", "--region", "eu-west-1"]


def test_run_requires_login(server):
    with patch.object(AccountManager, "is_authenticated", return_value=False), \
            pytest.raises(ToolError, match="sso_login"):
        call(server, "run_aws_command", {"command": "sts get-caller-identity", "accounts": ["111111111111"]})


def test_run_blocks_destructive(server):
    with patch.object(AccountManager, "is_authenticated", return_value=True), \
            pytest.raises(ToolError, match="destructive"):
        call(server, "run_aws_command", {"command": "ec2 terminate-instances --instance-ids i-1",
                                         "accounts": ["111111111111"]})


def test_templates_roundtrip(server):
    call(server, "save_template", {"name": "whoami", "command": "sts get-caller-identity", "team": "core"})
    assert call(server, "list_templates")[0]["team"] == "core"
    done = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}", stderr="")
    call(server, "generate_profiles", {"role": "ReadOnly", "accounts": ["111111111111"]})
    with patch.object(AccountManager, "is_authenticated", return_value=True), \
            patch("multi_aws_tool.execution.subprocess.run", return_value=done):
        out = call(server, "run_template", {"name": "whoami"})
    # Dev Account has no profile, so it reports an error rather than being skipped
    assert out["total"] == 2 and out["successful"] == 1
    call(server, "delete_template", {"name": "whoami"})
    assert call(server, "list_templates") == []


def test_teams_and_tags(server):
    call(server, "assign_team", {"team": "platform", "accounts": ["222222222222"], "overwrite": True})
    assert call(server, "list_teams") == {"core": 1, "platform": 1}
    call(server, "set_tags", {"tags": {"env": "prod"}, "team": "platform"})
    assert call(server, "list_accounts", {"tags": {"env": "prod"}})[0]["id"] == "222222222222"
    call(server, "remove_tags", {"keys": ["env"], "accounts": ["222222222222"]})
    assert call(server, "list_accounts", {"tags": {"env": "prod"}}) == []


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
