"""
Local MCP (Model Context Protocol) server for multi-aws.

Lets MCP clients such as Claude Desktop and Claude Code run AWS CLI commands
across your accounts with the same config (``~/.multi-aws/config.ini``),
account data and SSO profiles that the ``multi-aws`` CLI uses. It runs over
stdio on your machine, so credentials never leave it.

Install and register with Claude Desktop::

    pip install 'multi-aws-tool[mcp]'
    multi-aws-mcp --install-claude-desktop

Destructive commands follow the ``security.allow-destructive-commands`` config
setting; the MCP client cannot override it.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .aws.account_manager import AccountManager
from .config.manager import ConfigManager
from .execution import ExecutionError, _account_manager_from_config, _load_config, execute
from .models.account import Account
from .output import MultiAWSExecutionSummary

SERVER_NAME = "multi-aws"

SERVER_INSTRUCTIONS = """\
Runs AWS CLI commands across the user's AWS accounts using their local
multi-aws configuration, SSO session and AWS CLI profiles.

Typical flow:
1. Call get_status to check the SSO session and see the defaults.
2. Call list_accounts to find account IDs, teams, tags and available roles.
3. Call run_aws_command with the command (without the leading 'aws') and
   select accounts by ID, team and/or tags. Prefer --query to keep output small.
