"""
Interactive first-time setup (``multi-aws setup``).

Walks a new user through the same steps the MCP ``getting_started`` prompt
covers: AWS CLI -> config -> SSO session -> login -> account discovery ->
roles -> profiles -> verification, with optional Claude Desktop integration.
Steps that are already done are skipped, so it is safe to re-run.
"""

import shutil
from typing import List, Optional

import click

from ..aws import profile_config
from ..config.manager import ConfigManager
from ..services import MultiAWS, OperationError, summarize_execution

_READ_ONLY_HINTS = ("readonly", "read-only", "viewonly", "viewer", "audit")


def _step(number: int, title: str) -> None:
    click.echo()
    click.secho(f"Step {number}: {title}", bold=True)


def _ok(message: str) -> None:
    click.secho(f"  ✓ {message}", fg="green")


def _suggest_role(roles: List[str]) -> Optional[str]:
    for role in roles:
        if any(hint in role.lower().replace("_", "") for hint in _READ_ONLY_HINTS):
            return role
    return roles[0] if roles else None


def run_setup_wizard() -> None:
    click.secho("👋 multi-aws setup", bold=True)
    click.echo("This sets up AWS SSO access to all your accounts. Re-run it any time;")
    click.echo("finished steps are skipped. Press Ctrl+C to stop.")

    config = ConfigManager()
    if config.config_exists():
        config.load_config()
    ops = MultiAWS(config)

    try:
        _run(ops)
    except OperationError as e:
        click.secho(f"\n❌ {e}", fg="red", err=True)
        click.echo("Fix the problem above and run 'multi-aws setup' again.")
    except click.Abort:
        click.echo("\nSetup stopped. Run 'multi-aws setup' to continue later.")


