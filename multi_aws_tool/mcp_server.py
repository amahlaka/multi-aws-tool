"""
Local MCP (Model Context Protocol) server for multi-aws.

Exposes the whole tool (onboarding, SSO, account discovery, roles, profiles,
teams, tags, templates and running commands) to MCP clients such as Claude
Desktop and Claude Code. It uses the same config (``~/.multi-aws/config.ini``),
account data, SSO session and AWS CLI profiles as the ``multi-aws`` CLI, and
runs over stdio on your machine, so credentials never leave it.

Register with Claude Desktop::

    multi-aws-mcp --install-claude-desktop

Destructive AWS commands follow the ``security.allow-destructive-commands``
config setting, which the MCP client can neither override nor change.
"""

import argparse
import functools
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .aws.account_manager import AccountManagerError
from .aws.sso_client import SSOAuthenticationError
from .config.manager import ConfigManager, ConfigurationError
from .config.template_manager import TemplateError
from .execution import ExecutionError
from .services import MultiAWS, OperationError, summarize_execution
from .utils.account_data import AccountDataError

SERVER_NAME = "multi-aws"

SERVER_INSTRUCTIONS = """\
multi-aws runs AWS CLI commands across many AWS accounts using the user's own
AWS IAM Identity Center (SSO) login and AWS CLI profiles, all on their machine.

Start with get_status: it reports which setup step is next. For a new user,
or if they ask how to get started, follow the 'getting_started' prompt
(setup walkthrough): AWS CLI -> config -> SSO session -> login -> discover
accounts -> fetch roles -> generate profiles -> optional teams/tags/templates.

Running commands: pass the AWS CLI command without the leading 'aws' and
select accounts by ID/name, team and/or tags. Prefer --query to keep output
small. If SSO has expired, call sso_login (the user approves in the browser).
Destructive commands are rejected unless the user enabled them in their
config; you cannot change that setting. Tools that edit ~/.aws/config keep
a timestamped backup; offer dry_run first for bulk changes.
"""

GETTING_STARTED = """\
Walk me through setting up multi-aws step by step. Be concise and friendly,
do one step at a time, and confirm with me before anything that writes files.

1. Call get_status and briefly tell me where I am (which steps are done).
2. AWS CLI: if it's missing, tell me how to install AWS CLI v2 and stop until
   I've done it.
3. Config: show the defaults (profile prefix, default region, output folder)
   and ask if I want to change any; save with update_config.
4. SSO session: call list_sso_sessions. If I already have one, ask which to
   use and set general.sso-session. Otherwise ask for my AWS access portal URL
   (https://<something>.awsapps.com/start) and the region where IAM Identity
   Center is set up, then call add_sso_session.
5. Log in with sso_login and tell me to approve the request in my browser.
6. Discover my accounts with discover_accounts and summarise what was found.
7. Fetch roles for all accounts with fetch_roles (accounts=["all"]); it may
   take a minute for many accounts. Show the most common roles.
8. Ask which role to use by default (suggest a read-only one if available),
   preview with generate_profiles dry_run=true, then create the profiles.
9. Verify by running "sts get-caller-identity" in one or two accounts.
10. Optionally help me organise accounts: assign teams (assign_team), sync
    tags from AWS Organizations (sync_tags) or set them manually (set_tags),
    and save a couple of useful command templates (save_template).
11. Finish with a few example questions I can ask you, e.g. "list running
    EC2 instances in the <team> accounts".
"""

# Directories where the AWS CLI is commonly installed. GUI apps like Claude
# Desktop start servers with a minimal PATH, so we add these if aws is missing.
_EXTRA_PATH_DIRS = ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")

_EXPECTED_ERRORS = (
    OperationError, AccountManagerError, AccountDataError, ConfigurationError,
    TemplateError, ExecutionError, SSOAuthenticationError, ValueError,
)


# ---------------------------------------------------------------------------
# Setup helpers
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