If SSO is not authenticated, call sso_login (opens a browser for the user).
Destructive commands are rejected unless the user enabled them in their config.
"""

# Directories where the AWS CLI is commonly installed. GUI apps like Claude
# Desktop start servers with a minimal PATH, so we add these if aws is missing.
_EXTRA_PATH_DIRS = ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")


class SelectionError(ValueError):
    """Raised when an account selection is invalid or empty."""


# ---------------------------------------------------------------------------
# Helpers (independent of the MCP SDK so they can be unit tested)
# ---------------------------------------------------------------------------

def ensure_aws_on_path() -> Optional[str]:
    """Return the aws CLI path, extending PATH with common locations if needed."""
    found = shutil.which("aws")
    if found:
        return found
    current = os.environ.get("PATH", "").split(os.pathsep)
    extra = [str(Path(d).expanduser()) for d in _EXTRA_PATH_DIRS]
    os.environ["PATH"] = os.pathsep.join(current + [d for d in extra if d not in current])
    return shutil.which("aws")


def account_to_dict(account: Account) -> Dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "status": account.status.value,
        "team": account.product_team,
        "tags": dict(account.tags),
        "roles": [role.name for role in account.roles],
        "profile": account.profile_name,
    }


def select_accounts(
    manager: AccountManager,
    accounts: Optional[List[str]] = None,
    team: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    include_inactive: bool = False,
) -> List[str]:
    """
    Resolve account selectors to a list of account IDs (same rules as ``multi-aws run``).

    ``accounts`` takes IDs or exact account names; ``["all"]`` means every account.
    ``team`` may be a comma-separated list. ``tags`` narrows the selection
    (and on its own selects from all accounts). Inactive accounts are dropped
    unless ``include_inactive`` is set or they were requested explicitly by ID.
    """
    if not accounts and not team and not tags:
        raise SelectionError("Specify accounts, team and/or tags to select accounts")

    all_accounts = manager.get_accounts()
    by_id = {acc.id: acc for acc in all_accounts}
    selected: List[str] = []
    explicit: set = set()

    def add(account_id: str) -> None:
        if account_id not in selected:
            selected.append(account_id)

    if accounts:
        for item in accounts:
            item = str(item).strip()
            if not item:
                continue
            if item.lower() == "all":
                for acc in all_accounts:
                    add(acc.id)
                continue
            if item in by_id or item.isdigit():
                add(item)  # unknown IDs are kept so execute() reports them
                explicit.add(item)
                continue
            matches = [acc for acc in all_accounts if acc.name.lower() == item.lower()]
            if not matches:
                raise SelectionError(f"No account with ID or name '{item}'")
            for acc in matches:
                add(acc.id)
                explicit.add(acc.id)

    if team:
        for team_name in (t.strip() for t in team.split(",")):
            if not team_name:
                continue
            team_accounts = manager.get_accounts_by_team(team_name)
            if not team_accounts:
                raise SelectionError(f"No accounts in team '{team_name}'")
            for acc in team_accounts:
                add(acc.id)

    if tags:
        tagged = {acc.id for acc in manager.get_accounts_by_tags(tags)}
        if not accounts and not team:
            selected = [acc.id for acc in all_accounts if acc.id in tagged]
        else:
            selected = [aid for aid in selected if aid in tagged]

    if not include_inactive:
        selected = [
            aid for aid in selected
            if aid in explicit or aid not in by_id or by_id[aid].is_active()
        ]

    if not selected:
        raise SelectionError("The selection matched no accounts")
    return selected


def summarize_execution(summary: MultiAWSExecutionSummary, max_output_chars: int) -> Dict[str, Any]:
    """
    Turn an execution summary into a compact, JSON-friendly tool result.

    Outputs are parsed as JSON when possible. The total output is capped at
    ``max_output_chars``, split evenly across results; truncated outputs are
    returned as raw text with ``output_truncated`` set.
    """
    results = summary.results
    budget = max(500, max_output_chars // max(1, len(results)))
    truncated = False
    items = []
    for r in results:
        item: Dict[str, Any] = {
            "account_id": r.account_id,
            "account_name": r.account_name,
            "region": r.region,
            "status": r.status,
        }
        output = (r.output or "").strip()
        if output:
            if len(output) > budget:
                item["output"] = output[:budget]
                item["output_truncated"] = True
                item["output_total_chars"] = len(output)
                truncated = True
            else:
                try:
                    item["output"] = json.loads(output)
                except ValueError:
                    item["output"] = output
        error = (r.error or "").strip()
        if error:
            item["error"] = error[:2000]
        if r.exit_code not in (None, 0):
            item["exit_code"] = r.exit_code
        items.append(item)

    return {
        "command": summary.command,
        "regions": summary.config_used.get("regions"),
        "role": summary.config_used.get("role"),
        "total": summary.total_accounts,
        "successful": summary.successful_accounts,
        "failed": summary.failed_accounts,
        "timed_out": summary.timeout_accounts,
        "execution_time_seconds": round(summary.total_execution_time, 2),
        "truncated": truncated,
        "results": items,
    }


def claude_desktop_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def server_launch_config() -> Dict[str, Any]:
    """The mcpServers entry that launches this server with the current Python."""
    entry: Dict[str, Any] = {
        "command": sys.executable,
        "args": ["-m", "multi_aws_tool.mcp_server"],
    }
    aws_path = shutil.which("aws")
    if aws_path:
        # Claude Desktop starts servers with a minimal PATH; make sure aws is found.
        path_dirs = [str(Path(aws_path).parent), "/usr/local/bin", "/usr/bin", "/bin"]
        entry["env"] = {"PATH": os.pathsep.join(dict.fromkeys(path_dirs))}
    return entry


def install_claude_desktop(config_path: Optional[Path] = None, name: str = SERVER_NAME) -> Path:
    """Add (or update) this server in Claude Desktop's config, keeping everything else."""
    config_path = config_path or claude_desktop_config_path()
    data: Dict[str, Any] = {}
    if config_path.exists():
        text = config_path.read_text()
        if text.strip():
            data = json.loads(text)
        backup = config_path.with_suffix(config_path.suffix + ".bak")
        backup.write_text(text)
    data.setdefault("mcpServers", {})[name] = server_launch_config()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2) + "\n")
    return config_path


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

def _import_sdk():
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x
        except ImportError as e:
            raise ImportError(
                "The MCP server needs the 'mcp' package (Python >= 3.10). "
                "Install it with: pip install 'multi-aws-tool[mcp]'"
            ) from e
    from mcp.types import ToolAnnotations
    return Server, ToolAnnotations