def _run(ops: MultiAWS) -> None:
    # 1. AWS CLI
    _step(1, "AWS CLI")
    aws = shutil.which("aws")
    if not aws:
        click.echo("  The AWS CLI v2 is required. Install it from")
        click.echo("  https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html")
        click.echo("  then run 'multi-aws setup' again.")
        return
    _ok(aws)

    # 2. multi-aws config
    _step(2, "multi-aws settings")
    if ops.config.config_exists():
        _ok(f"Using {ops.config.paths.config_file}")
        change = click.confirm("  Review the profile prefix and default region?", default=False)
    else:
        change = True
    if change:
        prefix = click.prompt("  Profile name prefix", default=ops.prefix)
        region = click.prompt("  Default AWS region", default=ops.region)
        ops.update_config({"general.prefix": prefix, "general.region": region})
        _ok(f"Saved to {ops.config.paths.config_file}")

    # 3. SSO session
    _step(3, "AWS IAM Identity Center (SSO) session")
    sessions = ops.list_sso_sessions()["sessions"]
    if ops.sso_session in sessions:
        _ok(f"Using session '{ops.sso_session}' ({sessions[ops.sso_session]['start_url']})")
    else:
        choice = "new"
        if sessions:
            click.echo("  Sessions found in your AWS config:")
            for name, info in sessions.items():
                click.echo(f"    • {name}: {info['start_url']}")
            choice = click.prompt("  Session to use (or 'new' to add one)",
                                  type=click.Choice(list(sessions) + ["new"]), default=next(iter(sessions)))
        if choice == "new":
            click.echo("  You'll need your AWS access portal URL (https://<name>.awsapps.com/start)")
            click.echo("  and the region where IAM Identity Center is set up (ask your AWS admin).")
            name = click.prompt("  Session name", default="default" if "default" not in sessions else "multi-aws")
            start_url = click.prompt("  Access portal URL")
            sso_region = click.prompt("  Identity Center region", default=ops.region)
            result = ops.add_sso_session(name, start_url, sso_region)
            _ok(f"Added [sso-session {name}] to {result['aws_config_file']}")
        else:
            ops.update_config({"general.sso-session": choice})
            _ok(f"Using session '{choice}'")

    # 4. Login
    _step(4, "Log in")
    if ops.accounts.is_authenticated():
        _ok("Already logged in")
    else:
        click.echo("  Opening your browser; approve the request there.")
        result = ops.sso_login(interactive=True)
        if not result["authenticated"]:
            raise OperationError(f"Login failed: {result.get('error', 'unknown error')}")
        _ok("Logged in")

    # 5. Accounts
    _step(5, "Discover accounts")
    known = [a for a in ops.accounts.get_accounts() if a.is_active()]
    if not known or click.confirm(f"  {len(known)} accounts known. Refresh the list?", default=False):
        result = ops.discover_accounts()
        _ok(f"{result['active']} active accounts ({len(result['new_accounts'])} new, "
            f"{result['disabled']} no longer accessible)")
    else:
        _ok(f"{len(known)} accounts")
    active = [a for a in ops.accounts.get_accounts() if a.is_active()]
    if not active:
        raise OperationError("No accounts are accessible with this SSO session")

    # 6. Roles
    _step(6, "Fetch roles")
    missing = [a.id for a in active if not a.roles]
    if missing:
        click.echo(f"  Fetching roles for {len(missing)} account(s); this can take a minute...")
        result = ops.fetch_roles(missing)
        _ok(f"Roles fetched for {result['updated']} account(s)")
        if result["failed"]:
            click.secho(f"  ⚠️  {len(result['failed'])} account(s) failed; run 'multi-aws roles' later", fg="yellow")
    else:
        _ok("Roles known for all accounts")

    # 7. Profiles
    _step(7, "Create AWS CLI profiles")
    status = ops.setup_status()
    role_counts = status["common_roles"]
    roles = list(role_counts)
    if not roles:
        raise OperationError("No SSO roles found in your accounts")
    click.echo("  Most common roles:")
    for i, role in enumerate(roles, 1):
        click.echo(f"    {i}. {role} ({role_counts[role]} accounts)")
    default = _suggest_role(roles)
    role = click.prompt("  Role to create profiles for (name or number)", default=default)
    if role.isdigit() and 1 <= int(role) <= len(roles):
        role = roles[int(role) - 1]
    ids = [a.id for a in active]
    preview = ops.generate_profiles(ids, role, dry_run=True)
    n_create, n_update = len(preview["created"]), len(preview["updated"])
    if not (n_create or n_update):
        click.secho(f"  ⚠️  '{role}' isn't available in any account", fg="yellow")
    elif click.confirm(f"  Write {n_create} new and update {n_update} existing profile(s) in "
                       f"{profile_config.aws_config_path()}? (a backup is kept)", default=True):
        result = ops.generate_profiles(ids, role)
        _ok(f"{len(result['created']) + len(result['updated'])} profiles for '{role}'")
        if result["skipped"]:
            click.echo(f"  ({len(result['skipped'])} account(s) don't have '{role}' and were skipped)")

    # 8. Verify
    _step(8, "Verify")
    with_profile = [a for a in ops.accounts.get_accounts() if a.is_active() and a.profile_name]
    if with_profile:
        sample = with_profile[0]
        summary = summarize_execution(
            ops.run("sts get-caller-identity", accounts=[sample.id], timeout=60), 5000)
        item = summary["results"][0]
        if item["status"] == "SUCCESS":
            arn = item["output"].get("Arn") if isinstance(item["output"], dict) else item["output"]
            _ok(f"{sample.name}: {arn}")
        else:
            click.secho(f"  ⚠️  {sample.name}: {item.get('error', 'failed')}", fg="yellow")
    else:
        click.echo("  No profiles yet; skipped.")

    # 9. Claude integration
    _step(9, "Use from Claude (optional)")
    try:
        from ..mcp_server import claude_desktop_config_path, install_claude_desktop
        desktop_config = claude_desktop_config_path()
        if desktop_config.parent.exists() and click.confirm(
                "  Add multi-aws to Claude Desktop so you can ask Claude about your accounts?", default=True):
            install_claude_desktop()
            _ok("Added; restart Claude Desktop to load it")
        click.echo("  For Claude Code: claude mcp add multi-aws -- multi-aws-mcp")
    except ImportError:
        click.echo("  Install the 'mcp' package to use multi-aws from Claude.")

    click.echo()
    click.secho("🎉 All set!", bold=True)
    click.echo("Try:")
    click.echo("  multi-aws run 'sts get-caller-identity' --accounts all")
    click.echo("  multi-aws assign-team --accounts <ids> --team <name>   # group accounts")
    click.echo("  multi-aws sync-tags                                     # import Organizations tags")
    click.echo("  multi-aws template add <name> --command '<aws command>' # save a command")