def build_server(config_manager: Optional[ConfigManager] = None,
                 ops_factory: Optional[Callable[[], MultiAWS]] = None):
    """Create the MCP server with all multi-aws tools registered."""
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    server = MCPServer(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

    def ops() -> MultiAWS:
        # Fresh each call so changes made via the CLI (config, accounts) are picked up.
        return ops_factory() if ops_factory else MultiAWS(config_manager)

    def tool(read_only: bool = False, destructive: bool = False, open_world: bool = False,
             idempotent: bool = False):
        """Register a sync tool; expected errors reach the model as tool errors."""
        annotations = ToolAnnotations.model_validate({
            "readOnlyHint": read_only, "destructiveHint": destructive,
            "openWorldHint": open_world, "idempotentHint": idempotent,
        })

        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except _EXPECTED_ERRORS as e:
                    raise ToolError(str(e)) from e
            server.tool(annotations=annotations)(wrapper)
            return fn
        return decorator

    def selection(o: MultiAWS, accounts, team, tags, include_inactive=False) -> List[str]:
        return o.select_accounts(accounts, team, tags, include_inactive)

    # -- status & setup -------------------------------------------------------

    @tool(read_only=True)
    def get_status() -> Dict[str, Any]:
        """
        Setup checklist and overview: which onboarding step is next, SSO login
        state, defaults, teams and most common roles. Call this first.
        """
        return ops().setup_status()

    @tool(read_only=True)
    def get_config() -> Dict[str, Any]:
        """Show all multi-aws settings (~/.multi-aws/config.ini)."""
        return ops().get_config()

    @tool(idempotent=True)
    def update_config(settings: Dict[str, str]) -> Dict[str, Any]:
        """
        Change multi-aws settings; creates the config file if missing.

        Args:
            settings: {"section.key": value}, e.g. {"general.region": "eu-west-1",
                "general.prefix": "acme", "output.path": "~/aws-reports"}. Keys:
                general.prefix/sso-session/region/account-file/templates-file,
                output.pattern/format/path, execution.mode/stop-on-errors,
                logging.level/file/console/max-size/backup-count.
                security.* can only be changed by the user directly.
        """
        return ops().update_config(settings)

    @tool(read_only=True)
    def list_sso_sessions() -> Dict[str, Any]:
        """List the SSO sessions in ~/.aws/config and which one multi-aws uses."""
        return ops().list_sso_sessions()

    @tool()
    def add_sso_session(name: str, start_url: str, sso_region: str,
                        overwrite: bool = False, make_default: bool = True) -> Dict[str, Any]:
        """
        Add an IAM Identity Center (SSO) session to ~/.aws/config (backup kept).

        Args:
            name: Session name, e.g. "my-org".
            start_url: AWS access portal URL, e.g. https://my-org.awsapps.com/start
            sso_region: Region where IAM Identity Center is set up, e.g. eu-west-1.
            overwrite: Replace an existing session with the same name.
            make_default: Make multi-aws use this session.
        """
        return ops().add_sso_session(name, start_url, sso_region, overwrite, make_default)

    @tool(open_world=True)
    def sso_login() -> Dict[str, Any]:
        """
        Log in to the configured SSO session (runs `aws sso login`). Opens the
        user's browser for approval and waits up to 5 minutes.
        """
        return ops().sso_login()

    # -- accounts & roles --------------------------------------------------------

    @tool(open_world=True)
    def discover_accounts(sanitize_names: bool = True) -> Dict[str, Any]:
        """
        Discover all accounts the user can access via SSO and store them
        locally (like `multi-aws init`). Accounts no longer accessible are
        marked disabled. Requires SSO login.
        """
        return ops().discover_accounts(sanitize_names)

    @tool(read_only=True)
    def list_accounts(team: Optional[str] = None, tags: Optional[Dict[str, str]] = None,
                      role: Optional[str] = None, name_contains: Optional[str] = None,
                      include_inactive: bool = False) -> List[Dict[str, Any]]:
        """
        List known accounts with their team, tags, SSO roles and profile.

        Args:
            team: Only accounts in this team (comma-separated for several).
            tags: Only accounts having all these tag key/values.
            role: Only accounts where this SSO role is available.
            name_contains: Case-insensitive substring of the account name.
            include_inactive: Include disabled accounts.
        """
        return ops().list_accounts(team, tags, role, name_contains, include_inactive)

    @tool(open_world=True, idempotent=True)
    def fetch_roles(accounts: Optional[List[str]] = None, team: Optional[str] = None,
                    tags: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Fetch the SSO roles (permission sets) available in accounts and store
        them. Use accounts=["all"] for everything. Requires SSO login.
        """
        o = ops()
        return o.fetch_roles(selection(o, accounts, team, tags))

    # -- profiles ------------------------------------------------------------------

    @tool(idempotent=True)
    def generate_profiles(role: str, accounts: Optional[List[str]] = None,
                          team: Optional[str] = None, tags: Optional[Dict[str, str]] = None,
                          region: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        """
        Create or update AWS CLI SSO profiles (<prefix>-<account>-<role>) in
        ~/.aws/config for the selected accounts (backup kept). Accounts where
        the role isn't available are skipped. Run fetch_roles first.

        Args:
            role: SSO role / permission set name, e.g. "ReadOnlyAccess".
            accounts: Account IDs or names, or ["all"].
            team: Team name(s), comma-separated.
            tags: Tag key/values the accounts must have.
            region: Default region for the profiles (config default if omitted).
            dry_run: Show what would change without writing.
        """
        o = ops()
        return o.generate_profiles(selection(o, accounts, team, tags), role, region, dry_run)

    @tool(idempotent=True)
    def sync_profiles(dry_run: bool = False) -> Dict[str, Any]:
        """Link existing <prefix>-* profiles in ~/.aws/config to their accounts."""
        return ops().sync_profiles(dry_run)

    @tool(idempotent=True)
    def sanitize_account_names(dry_run: bool = False) -> Dict[str, Any]:
        """Make stored account names safe to use in profile names."""
        return ops().sanitize_names(dry_run)

    @tool(destructive=True)
    def clean_duplicate_profiles(prefix_only: bool = False, dry_run: bool = True) -> Dict[str, Any]:
        """
        Find (and with dry_run=false remove) profiles in ~/.aws/config that point
        at the same account/role/SSO session. The prefixed one is kept; a backup
        is written before changes.
        """
        return ops().clean_duplicate_profiles(prefix_only, dry_run)

    # -- teams & tags ------------------------------------------------------------------

    @tool(read_only=True)
    def list_teams() -> Dict[str, int]:
        """Teams and how many accounts each has."""
        return ops().list_teams()

    @tool(idempotent=True)
    def assign_team(team: Optional[str], accounts: Optional[List[str]] = None,
                    tags: Optional[Dict[str, str]] = None, overwrite: bool = False) -> Dict[str, Any]:
        """
        Assign accounts to a team (a local label used to select accounts).

        Args:
            team: Team name; null removes the accounts' team.
            accounts: Account IDs or names.
            tags: Select accounts by tag instead of / in addition to IDs.
            overwrite: Replace an existing different team.
        """
        o = ops()
        return o.assign_team(selection(o, accounts, None, tags, True), team,
                             overwrite or team is None)

    @tool(idempotent=True)
    def set_tags(tags: Dict[str, str], accounts: Optional[List[str]] = None,
                 team: Optional[str] = None, overwrite: bool = False) -> Dict[str, Any]:
        """
        Set local tags on accounts (used to select accounts). Existing different
        values are kept unless overwrite is true.
        """
        o = ops()
        return o.set_tags(selection(o, accounts, team, None, True), tags, overwrite)

    @tool(destructive=True, idempotent=True)
    def remove_tags(keys: List[str], accounts: Optional[List[str]] = None,
                    team: Optional[str] = None) -> Dict[str, Any]:
        """Remove tag keys from accounts."""
        o = ops()
        return o.remove_tags(selection(o, accounts, team, None, True), keys)

    @tool(open_world=True, idempotent=True)
    def sync_tags(management_account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Import account tags from AWS Organizations (replaces local tags of
        accounts that have tags there).

        Args:
            management_account_id: Management or delegated-admin account whose
                profile has organizations:ListTagsForResource. Without it the
                default AWS credentials are used.
        """
        return ops().sync_tags(management_account_id)

    # -- templates -----------------------------------------------------------------------

    @tool(read_only=True)
    def list_templates() -> List[Dict[str, Any]]:
        """Saved command templates (reusable commands with default accounts/options)."""
        return ops().list_templates()

    @tool(idempotent=True)
    def save_template(name: str, command: str, description: str = "",
                      accounts: Optional[List[str]] = None, team: str = "",
                      tags: Optional[Dict[str, str]] = None, region: str = "",
                      timeout: int = 0, overwrite: bool = False) -> Dict[str, Any]:
        """
        Save a reusable command template (also usable as `multi-aws run @name`).

        Args:
            name: Template name (letters, digits, - _ .).
            command: AWS CLI command without 'aws'.
            description: What it's for.
            accounts / team / tags: Default account selection.
            region: Default region.
            timeout: Default per-account timeout in seconds (0 = default).
            overwrite: Replace an existing template.
        """
        return ops().save_template(name, command, description, accounts, team, tags,
                                   region, timeout=timeout, overwrite=overwrite)

    @tool(destructive=True)
    def delete_template(name: str) -> Dict[str, Any]:
        """Delete a saved command template."""
        return ops().delete_template(name)

    # -- running -------------------------------------------------------------------------

    def run_and_summarize(o: MultiAWS, kwargs: Dict[str, Any], max_output_chars: int,
                          save: bool) -> Dict[str, Any]:
        kwargs["timeout"] = max(1, min(int(kwargs.get("timeout") or 120), 900))
        summary = o.run(**kwargs)
        result = summarize_execution(summary, max(1000, max_output_chars))
        if save or result["truncated"]:
            output_dir = o.config.get("output", "path", "~/.multi-aws/outputs/")
            try:
                result["saved_to"] = str(summary.save(Path(output_dir).expanduser() / "mcp"))
            except OSError as e:
                result["save_error"] = str(e)
        if result["truncated"]:
            result["note"] = ("Some outputs were truncated (full results in 'saved_to'). "
                              "Use --query to narrow the output or raise max_output_chars.")
        return result

    @tool(destructive=True, open_world=True)
    def run_aws_command(command: str, accounts: Optional[List[str]] = None,
                        team: Optional[str] = None, tags: Optional[Dict[str, str]] = None,
                        regions: Optional[List[str]] = None, role: Optional[str] = None,
                        include_inactive: bool = False, timeout: int = 120,
                        max_output_chars: int = 40000, save: bool = False) -> Dict[str, Any]:
        """
        Run an AWS CLI command in one or more accounts (and regions) in parallel,
        using the user's SSO profiles, exactly like `multi-aws run`.
        Destructive commands are rejected unless the user allowed them in config.

        Args:
            command: AWS CLI command without 'aws', e.g.
                "ec2 describe-instances --query 'Reservations[].Instances[].InstanceId'".
                Don't pass --profile/--region/--output; they're set per account.
            accounts: Account IDs or exact names; ["all"] for every account.
            team: Team name(s), comma-separated.
            tags: Tag key/values the accounts must all have.
            regions: Regions to run in; ["all"] for every enabled region. Defaults
                to the configured region.
            role: SSO role whose profile to use (default: each account's profile).
            include_inactive: Include disabled accounts selected via team/tags/"all".
            timeout: Per account/region timeout in seconds (max 900).
            max_output_chars: Cap on total returned output; longer outputs are truncated.
            save: Also save the full results to the configured output folder.
        """
        return run_and_summarize(ops(), dict(
            command=command, accounts=accounts, team=team, tags=tags, regions=regions,
            role=role, include_inactive=include_inactive, timeout=timeout,
        ), max_output_chars, save)

    @tool(destructive=True, open_world=True)
    def run_template(name: str, accounts: Optional[List[str]] = None, team: Optional[str] = None,
                     tags: Optional[Dict[str, str]] = None, regions: Optional[List[str]] = None,
                     role: Optional[str] = None, max_output_chars: int = 40000,
                     save: bool = False) -> Dict[str, Any]:
        """
        Run a saved template. Any accounts/team/tags given replace the template's
        own account selection; regions/role override its defaults.
        """
        o = ops()
        kwargs = o.template_run_kwargs(name, accounts=accounts, team=team, tags=tags,
                                       regions=regions, role=role)
        kwargs.pop("output_format", None)
        return run_and_summarize(o, kwargs, max_output_chars, save)

    # -- cleanup ---------------------------------------------------------------------------

    @tool(destructive=True)
    def cleanup(confirm: bool, profiles: bool = False, tokens: bool = False,
                account_data: bool = False) -> Dict[str, Any]:
        """
        Remove multi-aws state. Only call after the user explicitly asked for it.

        Args:
            confirm: Must be true; confirms the user asked for this.
            profiles: Remove <prefix>-* SSO profiles from ~/.aws/config (backup kept).
            tokens: Delete cached SSO/CLI tokens (logs out all AWS CLI SSO sessions).
            account_data: Delete the local account data file (backup kept).
        """
        if not confirm:
            raise OperationError("Set confirm=true once the user has confirmed the cleanup")
        if not (profiles or tokens or account_data):
            raise OperationError("Choose at least one of profiles, tokens, account_data")
        return ops().cleanup(profiles, tokens, account_data)

    # -- prompts ------------------------------------------------------------------------------

    @server.prompt(name="getting_started", title="Set up multi-aws",
                   description="Guided walkthrough to set up multi-aws from scratch")
    def getting_started() -> str:
        return GETTING_STARTED

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