def build_server(config_manager: Optional[ConfigManager] = None):
    """Create the MCP server with all multi-aws tools registered."""
    import anyio

    Server, ToolAnnotations = _import_sdk()
    server = Server(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

    def load():
        # Reload on each call so config/account changes made via the CLI are picked up.
        cfg = config_manager or _load_config()
        return cfg, _account_manager_from_config(cfg)

    def annotations(**hints):
        return ToolAnnotations.model_validate(hints)

    @server.tool(annotations=annotations(readOnlyHint=True, openWorldHint=False))
    async def get_status() -> Dict[str, Any]:
        """Show the multi-aws configuration, SSO login state and account/team overview."""
        def work():
            cfg, manager = load()
            accounts = manager.get_accounts()
            teams = sorted({a.product_team for a in accounts if a.product_team})
            return {
                "config_file": str(cfg.paths.config_file),
                "sso_session": manager.sso_client.sso_session_name,
                "default_region": cfg.get("general", "region", "us-east-1"),
                "profile_prefix": manager.profile_prefix,
                "output_format": cfg.get("output", "format", "json"),
                "allow_destructive_commands": cfg.get_bool("security", "allow-destructive-commands", False),
                "sso_authenticated": manager.is_authenticated(),
                "aws_cli": shutil.which("aws"),
                "accounts_total": len(accounts),
                "accounts_active": sum(1 for a in accounts if a.is_active()),
                "teams": teams,
            }
        return await anyio.to_thread.run_sync(work)

    @server.tool(annotations=annotations(readOnlyHint=True, openWorldHint=False))
    async def list_accounts(
        team: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        role: Optional[str] = None,
        name_contains: Optional[str] = None,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        List known AWS accounts with their team, tags, SSO roles and profile.

        Args:
            team: Only accounts in this product team (comma-separated for several).
            tags: Only accounts having all of these tag key/value pairs.
            role: Only accounts where this SSO role (permission set) is available.
            name_contains: Case-insensitive substring match on the account name.
            include_inactive: Also include disabled/suspended accounts.
        """
        def work():
            _, manager = load()
            accounts = manager.get_accounts()
            if team:
                teams = {t.strip() for t in team.split(",") if t.strip()}
                accounts = [a for a in accounts if a.product_team in teams]
            if tags:
                accounts = [a for a in accounts if all(a.tags.get(k) == v for k, v in tags.items())]
            if role:
                accounts = [a for a in accounts if a.has_role(role)]
            if name_contains:
                accounts = [a for a in accounts if name_contains.lower() in a.name.lower()]
            if not include_inactive:
                accounts = [a for a in accounts if a.is_active()]
            return [account_to_dict(a) for a in sorted(accounts, key=lambda a: a.name.lower())]
        return await anyio.to_thread.run_sync(work)

    @server.tool(annotations=annotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True))
    async def run_aws_command(
        command: str,
        accounts: Optional[List[str]] = None,
        team: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        regions: Optional[List[str]] = None,
        role: Optional[str] = None,
        include_inactive: bool = False,
        timeout: int = 120,
        max_output_chars: int = 40000,
        save: bool = False,
    ) -> Dict[str, Any]:
        """
        Run an AWS CLI command in one or more accounts (and regions) in parallel.

        Uses the user's AWS CLI SSO profiles, exactly like `multi-aws run`.
        Destructive commands (delete/terminate/put/...) are rejected unless the
        user has enabled allow-destructive-commands in their multi-aws config.

        Args:
            command: AWS CLI command without the leading 'aws', e.g.
                "ec2 describe-instances --query 'Reservations[].Instances[].InstanceId'".
                Don't pass --profile/--region/--output; they are set per account.
            accounts: Account IDs or exact account names; ["all"] for every account.
            team: Product team name(s), comma-separated.
            tags: Account tag key/value pairs the accounts must all have.
            regions: Regions to run in; ["all"] for every enabled region.
                Defaults to the configured region.
            role: SSO role (permission set) whose profile to use, e.g. "ReadOnlyAccess".
                Defaults to each account's stored profile.
            include_inactive: Include disabled accounts selected via team/tags/"all".
            timeout: Per account/region timeout in seconds.
            max_output_chars: Cap on the total output returned; longer outputs are truncated.
            save: Also save the full results to the configured output directory.
        """
        def work():
            cfg, manager = load()
            try:
                account_ids = select_accounts(manager, accounts, team, tags, include_inactive)
            except SelectionError as e:
                return {"error": str(e)}
            if not manager.is_authenticated():
                return {"error": f"SSO session '{manager.sso_client.sso_session_name}' is not logged in or has "
                                 "expired. Call sso_login, or run 'aws sso login' in a terminal."}

            if not regions:
                region_arg = None
            elif len(regions) == 1 and regions[0].lower() == "all":
                region_arg = "all"
            else:
                region_arg = list(regions)

            try:
                summary = execute(
                    command,
                    accounts=account_ids,
                    regions=region_arg,
                    parallel=True,
                    role=role,
                    timeout=max(1, min(timeout, 900)),
                    account_manager=manager,
                    config_manager=cfg,
                )
            except ExecutionError as e:
                return {"error": str(e)}
            except Exception as e:  # e.g. listing regions failed
                return {"error": f"{type(e).__name__}: {e}"}

            result = summarize_execution(summary, max(1000, max_output_chars))
            if save or result["truncated"]:
                output_dir = cfg.get("output", "path", "~/.multi-aws/outputs/")
                try:
                    result["saved_to"] = str(summary.save(Path(output_dir).expanduser() / "mcp"))
                except OSError as e:
                    result["save_error"] = str(e)
            if result["truncated"]:
                result["note"] = ("Some outputs were truncated (full results saved to 'saved_to'). "
                                  "Use --query to narrow the output or raise max_output_chars.")
            return result
        return await anyio.to_thread.run_sync(work)

    @server.tool(annotations=annotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
    async def sso_login() -> Dict[str, Any]:
        """
        Log in to the configured AWS SSO session (runs `aws sso login`).

        Opens the user's browser for approval and waits up to 5 minutes.
        """
        def work():
            _, manager = load()
            if manager.is_authenticated():
                return {"authenticated": True, "message": "Already logged in"}
            try:
                proc = subprocess.run(
                    ["aws", "sso", "login", "--sso-session", manager.sso_client.sso_session_name],
                    capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                return {"authenticated": False, "error": "AWS CLI (aws) not found on PATH"}
            except subprocess.TimeoutExpired:
                return {"authenticated": False, "error": "Timed out waiting for browser approval"}
            ok = proc.returncode == 0 and manager.is_authenticated()
            out = {"authenticated": ok}
            if not ok:
                out["error"] = (proc.stderr or proc.stdout or "aws sso login failed").strip()[-2000:]
            return out
        return await anyio.to_thread.run_sync(work)

    return server


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="multi-aws-mcp",
        description="Local MCP server (stdio) exposing multi-aws to Claude Desktop and other MCP clients.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--print-config", action="store_true",
                       help="Print the mcpServers JSON entry for this server and exit")
    group.add_argument("--install-claude-desktop", action="store_true",
                       help="Add this server to Claude Desktop's config (a .bak backup is kept)")
    args = parser.parse_args(argv)

    if args.print_config:
        print(json.dumps({"mcpServers": {SERVER_NAME: server_launch_config()}}, indent=2))
        return
    if args.install_claude_desktop:
        path = install_claude_desktop()
        print(f"Added '{SERVER_NAME}' MCP server to {path}")
        print("Restart Claude Desktop to load it.")
        return

    ensure_aws_on_path()
    build_server().run()


if __name__ == "__main__":
    main()
