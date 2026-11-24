"""
CLI command definitions for MultiAWSTool
"""

import click
import logging
import sys
from pathlib import Path
import os
import shutil

# Import dependencies at module level
from ..config.manager import load_or_create_config, ConfigurationError
from ..aws.account_manager import AccountManager, AccountManagerError
from ..utils.validators import parse_account_list, sanitize_profile_name_component
from ..utils.logging_config import setup_logging_from_config
from ..models.config import MultiAWSConfig
from .. import __version__
from ..execution import execute, ExecutionError

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def _terminal_columns(default: int = 120) -> int:
    """Terminal width, or a default when stdout isn't a terminal (pipes, CI, cron)."""
    try:
        return os.get_terminal_size()[0]
    except (OSError, ValueError):
        return shutil.get_terminal_size((default, 24)).columns


class AppContext:
    """Application context to hold shared objects"""
    def __init__(self):
        self.config_manager = None
        self.account_manager = None
        self.verbose = False
        self.max_content_width = 120
        self.terminal_width = 120

    def initialize(self, verbose=False):
        """Initialize the application context"""
        self.verbose = verbose
        columns = _terminal_columns()
        self.max_content_width = columns
        self.terminal_width = columns
        try:
            # Load configuration
            self.config_manager = load_or_create_config()


            
            # Setup logging from configuration
            try:
                config = MultiAWSConfig.from_config_manager(self.config_manager)
                
                # Override log level to DEBUG if verbose mode is enabled
                if verbose:
                    config.logging.level = 'DEBUG'
                
                setup_logging_from_config(config)
                logger.info("Logging configured from config file")
            except Exception as e:
                # Fallback to basic logging if config-based setup fails
                logger.warning(f"Failed to setup logging from config, using defaults: {e}")
                from ..utils.logging_config import setup_logging
                setup_logging(logging.DEBUG if verbose else logging.INFO)
            
            # Get config values
            sso_session = self.config_manager.get('general', 'sso-session', 'default')
            region = self.config_manager.get('general', 'region', 'us-east-1')
            account_file = self.config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json')
            prefix = self.config_manager.get('general', 'prefix', 'multi-aws')
            
            # Initialize account manager
            self.account_manager = AccountManager(sso_session, region, account_file, profile_prefix=prefix)
            
            if verbose:
                logger.debug(f"Initialized with SSO session: {sso_session}, region: {region}")
                
        except Exception as e:
            logger.error(f"Failed to initialize application context: {e}")
            raise

    def ensure_authenticated(self):
        """Ensure the account manager is authenticated"""
        if not self.account_manager:
            raise AccountManagerError("Account manager not initialized")
            
        if not self.account_manager.is_authenticated():
            click.echo("🔐 Authenticating with AWS SSO...")
            if not self.account_manager.authenticate():
                raise AccountManagerError("SSO authentication failed")
        return True


def get_account_manager(ctx):
    """Get or initialize the account manager from context"""
    if not ctx.obj.account_manager:
        try:
            ctx.obj.initialize(verbose=ctx.obj.verbose)
        except Exception as e:
            raise click.ClickException(f"Failed to initialize account manager: {e}")
    return ctx.obj.account_manager


def get_account_name(ctx, account_id):
    """
    Get account name from account ID using the shared account manager.
    
    Args:
        ctx: Click context containing the account manager
        account_id: AWS account ID to look up
        
    Returns:
        str: Account name if found, otherwise returns the account ID
    """
    try:
        account_manager = get_account_manager(ctx)
        account = account_manager.get_account(account_id)
        if account and account.name:
            return account.name
        return account_id  # Return ID if name not found
    except Exception:
        return account_id  # Return ID if any error occurs


@click.group(invoke_without_command=True)
@click.version_option(version=__version__)
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.pass_context
def cli(ctx: click.Context, verbose):
    """MultiAWSTool - Multi-AWS Account Management Tool"""
    # Initialize application context
    ctx.ensure_object(AppContext)
    ctx.obj.verbose = verbose
    columns = _terminal_columns()
    ctx.max_content_width = columns
    ctx.terminal_width = columns
    ctx.obj.max_content_width = columns
    ctx.obj.terminal_width = columns
    ctx.color = True
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        ctx.exit()
    try:
        ctx.obj.initialize(verbose=verbose)
    except Exception as e:
        # For some commands (like configure), we might not have a config yet
        # So we'll defer initialization to individual commands that need it
        logger.debug(f"Deferred context initialization: {e}")
        
        # Set up basic logging for commands that don't have config yet
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
            logger.debug("Verbose mode enabled - using basic logging")

@cli.command()
def configure():
    """Configure the MultiAWSTool settings"""
    click.echo("🔧 MultiAWSTool Configuration Setup")
    click.echo("=" * 40)
    
    # Import dependencies
    try:
        from ..config.manager import ConfigManager
        from ..config.manager import ConfigurationError
        from ..models.config import MultiAWSConfig
    except ImportError as e:
        click.echo(f"❌ Import error: {e}", err=True)
        return
    
    try:
        
        config_manager = ConfigManager()
        
        # Check if config already exists
        if config_manager.config_exists():
            if not click.confirm("Configuration file already exists. Do you want to reconfigure?"):
                click.echo("Configuration cancelled.")
                return
            
            # Load existing config
            config_manager.load_config()
            existing_config = MultiAWSConfig.from_config_manager(config_manager)
        else:
            existing_config = MultiAWSConfig.default()
        
        click.echo("\nPlease provide the following configuration values:")
        click.echo("(Press Enter to use default/current values shown in brackets)")
        
        # General settings
        click.echo("\n📋 General Settings:")
        prefix = click.prompt(
            "AWS Profile prefix", 
            default=existing_config.general.prefix,
            show_default=True
        )
        
        sso_session = click.prompt(
            "SSO Session name", 
            default=existing_config.general.sso_session,
            show_default=True
        )
        
        account_file = click.prompt(
            "Account file path", 
            default=existing_config.general.account_file,
            show_default=True
        )
        
        region = click.prompt(
            "Default AWS region", 
            default=existing_config.general.region,
            show_default=True
        )
        
        # Output settings
        click.echo("\n📁 Output Settings:")
        click.echo("Pattern placeholders: !a=account_id, !A=account_name, !c=command, !d=date, !t=time, !s=timestamp")
        pattern = click.prompt(
            "Output filename pattern", 
            default=existing_config.output.pattern,
            show_default=True
        )
        
        format_choice = click.prompt(
            "Output format", 
            type=click.Choice(['json', 'yaml', 'txt', 'csv'], case_sensitive=False),
            default=existing_config.output.format,
            show_default=True
        )
        
        output_path = click.prompt(
            "Output directory", 
            default=existing_config.output.path,
            show_default=True
        )
        
        # Execution settings
        click.echo("\n⚡ Execution Settings:")
        execution_mode = click.prompt(
            "Execution mode", 
            type=click.Choice(['parallel', 'sequential'], case_sensitive=False),
            default=existing_config.execution.mode,
            show_default=True
        )
        
        stop_on_errors = click.prompt(
            "Stop after how many errors (0 = never stop)", 
            type=int,
            default=existing_config.execution.stop_on_errors,
            show_default=True
        )
        
        # Security settings
        click.echo("\n🔒 Security Settings:")
        allow_destructive = click.confirm(
            "Allow destructive commands (create, delete, modify operations)",
            default=existing_config.security.allow_destructive_commands
        )
        
        # Logging settings
        click.echo("\n📋 Logging Settings:")
        log_level = click.prompt(
            "Log level",
            type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], case_sensitive=False),
            default=existing_config.logging.level,
            show_default=True
        )
        
        log_file = click.prompt(
            "Log file path (empty to disable file logging)",
            default=existing_config.logging.file,
            show_default=True
        )
        
        console_logging = click.confirm(
            "Enable console logging",
            default=existing_config.logging.console
        )
        
        max_size = click.prompt(
            "Maximum log file size (MB)",
            type=int,
            default=existing_config.logging.max_size,
            show_default=True
        )
        
        backup_count = click.prompt(
            "Number of backup log files to keep",
            type=int,
            default=existing_config.logging.backup_count,
            show_default=True
        )
        
        # Create new configuration
        new_config = MultiAWSConfig(
            general=existing_config.general.__class__(
                prefix=prefix,
                sso_session=sso_session,
                account_file=account_file,
                region=region
            ),
            output=existing_config.output.__class__(
                pattern=pattern,
                format=format_choice,
                path=output_path
            ),
            execution=existing_config.execution.__class__(
                mode=execution_mode,
                stop_on_errors=stop_on_errors
            ),
            security=existing_config.security.__class__(
                allow_destructive_commands=allow_destructive
            ),
            logging=existing_config.logging.__class__(
                level=log_level.upper(),
                file=log_file if log_file.strip() else "",
                console=console_logging,
                max_size=max_size,
                backup_count=backup_count
            )
        )
        
        # Validate configuration
        validation_errors = new_config.validate()
        if validation_errors:
            click.echo("\n❌ Configuration validation errors:")
            for error in validation_errors:
                click.echo(f"  • {error}")
            return
        
        # Save configuration
        new_config.to_config_manager(config_manager)
        config_manager.save_config()
        
        click.echo("\n✅ Configuration saved successfully!")
        click.echo(f"📁 Config file: {config_manager.paths.config_file}")
        click.echo(f"📂 Config directory: {config_manager.paths.config_dir}")
        
        # Show next steps
        click.echo("\n🚀 Next steps:")
        click.echo("  1. Run 'multi-aws init' to initialize SSO and discover accounts")
        click.echo("  2. Run 'multi-aws roles --accounts <account-ids>' to fetch available roles")
        click.echo("  3. Run 'multi-aws profiles --accounts <account-ids> --role <role-name>' to generate profiles")
        click.echo("  OR run 'multi-aws sync' to sync existing profiles from ~/.aws/config")
        
    except ConfigurationError as e:
        click.echo(f"❌ Configuration error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during configuration")

def _ops(ctx, account_manager=None):
    """Shared operations object (see multi_aws_tool.services) for this CLI invocation."""
    from ..services import MultiAWS
    config_manager = ctx.obj.config_manager or load_or_create_config()
    return MultiAWS(config_manager, account_manager or get_account_manager(ctx))


def _ops_errors():
    from ..services import OperationError
    from ..utils.account_data import AccountDataError
    return (OperationError, AccountManagerError, AccountDataError, ConfigurationError)


@cli.command()
@click.option('--sso-session', default=None,
              help='SSO session name to use (default: general.sso-session from config)')
@click.pass_context
def init(ctx, sso_session):
    """Initialize SSO and discover AWS accounts"""
    from ..aws import profile_config

    try:
        config_manager = ctx.obj.config_manager or load_or_create_config()
        sso_session = sso_session or config_manager.get('general', 'sso-session', 'default')
        click.echo(f"🚀 Initializing with SSO session: {sso_session}")

        if sso_session not in profile_config.list_sso_sessions(profile_config.read_config()):
            click.echo(f"❌ SSO session '{sso_session}' not found in {profile_config.aws_config_path()}")
            click.echo("Run 'multi-aws setup' for a guided setup, or add it yourself, e.g.:")
            click.echo(f"""
[sso-session {sso_session}]
sso_start_url = https://your-sso-portal.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access
""")
            return

        account_manager = AccountManager(
            sso_session,
            config_manager.get('general', 'region', 'us-east-1'),
            config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json'),
            profile_prefix=config_manager.get('general', 'prefix', 'multi-aws'),
        )
        ctx.obj.account_manager = account_manager

        click.echo("🔐 Authenticating with AWS SSO...")
        if not account_manager.authenticate():
            click.echo("❌ SSO authentication failed")
            return

        click.echo("🔍 Discovering AWS accounts...")
        result = _ops(ctx, account_manager).discover_accounts()

        for change in result['sanitized_names']:
            click.echo(f"   Sanitized: '{change['from']}' -> '{change['to']}' (ID: {change['id']})")

        click.echo(f"\n✅ Account discovery complete!")
        click.echo(f"📊 Found {result['active']} active accounts, {result['disabled']} disabled")
        if result['new_accounts']:
            click.echo(f"\n🆕 New accounts:")
            for account in result['new_accounts']:
                click.echo(f"  • {account['id']} - {account['name']}")

        click.echo(f"\n💾 Account data saved to: {result['account_file']}")
        click.echo(f"\n🚀 Next steps:")
        click.echo(f"  1. Run 'multi-aws roles --accounts all' to fetch available roles")
        click.echo(f"  2. Run 'multi-aws profiles --accounts all --role <role-name> --append-to-config' to generate profiles")

    except _ops_errors() as e:
        click.echo(f"❌ Account discovery error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during initialization")


@cli.command()
@click.option('--accounts', required=True, help="Comma-separated account IDs/names, a file path, or 'all'")
@click.pass_context
def roles(ctx, accounts):
    """Fetch available roles for specified accounts"""
    click.echo(f"🔍 Fetching roles for accounts: {accounts}")

    try:
        ops = _ops(ctx)
        account_ids = ops.select_accounts(accounts)
        click.echo(f"📋 Processing {len(account_ids)} account(s)")
        ctx.obj.ensure_authenticated()

        result = ops.fetch_roles(account_ids)

        click.echo(f"\n✅ Fetched roles for {result['updated']} account(s)")
        for role_name, count in result['roles'].items():
            click.echo(f"  • {role_name} ({count} account(s))")
        if result['failed']:
            click.echo(f"\n❌ Failed to fetch roles for {len(result['failed'])} account(s):")
            for account_id, error in result['failed'].items():
                click.echo(f"  • {account_id}: {error}")
        for account_id in result['not_found']:
            click.echo(f"⚠️  Account {account_id} not found. Run 'init' first.")

        click.echo(f"\n🚀 Next step:")
        click.echo(f"  Run 'multi-aws profiles --accounts <account-ids> --role <role-name> --append-to-config' to generate profiles")

    except _ops_errors() as e:
        click.echo(f"❌ Role discovery error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during role discovery")


@cli.command()
@click.option('--accounts', required=True, help="Comma-separated account IDs/names, a file path, or 'all'")
@click.option('--role', required=True, help='Role name to use for all accounts')
@click.option('--region', help='AWS region override')
@click.option('--format', type=click.Choice(['aws-cli', 'env-vars']), default='aws-cli', help='Output format')
@click.option('--output-file', help='File to write profiles to')
@click.option('--append-to-config', is_flag=True,
              help='Write profiles to ~/.aws/config (existing ones are updated in place; a backup is kept)')
@click.pass_context
def profiles(ctx, accounts, role, region, format, output_file, append_to_config):
    """Generate AWS CLI profiles for specified accounts and role"""
    from ..aws import profile_config

    click.echo(f"🔧 Generating {format} profiles for role '{role}'")
    write = append_to_config and format == 'aws-cli'

    try:
        ops = _ops(ctx)
        account_ids = ops.select_accounts(accounts)
        click.echo(f"📋 Processing {len(account_ids)} account(s)")

        result = ops.generate_profiles(account_ids, role, region, dry_run=not write)

        for skip in result['skipped']:
            label = f"{skip.get('name', '')} ({skip['id']})" if skip.get('name') else skip['id']
            click.echo(f"⚠️  Skipping {label}: {skip['reason']}")

        generated = result['profiles']
        if not generated:
            click.echo("❌ No valid accounts with the specified role found", err=True)
            return

        if write:
            for name in result['created']:
                click.echo(f"➕ Created: {name}")
            for name in result['updated']:
                click.echo(f"🔄 Updated: {name}")
            click.echo(f"✅ Wrote {len(generated)} profile(s) for role '{role}' to {result['aws_config_file']}")
            if result.get('backup'):
                click.echo(f"📋 Backup: {result['backup']}")
            click.echo(f"\n📖 Use with: aws --profile {generated[0]['profile']} sts get-caller-identity")
            click.echo("   or: multi-aws run 'sts get-caller-identity' --accounts <account-ids>")
            return

        if format == 'aws-cli':
            lines = []
            for p in generated:
                lines += profile_config.section_lines(f"profile {p['profile']}", p['settings']) + [""]
        else:
            lines = []
            for p in generated:
                clean_name = p['account_name'].replace('-', '_').replace(' ', '_').upper()
                lines += [f"# {p['account_name']} ({p['account_id']})",
                          f"export AWS_PROFILE_{clean_name}='{p['profile']}'", ""]
        content = '\n'.join(lines)

        if output_file:
            output_path = Path(output_file).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
            click.echo(f"✅ Generated {len(generated)} profile(s) for role '{role}'")
            click.echo(f"💾 Profiles written to: {output_path}")
        else:
            click.echo(f"✅ Generated {len(generated)} profile(s) for role '{role}':")
            click.echo("\n" + content)

        if format == 'aws-cli':
            click.echo("\n📖 Add these to ~/.aws/config (or rerun with --append-to-config),")
            click.echo("   then run 'multi-aws sync' so multi-aws picks them up.")
        else:
            click.echo("\n📖 Source the file, then use: aws --profile $AWS_PROFILE_<ACCOUNT> <command>")

    except _ops_errors() as e:
        click.echo(f"❌ Profile generation error: {e}", err=True)
    except OSError as e:
        click.echo(f"❌ File operation error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during profile generation")


@cli.command()
@click.option('--dry-run', is_flag=True, help='Show what would be synced without making changes')
@click.pass_context
def sync(ctx, dry_run):
    """Sync profile names from ~/.aws/config to account data"""
    click.echo("🔄 Syncing profiles from AWS config to account data")

    try:
        ops = _ops(ctx)
        click.echo(f"📋 Looking for profiles with prefix: {ops.prefix}")
        result = ops.sync_profiles(dry_run=dry_run)

        verb = "Would update" if dry_run else "Updated"
        for change in result['changes']:
            click.echo(f"{'🔄' if dry_run else '✅'} {verb} {change['name']} ({change['id']}): "
                       f"'{change['from']}' -> '{change['to']}'")
        for unknown in result['unknown_accounts']:
            click.echo(f"⚠️  Account {unknown['id']} not found in account data (profile: {unknown['profile']})")

        click.echo(f"\n📋 Sync Summary:")
        click.echo(f"  🔍 Profiles found: {result['profiles_found']}")
        click.echo(f"  ✅ {'Updates needed' if dry_run else 'Updates made'}: {len(result['changes'])}")
        if dry_run and result['changes']:
            click.echo("   Run without --dry-run to apply changes")

    except _ops_errors() as e:
        click.echo(f"❌ Sync error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during profile sync")


@cli.command()
@click.option('--dry-run', is_flag=True, help='Show what would be sanitized without making changes')
@click.pass_context
def sanitize_names(ctx, dry_run):
    """Sanitize account names in stored account data for profile compatibility"""
    click.echo("🧹 Sanitizing account names for profile compatibility")

    try:
        result = _ops(ctx).sanitize_names(dry_run=dry_run)
        verb = "Would sanitize" if dry_run else "Sanitized"
        for change in result['changes']:
            click.echo(f"{'🔄' if dry_run else '✅'} {verb}: '{change['from']}' -> '{change['to']}' (ID: {change['id']})")

        click.echo(f"\n📋 Sanitization Summary:")
        click.echo(f"  📊 Accounts checked: {result['checked']}")
        click.echo(f"  ✅ Names {'to sanitize' if dry_run else 'sanitized'}: {len(result['changes'])}")
        if dry_run and result['changes']:
            click.echo("   Run without --dry-run to apply changes")

    except _ops_errors() as e:
        click.echo(f"❌ Sanitization error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during name sanitization")


@cli.command()
@click.option('--dry-run', is_flag=True, help='Show what would be cleaned without making changes')
@click.option('--prefix-only', is_flag=True, help='Only check profiles with the configured prefix')
@click.option('--yes', is_flag=True, help='Remove duplicates without asking')
@click.pass_context
def clean_duplicates(ctx, dry_run, prefix_only, yes):
    """Check for and clean up duplicate profiles in ~/.aws/config"""
    click.echo("🔍 Checking for duplicate profiles in AWS config")

    try:
        ops = _ops(ctx)
        click.echo(f"📋 Checking {'only profiles with prefix: ' + ops.prefix if prefix_only else 'all profiles'}")
        found = ops.clean_duplicate_profiles(prefix_only=prefix_only, dry_run=True)

        if not found['duplicates']:
            click.echo("✅ No duplicate profiles found")
            return

        to_remove = sum(len(d['remove']) for d in found['duplicates'])
        for dup in found['duplicates']:
            click.echo(f"\n🔍 Found duplicates for {dup['account_id']} + {dup['role']}:")
            click.echo(f"   ✅ Keeping: {dup['keep']}")
            for name in dup['remove']:
                click.echo(f"   ❌ Duplicate: {name}")

        click.echo(f"\n📋 Profiles to remove: {to_remove}")
        if dry_run:
            click.echo("\n📝 Dry run: No changes made")
            click.echo("   Run without --dry-run to remove duplicates")
            return
        if not yes and not click.confirm(f"\nAre you sure you want to remove {to_remove} duplicate profile(s)?"):
            click.echo("Operation cancelled")
            return

        result = ops.clean_duplicate_profiles(prefix_only=prefix_only, dry_run=False)
        click.echo(f"📋 Created backup: {result['backup']}")
        click.echo(f"\n✅ Successfully removed {result['removed']} duplicate profile(s)")
        click.echo(f"\n🚀 Next step: run 'multi-aws sync' to update account data with current profiles")

    except _ops_errors() as e:
        click.echo(f"❌ Duplicate cleanup error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Duplicate cleanup error: {e}", err=True)
        logger.exception("Unexpected error during duplicate cleanup")


@cli.command()
@click.pass_context
def setup(ctx):
    """Guided first-time setup: SSO session, login, accounts, roles and profiles"""
    from .setup_wizard import run_setup_wizard
    run_setup_wizard()

@cli.group()
def template():
    """Manage command templates / presets"""


@template.command('add')
@click.argument('name')
@click.option('--command', required=True, help='AWS CLI command to save (e.g. "sts get-caller-identity")')
@click.option('--description', default='', help='Human-readable description of the template')
@click.option('--region', default='', help='AWS region override for this template')
@click.option('--output-format', default='', type=click.Choice(['', 'json', 'yaml', 'txt', 'csv']),
              help='Output format override for this template')
@click.option('--parallel/--sequential', default=None,
              help='Execution mode override (default: use global config)')
@click.option('--timeout', type=int, default=0, help='Timeout override in seconds (0 = use default)')
@click.option('--accounts', default='', help='Default account IDs (comma-separated) or file path for this template')
@click.option('--team', default='', help='Default team name(s) to select accounts from for this template')
@click.option('--tag', 'tags', multiple=True, metavar='KEY=VALUE',
              help='Default tag filter(s) for this template (format: key=value). Can be specified multiple times.')
@click.option('--save/--no-save', default=None,
              help='Save command outputs to files by default when using this template')
@click.option('--overwrite', is_flag=True, help='Overwrite an existing template with the same name')
@click.pass_context
def template_add(ctx, name, command, description, region, output_format, parallel, timeout,
                 accounts, team, tags, save, overwrite):
    """Add or update a named command template"""
    from ..config.template_manager import get_template_manager, TemplateError
    from ..models.template import CommandTemplate
    from ..config.schema import is_destructive_command

    try:
        config_manager = ctx.obj.config_manager or load_or_create_config()
        allow_destructive = config_manager.get_bool('security', 'allow-destructive-commands', False)

        if is_destructive_command(command) and not allow_destructive:
            click.echo(
                f"❌ Command '{command}' is considered destructive. "
                "Set allow-destructive-commands = true in config to save such templates.",
                err=True,
            )
            return

        tmgr = get_template_manager(config_manager)

        if tmgr.template_exists(name) and not overwrite:
            click.echo(
                f"❌ Template '{name}' already exists. Use --overwrite to replace it.", err=True
            )
            return

        tmpl = CommandTemplate(
            name=name,
            command=command,
            description=description,
            region=region,
            output_format=output_format,
            parallel=parallel,
            timeout=timeout,
            accounts=accounts,
            team=team,
            tags=list(tags),
            save=save,
        )
        tmgr.add_template(tmpl)
        tmgr.save_templates()

        click.echo(f"✅ Template '{name}' saved.")
        click.echo(f"   Command  : {command}")
        if description:
            click.echo(f"   Desc     : {description}")
        if region:
            click.echo(f"   Region   : {region}")
        if output_format:
            click.echo(f"   Format   : {output_format}")
        if parallel is not None:
            click.echo(f"   Parallel : {parallel}")
        if timeout:
            click.echo(f"   Timeout  : {timeout}s")
        if accounts:
            click.echo(f"   Accounts : {accounts}")
        if team:
            click.echo(f"   Team     : {team}")
        if tags:
            click.echo(f"   Tags     : {', '.join(tags)}")
        if save is not None:
            click.echo(f"   Save     : {save}")
        click.echo(f"\n💡 Run it with: multi-aws run @{name}")

    except TemplateError as exc:
        click.echo(f"❌ Template error: {exc}", err=True)
    except Exception as exc:
        click.echo(f"❌ Unexpected error: {exc}", err=True)
        logger.exception("Unexpected error while adding template")


@template.command('list')
@click.pass_context
def template_list(ctx):
    """List all saved command templates"""
    from ..config.template_manager import get_template_manager, TemplateError

    try:
        config_manager = ctx.obj.config_manager or load_or_create_config()
        tmgr = get_template_manager(config_manager)
        templates = tmgr.list_templates()

        if not templates:
            click.echo("ℹ️  No templates defined yet.")
            click.echo("  Use 'multi-aws template add <name> --command \"<cmd>\"' to create one.")
            return

        click.echo(f"📋 {len(templates)} template(s):\n")
        for tmpl in templates:
            click.echo(f"  @{tmpl.name}")
            click.echo(f"    Command : {tmpl.command}")
            if tmpl.description:
                click.echo(f"    Desc    : {tmpl.description}")
            extras = []
            if tmpl.region:
                extras.append(f"region={tmpl.region}")
            if tmpl.output_format:
                extras.append(f"format={tmpl.output_format}")
            if tmpl.parallel is not None:
                extras.append(f"parallel={tmpl.parallel}")
            if tmpl.timeout:
                extras.append(f"timeout={tmpl.timeout}s")
            if tmpl.accounts:
                extras.append(f"accounts={tmpl.accounts}")
            if tmpl.team:
                extras.append(f"team={tmpl.team}")
            if tmpl.tags:
                extras.append(f"tags={','.join(tmpl.tags)}")
            if tmpl.save is not None:
                extras.append(f"save={tmpl.save}")
            if extras:
                click.echo(f"    Options : {', '.join(extras)}")
            click.echo()

    except TemplateError as exc:
        click.echo(f"❌ Template error: {exc}", err=True)
    except Exception as exc:
        click.echo(f"❌ Unexpected error: {exc}", err=True)
        logger.exception("Unexpected error while listing templates")


@template.command('show')
@click.argument('name')
@click.pass_context
def template_show(ctx, name):
    """Show details of a single template"""
    from ..config.template_manager import get_template_manager, TemplateError

    try:
        config_manager = ctx.obj.config_manager or load_or_create_config()
        tmgr = get_template_manager(config_manager)
        tmpl = tmgr.get_template(name)

        if not tmpl:
            click.echo(f"❌ Template '{name}' not found.", err=True)
            return

        click.echo(f"📄 Template: @{tmpl.name}")
        click.echo(f"  Command     : {tmpl.command}")
        click.echo(f"  Description : {tmpl.description or '(none)'}")
        click.echo(f"  Region      : {tmpl.region or '(use default)'}")
        click.echo(f"  Format      : {tmpl.output_format or '(use default)'}")
        parallel_str = "(use default)" if tmpl.parallel is None else str(tmpl.parallel)
        click.echo(f"  Parallel    : {parallel_str}")
        click.echo(f"  Timeout     : {tmpl.timeout or '(use default)'}")
        click.echo(f"  Accounts    : {tmpl.accounts or '(none)'}")
        click.echo(f"  Team        : {tmpl.team or '(none)'}")
        click.echo(f"  Tags        : {', '.join(tmpl.tags) if tmpl.tags else '(none)'}")
        save_str = "(use CLI flag)" if tmpl.save is None else str(tmpl.save)
        click.echo(f"  Save        : {save_str}")
        click.echo(f"  Created     : {tmpl.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        click.echo(f"  Updated     : {tmpl.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")

    except TemplateError as exc:
        click.echo(f"❌ Template error: {exc}", err=True)
    except Exception as exc:
        click.echo(f"❌ Unexpected error: {exc}", err=True)
        logger.exception("Unexpected error while showing template")


@template.command('delete')
@click.argument('name')
@click.option('--confirm', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def template_delete(ctx, name, confirm):
    """Delete a saved template"""
    from ..config.template_manager import get_template_manager, TemplateError

    try:
        config_manager = ctx.obj.config_manager or load_or_create_config()
        tmgr = get_template_manager(config_manager)

        if not tmgr.template_exists(name):
            click.echo(f"❌ Template '{name}' not found.", err=True)
            return

        if not confirm:
            if not click.confirm(f"Delete template '{name}'?"):
                click.echo("Deletion cancelled.")
                return

        tmgr.delete_template(name)
        tmgr.save_templates()
        click.echo(f"✅ Template '{name}' deleted.")

    except TemplateError as exc:
        click.echo(f"❌ Template error: {exc}", err=True)
    except Exception as exc:
        click.echo(f"❌ Unexpected error: {exc}", err=True)
        logger.exception("Unexpected error while deleting template")


def _command_name_parts(args):
    """Service and operation (first two non-option arguments) of an AWS CLI command."""
    parts = []
    skip_next = False
    for part in args:
        if skip_next:
            skip_next = False
            continue
        if part.startswith('--'):
            # Global options that take a value
            if part in ['--profile', '--region', '--output', '--endpoint-url']:
                skip_next = True
            continue
        parts.append(part)
        if len(parts) >= 2:
            break
    return parts


def _write_result_file(result, account, output_path, output_pattern, output_format):
    """Write one result to a file named from the configured output pattern.

    Pattern placeholders: !a=account id, !A=account name, !c=command, !S=service,
    !C=operation, !d=date, !t=time, !s=timestamp, !r=role, !p=team, !R=region.

    Returns:
        Path of the written file
    """
    import json
    import shlex
    from datetime import datetime

    started = datetime.fromisoformat(result.timestamp)
    # Profile format: prefix-account-role
    profile_parts = (result.profile_name or '').split('-')
    role_name = profile_parts[-1] if len(profile_parts) > 2 else 'unknown'

    name_parts = _command_name_parts(shlex.split(result.command))
    command_name = ('-'.join(name_parts) if name_parts else 'unknown-command').replace('/', '_')

    def clean(value):
        return value.replace(' ', '_').replace('/', '_')

    replacements = [
        ('!a', account.id),
        ('!A', clean(account.name)),
        ('!c', command_name),
        ('!d', started.strftime('%Y%m%d')),
        ('!t', started.strftime('%H%M%S')),
        ('!s', started.strftime('%Y%m%d_%H%M%S')),
        ('!r', role_name),
        ('!S', name_parts[0] if name_parts else 'unknown-service'),
        ('!C', name_parts[1] if len(name_parts) > 1 else 'unknown-operation'),
        ('!p', clean(account.product_team) if account.product_team else 'unknown-team'),
        ('!R', result.region or 'unknown-region'),
    ]
    filename_base = output_pattern
    for placeholder, value in replacements:
        filename_base = filename_base.replace(placeholder, value)
    filename = f"{filename_base}.{output_format}"

    # Flag output that doesn't match the requested format
    stdout = result.output or ''
    try:
        if output_format == 'json':
            json.loads(stdout)
        elif output_format in ('yaml', 'yml'):
            import yaml
            yaml.safe_load(stdout)
    except Exception as e:
        click.echo(f"⚠️  Warning: Output is not valid {output_format.upper()} for account {account.name}: {e}")
        filename = f"{filename_base}-corrupted.{output_format}"

    # The pattern may contain slashes to create subdirectories
    file_path = os.path.join(output_path, filename)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        if result.status == 'SUCCESS':
            f.write(stdout)
        else:
            f.write(f"ERROR: {result.error}\nSTDOUT: {stdout}")
    return file_path


def _legacy_summary_records(summary, accounts_by_id):
    """Summary records in the list format written by earlier versions (read by mat-parse)."""
    records = []
    for r in summary.results:
        account = accounts_by_id.get(r.account_id)
        record = r.to_dict()
        record['status'] = r.status.lower()
        record['team'] = account.product_team if account and account.product_team else "N/A"
        records.append(record)
    return records


@cli.command()
@click.option('--accounts', help='Comma-separated account IDs or file path')
@click.option('--team', help='Team name(s) to select accounts from')
@click.option('--tag', 'tags', multiple=True, metavar='KEY=VALUE',
              help='Filter accounts by tag (format: key=value). Can be specified multiple times.')
@click.option('--output-dir', help='Directory to save output files')
@click.option('--verbose', is_flag=True, help='Enable verbose output')
@click.option('--save' , is_flag=True, help='Save command outputs to files')
@click.option('--region', help='AWS region override')
@click.option('--all-regions', is_flag=True, help='Run command on all available AWS regions')
@click.option('--parallel', is_flag=True, help='Execute commands in parallel')
@click.option('--timeout', type=int, default=300, help='Command timeout in seconds')
@click.option('--dry-run', is_flag=True, help='Show what would be executed without running commands')
@click.argument('command', nargs=-1)
@click.pass_context
def run(ctx: click.Context, command: tuple, accounts, team, tags, output_dir, region, all_regions, parallel, timeout, dry_run, save, verbose):
    """Execute AWS CLI command across multiple accounts using their configured profiles.

    The COMMAND argument may reference a saved template by prefixing its name with @,
    for example: multi-aws run @my-template --accounts 123456789012
    """
    import subprocess
    import json
    import shlex
    from datetime import datetime

    try:
        config_manager = ctx.obj.config_manager or load_or_create_config()

        # ------------------------------------------------------------------
        # Template resolution: if the sole argument starts with '@' treat it
        # as a reference to a saved template and apply its settings.
        # ------------------------------------------------------------------
        if command and len(command) == 1 and command[0].startswith('@'):
            template_name = command[0][1:]
            from ..config.template_manager import get_template_manager, TemplateError
            try:
                tmgr = get_template_manager(config_manager)
                tmpl = tmgr.get_template(template_name)
            except TemplateError as exc:
                click.echo(f"❌ Failed to load templates: {exc}", err=True)
                return

            if tmpl is None:
                click.echo(f"❌ Template '@{template_name}' not found.", err=True)
                click.echo("  Run 'multi-aws template list' to see available templates.")
                return

            click.echo(f"📄 Using template: @{tmpl.name}")
            if tmpl.description:
                click.echo(f"   ({tmpl.description})")

            # Expand the template command into a tuple of tokens (shell rules, so quoted args survive)
            command = tuple(shlex.split(tmpl.command))

            # Apply template overrides only when the user hasn't supplied them
            if tmpl.region and not region:
                region = tmpl.region
            if tmpl.output_format:
                # output_format is read later from config_manager; we override
                # it via a local variable handled below
                _tmpl_output_format = tmpl.output_format
            else:
                _tmpl_output_format = None
            if tmpl.parallel is not None and not parallel:
                parallel = tmpl.parallel
            if tmpl.timeout and timeout == 300:  # 300 is the CLI default
                timeout = tmpl.timeout
            # Account filter defaults: apply only when not provided on the CLI
            if tmpl.accounts and not accounts:
                accounts = tmpl.accounts
            if tmpl.team and not team:
                team = tmpl.team
            if tmpl.tags and not tags:
                tags = tuple(tmpl.tags)
            if tmpl.save is not None and not save:
                save = tmpl.save
        else:
            _tmpl_output_format = None
            # A single quoted argument ('ec2 describe-instances --query "..."') is
            # split with shell rules; multiple arguments (after --) are used as-is.
            if len(command) == 1:
                command = tuple(shlex.split(command[0]))

        # ------------------------------------------------------------------
        # Security check: validate the resolved command
        # ------------------------------------------------------------------
        from ..config.schema import is_destructive_command
        allow_destructive = config_manager.get_bool('security', 'allow-destructive-commands', False)
        resolved_cmd_str = ' '.join(command)
        if is_destructive_command(resolved_cmd_str) and not allow_destructive:
            click.echo(
                f"❌ Command '{resolved_cmd_str}' is considered destructive. "
                "Set allow-destructive-commands = true in config to run it.",
                err=True,
            )
            return

        click.echo(f"⚡ Running command: {command}")
        click.echo(f"Across accounts: {accounts}")
        click.echo(f"Selected team: {team}")
        click.echo("Using each account's configured profile")

        if not accounts and not team and not tags:
            click.echo("❌ You must specify --accounts, --team, or --tag to select accounts", err=True)
            return
        if all_regions and region:
            click.echo("⚠️  --all-regions and --region are mutually exclusive; ignoring --region")
            region = None
        # Get configuration values
        config_region = region or config_manager.get('general', 'region', 'us-east-1')
        output_format = _tmpl_output_format or config_manager.get('output', 'format', 'json')
        output_pattern = config_manager.get('output', 'pattern', '!A-!c-!d')  # Get configurable pattern
        
        # Parse tag filters
        tag_filter: dict = {}
        for tag_item in (tags or []):
            if '=' not in tag_item:
                click.echo(f"❌ Invalid tag format: '{tag_item}'. Use key=value format.", err=True)
                return
            k, v = tag_item.split('=', 1)
            tag_filter[k.strip()] = v.strip()

        # Parse account list
        account_manager = get_account_manager(ctx)
        if team:
            account_ids = []
            team_list = [t.strip() for t in team.split(',')]
            for t in team_list:
                click.echo(f"📂 Including accounts from team: {t}")
                team_accounts = account_manager.get_accounts_by_team(t)
                for acc in team_accounts:
                    if acc.id not in account_ids:
                        account_ids.append(acc.id)
        elif accounts:
            account_ids = parse_account_list(accounts)
        else:
            # tag-only selection: use all accounts
            account_ids = [acc.id for acc in account_manager.get_accounts()]

        # Apply tag filter if provided
        if tag_filter:
            if tag_filter:
                click.echo(
                    f"🏷️  Filtering by tag(s): "
                    + ", ".join(f"{k}={v}" for k, v in tag_filter.items())
                )
            tagged_ids = {
                acc.id for acc in account_manager.get_accounts_by_tags(tag_filter)
            }
            account_ids = [aid for aid in account_ids if aid in tagged_ids]
                
        if not account_ids:
            click.echo("❌ No valid account IDs found", err=True)
            return
        
        click.echo(f"📋 Processing {len(account_ids)} account(s)")
        
        # Get account manager and ensure authentication
        ctx.obj.ensure_authenticated()
        
        # Validate accounts and check they have profiles configured
        valid_accounts = []
        
        for account_id in account_ids:
            account = account_manager.get_account(account_id)
            if not account:
                click.echo(f"⚠️  Account {account_id} not found. Run 'init' command first.")
                continue
                
            if not account.profile_name:
                click.echo(f"⚠️  No profile configured for account {account_id} ({account.name if account else 'unknown'}).")
                click.echo(f"   Run 'multi-aws profiles --accounts {account_id} --role <role-name>' to generate profile")
                continue
            
            valid_accounts.append(account)
            click.echo(f"✅ {account.name} ({account.id}) - using profile: {account.profile_name}")
        
        if not valid_accounts:
            click.echo("❌ No valid accounts with configured profiles found", err=True)
            return

        # Determine regions to run on
        if all_regions:
            click.echo("🌍 Fetching available AWS regions...")
            try:
                region_result = subprocess.run(
                    [
                        'aws', '--profile', valid_accounts[0].profile_name,
                        '--region', config_region,
                        'ec2', 'describe-regions',
                        '--filters', 'Name=opt-in-status,Values=opt-in-not-required,opted-in',
                        '--query', 'Regions[].RegionName', '--output', 'json'
                    ],
                    capture_output=True, text=True, timeout=30
                )
                if region_result.returncode == 0:
                    regions_to_run = sorted(json.loads(region_result.stdout))
                    click.echo(f"🌍 Running across {len(regions_to_run)} region(s): {', '.join(regions_to_run)}")
                else:
                    click.echo(f"⚠️  Could not fetch regions: {region_result.stderr.strip()}")
                    click.echo(f"   Falling back to configured region: {config_region}")
                    regions_to_run = [config_region]
            except Exception as e:
                click.echo(f"⚠️  Failed to fetch regions: {e}")
                regions_to_run = [config_region]
        else:
            regions_to_run = [config_region]

        # Prepare output directory
        output_path = None
        if output_dir:
            output_path = os.path.expanduser(output_dir)
        elif save:  # use the default save location from the config file
            output_path = os.path.expanduser(config_manager.get('output', 'path'))
        if output_path:
            os.makedirs(output_path, exist_ok=True)
            click.echo(f"💾 Output will be saved to: {output_path}")

        accounts_by_id = {acc.id: acc for acc in valid_accounts}

        def report_result(result):
            """Print (and optionally save) each result as it completes."""
            account = accounts_by_id[result.account_id]
            label = f"{account.name} ({result.region})"

            if dry_run:
                click.echo(f"🔄 {label}: {result.error}")
                return

            if output_path and result.exit_code is not None:
                file_path = _write_result_file(result, account, output_path,
                                               output_pattern, output_format)
                result.output_file = file_path

            if result.status == 'SUCCESS':
                click.echo(f"✅ {label}: Command completed successfully")
                if verbose and result.has_output():
                    out = result.output
                    click.echo(f"📄 Output:\n{out[:500]}{'...' if len(out) > 500 else ''}")
            elif result.status == 'TIMEOUT':
                click.echo(f"⏰ {label}: Command timed out after {timeout}s")
            else:
                click.echo(f"❌ {label}: Command failed")
                click.echo(f"📄 Error: {result.error}")

        mode = "in parallel" if parallel else "sequentially"
        click.echo(f"🚀 Executing commands {mode} across {len(valid_accounts)} account(s) "
                   f"and {len(regions_to_run)} region(s)...")

        summary = execute(
            list(command),
            valid_accounts,
            regions=regions_to_run,
            parallel=parallel,
            timeout=timeout,
            output_format=output_format,
            allow_destructive=allow_destructive,
            dry_run=dry_run,
            account_manager=account_manager,
            config_manager=config_manager,
            on_result=report_result,
        )

        click.echo(f"\n📊 Execution Summary:")
        click.echo(f"  ✅ Successful: {summary.successful_accounts}")
        click.echo(f"  ❌ Failed: {summary.failed_accounts}")
        click.echo(f"  ⏰ Timeouts: {summary.timeout_accounts}")
        click.echo(f"  📋 Total: {summary.total_accounts}")

        if output_path:
            click.echo(f"\n💾 All outputs saved to: {output_path}")
            summary_file = os.path.join(
                output_path, f"execution_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(summary_file, 'w') as f:
                json.dump(_legacy_summary_records(summary, accounts_by_id), f, indent=2, default=str)
            click.echo(f"📋 Summary saved to: {summary_file}")

    except ExecutionError as e:
        click.echo(f"❌ {e}", err=True)
    except AccountManagerError as e:
        click.echo(f"❌ Command execution error: {e}", err=True)
    except (OSError, IOError) as e:
        click.echo(f"❌ File operation error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during command execution")


@cli.command()
@click.option('--team', help='Product team name to filter accounts')
@click.pass_context
def list_team_accounts(ctx,team):
    """List accounts assigned to a specific product team"""
    click.echo("📋 Listing accounts by product team")
    
    try:
        # Get account manager
        account_manager = get_account_manager(ctx)
        
        if not team:
            click.echo("❌ Please specify a product team name using --team", err=True)
            return
        
        # Load current account data
        try:
            account_collection = account_manager.data_manager.load_accounts()
        except Exception as e:
            click.echo(f"❌ Failed to load account data: {e}", err=True)
            return
        
        team_accounts = account_manager.get_accounts_by_team(team)
        
        if not team_accounts:
            click.echo(f"ℹ️  No accounts found for product team: {team}")
            return
        
        click.echo(f"📊 Found {len(team_accounts)} account(s) for product team: {team}\n")
        
        for account in team_accounts:
            click.echo(f"• {account.name} ({account.id}) - Profile: {account.profile_name or 'N/A'}")
        
    except AccountManagerError as e:
        click.echo(f"❌ Team listing error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during team listing")

@cli.command()
@click.option('--accounts', help='Comma-separated account IDs or file path to clean profiles for specific accounts')
@click.option('--team', help='Product team name to assign to the accounts')
@click.option('--overwrite', is_flag=True, help='Overwrite existing team assignments')
@click.pass_context
def assign_team(ctx, accounts, team, overwrite):
    """Assign a product team to specified accounts"""
    click.echo("🏷️  Assigning product team to accounts")
    
    try:
        # Get account manager
        account_manager: AccountManager = get_account_manager(ctx)

        
        if not accounts:
            click.echo("❌ Please specify accounts using --accounts", err=True)
            return
        
        if not team:
            click.echo("❌ Please specify a product team name using --team", err=True)
            return
        
        # Get account manager
        
        # Parse account list
        account_ids = parse_account_list(accounts)
        if not account_ids:
            click.echo("❌ No valid account IDs found", err=True)
            return
        
        click.echo(f"📋 Processing {len(account_ids)} account(s)")
        
        # Load current account data
        try:
            account_collection = account_manager.data_manager.load_accounts()
        except Exception as e:
            click.echo(f"❌ Failed to load account data: {e}", err=True)
            return
        
        updates_made = 0
        
        for account_id in account_ids:
            account = account_collection.get_account(account_id)
            if not account:
                click.echo(f"⚠️  Account {account_id} not found in account data")
                continue
            
            old_team = account.product_team
            if old_team != team and (overwrite or not old_team):
                account.set_team(team)
                click.echo(f"✅ Updated {account.name} ({account.id}): '{old_team}' -> '{team}'")
                updates_made += 1
            else:
                if overwrite:
                    click.echo(f"✓ {account.name} ({account.id}): product team already set to '{team}'")
                else:
                    click.echo(f"✓ {account.name} ({account.id}): product team already set as '{old_team}' and overwrite not enabled, skipping")
        if updates_made > 0:
            # Save the updated account collection
            try:
                account_manager.data_manager.save_accounts(account_collection)
                click.echo(f"\n✅ Successfully updated {updates_made} account(s)")
                click.echo(f"💾 Account data saved to: {account_manager.data_manager.file_path}")
            except Exception as e:
                click.echo(f"❌ Failed to save account data: {e}", err=True)
                return
        else:
            click.echo("\n✅ No updates were necessary")
        
    except AccountManagerError as e:
        click.echo(f"❌ Team assignment error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during team assignment")
        return
    

@cli.command('list-tags')
@click.option('--accounts', default=None,
              help='Comma-separated account IDs or file path. '
                   'If omitted together with --team, all accounts are listed.')
@click.option('--team', default=None, help='Team name to filter accounts')
@click.pass_context
def list_tags(ctx, accounts, team):
    """View tags stored on accounts"""
    try:
        account_manager = get_account_manager(ctx)
        collection = account_manager.data_manager.load_accounts()

        if accounts:
            account_ids = parse_account_list(accounts)
            selected = [collection.get_account(aid) for aid in account_ids]
            selected = [a for a in selected if a is not None]
        elif team:
            selected = account_manager.get_accounts_by_team(team)
        else:
            selected = list(collection.accounts)

        if not selected:
            click.echo("ℹ️  No matching accounts found.")
            return

        click.echo(f"🏷️  Tags for {len(selected)} account(s):\n")
        for account in selected:
            header = f"  {account.name} ({account.id})"
            if account.tags:
                click.echo(header)
                for key, value in sorted(account.tags.items()):
                    click.echo(f"    {key} = {value}")
            else:
                click.echo(f"{header}  — no tags")

    except AccountManagerError as e:
        click.echo(f"❌ Error listing tags: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during list-tags")


@cli.command('set-tag')
@click.option('--accounts', default=None,
              help='Comma-separated account IDs or file path')
@click.option('--team', default=None, help='Team name to filter accounts')
@click.option('--tag', 'tags', multiple=True, required=True, metavar='KEY=VALUE',
              help='Tag to set (key=value). Can be specified multiple times.')
@click.option('--overwrite', is_flag=True,
              help='Overwrite existing tag values. Without this flag, existing tags are skipped.')
@click.pass_context
def set_tag(ctx, accounts, team, tags, overwrite):
    """Set tags on accounts"""
    if not accounts and not team:
        click.echo("❌ Specify --accounts or --team to select accounts.", err=True)
        return

    # Parse tag pairs upfront so we can fail early on bad input
    tag_pairs: dict = {}
    for item in tags:
        if '=' not in item:
            click.echo(f"❌ Invalid tag format: '{item}'. Use key=value format.", err=True)
            return
        k, v = item.split('=', 1)
        tag_pairs[k.strip()] = v.strip()

    try:
        account_manager = get_account_manager(ctx)
        collection = account_manager.data_manager.load_accounts()

        if accounts:
            account_ids = parse_account_list(accounts)
            selected = [collection.get_account(aid) for aid in account_ids]
            selected = [a for a in selected if a is not None]
        else:
            selected = account_manager.get_accounts_by_team(team)

        if not selected:
            click.echo("ℹ️  No matching accounts found.")
            return

        click.echo(f"🏷️  Setting {len(tag_pairs)} tag(s) on {len(selected)} account(s)")
        updates_made = 0

        for account in selected:
            account_updated = False
            for key, value in tag_pairs.items():
                existing = account.tags.get(key)
                if existing is not None and existing == value:
                    click.echo(f"  ✓ {account.name} ({account.id}): {key}={value} (unchanged)")
                    continue
                if existing is not None and not overwrite:
                    click.echo(
                        f"  ⚠️  {account.name} ({account.id}): {key} already set to "
                        f"'{existing}', skipping (use --overwrite to replace)"
                    )
                    continue
                old_display = f"'{existing}'" if existing is not None else "unset"
                account.tags[key] = value
                account_updated = True
                click.echo(
                    f"  ✅ {account.name} ({account.id}): {key} {old_display} → '{value}'"
                )
            if account_updated:
                from datetime import datetime
                account.last_updated = datetime.now()
                updates_made += 1

        if updates_made > 0:
            account_manager.data_manager.save_accounts(collection)
            click.echo(f"\n💾 Updated {updates_made} account(s). "
                       f"Saved to: {account_manager.data_manager.file_path}")
        else:
            click.echo("\n✅ No updates were necessary.")

    except AccountManagerError as e:
        click.echo(f"❌ Error setting tags: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during set-tag")


@cli.command('remove-tag')
@click.option('--accounts', default=None,
              help='Comma-separated account IDs or file path')
@click.option('--team', default=None, help='Team name to filter accounts')
@click.option('--key', 'keys', multiple=True, required=True,
              help='Tag key to remove. Can be specified multiple times.')
@click.pass_context
def remove_tag(ctx, accounts, team, keys):
    """Remove tags from accounts"""
    if not accounts and not team:
        click.echo("❌ Specify --accounts or --team to select accounts.", err=True)
        return

    try:
        account_manager = get_account_manager(ctx)
        collection = account_manager.data_manager.load_accounts()

        if accounts:
            account_ids = parse_account_list(accounts)
            selected = [collection.get_account(aid) for aid in account_ids]
            selected = [a for a in selected if a is not None]
        else:
            selected = account_manager.get_accounts_by_team(team)

        if not selected:
            click.echo("ℹ️  No matching accounts found.")
            return

        click.echo(f"🗑️  Removing tag key(s) {list(keys)} from {len(selected)} account(s)")
        updates_made = 0

        for account in selected:
            account_updated = False
            for key in keys:
                if key in account.tags:
                    old_value = account.tags.pop(key)
                    account_updated = True
                    click.echo(
                        f"  ✅ {account.name} ({account.id}): removed {key}='{old_value}'"
                    )
                else:
                    click.echo(
                        f"  ✓ {account.name} ({account.id}): key '{key}' not present, skipping"
                    )
            if account_updated:
                from datetime import datetime
                account.last_updated = datetime.now()
                updates_made += 1

        if updates_made > 0:
            account_manager.data_manager.save_accounts(collection)
            click.echo(f"\n💾 Updated {updates_made} account(s). "
                       f"Saved to: {account_manager.data_manager.file_path}")
        else:
            click.echo("\n✅ No updates were necessary.")

    except AccountManagerError as e:
        click.echo(f"❌ Error removing tags: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during remove-tag")


@cli.command('sync-tags')
@click.option('--account', 'account_id', default=None,
              help='Account ID of the management or delegated-admin account to use for '
                   'Organizations access. The account must already be configured with a '
                   'profile (run \'profiles\' first). If omitted, the default credential '
                   'chain is used.')
@click.pass_context
def sync_tags(ctx, account_id):
    """Sync account tags from AWS Organizations"""
    click.echo("🏷️  Syncing account tags from AWS Organizations")

    try:
        account_manager = get_account_manager(ctx)

        profile_name = None
        if account_id:
            account = account_manager.get_account(account_id)
            if not account:
                click.echo(
                    f"❌ Account '{account_id}' not found. Run 'init' to discover accounts.",
                    err=True,
                )
                return
            if not account.profile_name:
                click.echo(
                    f"❌ No profile configured for account {account_id} ({account.name}).\n"
                    f"   Run 'profiles --accounts {account_id} --role <role-name>' first.",
                    err=True,
                )
                return
            profile_name = account.profile_name
            click.echo(
                f"🔑 Using account {account_id} ({account.name}) "
                f"with profile '{profile_name}' for Organizations access"
            )
        else:
            click.echo("🔑 Using default credentials for Organizations access")

        counts = account_manager.sync_account_tags(profile_name=profile_name)

        synced = counts['synced']
        skipped = counts['skipped']
        failed = counts['failed']

        click.echo(f"\n📊 Tag sync results:")
        if synced:
            click.echo(f"  ✅ Synced tags for {synced} account(s)")
        if skipped:
            click.echo(f"  ⚪ No tags found for {skipped} account(s)")
        if failed:
            click.echo(f"  ❌ Failed for {failed} account(s)")

        if synced == 0 and skipped > 0 and failed == 0:
            click.echo(
                "\nℹ️  No tags were found. Possible reasons:\n"
                "  • The account(s) have no tags in AWS Organizations\n"
                "  • The credentials do not have Organizations access\n"
                "  • Your organization does not use account tags\n"
                "Try specifying --account with a management or delegated-admin account ID "
                "that has organizations:ListTagsForResource permission."
            )
        elif synced > 0:
            click.echo(f"\n💾 Tag data saved to: {account_manager.data_manager.file_path}")

    except AccountManagerError as e:
        click.echo(f"❌ Tag sync error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during tag sync")


@cli.command()
@click.option('--profiles', is_flag=True, help='Clean up generated profiles')
@click.option('--tokens', is_flag=True, help='Clean up SSO tokens')
@click.option('--accounts', is_flag=True, help='Clean up account data')
@click.option('--all', is_flag=True, help='Clean up everything')
@click.option('--confirm', is_flag=True, help='Skip confirmation prompt')
def cleanup(profiles, tokens, accounts, all, confirm):
    """Clean up tool-generated configurations"""
    
    if not any([profiles, tokens, accounts, all]):
        click.echo("Please specify what to clean up:")
        click.echo("  --profiles   Clean up generated AWS profiles")
        click.echo("  --tokens     Clean up SSO authentication tokens")
        click.echo("  --accounts   Clean up stored account data")
        click.echo("  --all        Clean up everything")
        return
    
    try:
        from ..config.manager import load_or_create_config
        import os
        import shutil
        
        # Load configuration
        config_manager = load_or_create_config()
        
        cleanup_items = []
        
        if all or profiles:
            cleanup_items.append("AWS profiles from ~/.aws/config")
        
        if all or tokens:
            cleanup_items.append("SSO authentication tokens")
        
        if all or accounts:
            account_file = config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json')
            cleanup_items.append(f"Account data from {account_file}")
        
        # Confirmation
        if not confirm:
            click.echo("🧹 The following items will be cleaned up:")
            for item in cleanup_items:
                click.echo(f"  • {item}")
            
            if not click.confirm("\nAre you sure you want to proceed?"):
                click.echo("Cleanup cancelled")
                return
        
        click.echo("🧹 Starting cleanup...")
        
        # Clean up profiles
        if all or profiles:
            aws_config_path = os.path.expanduser("~/.aws/config")
            
            if os.path.exists(aws_config_path):
                click.echo("⚠️  Profile cleanup requires manual intervention")
                click.echo(f"   Please manually remove tool-generated profiles from: {aws_config_path}")
                click.echo("   Look for profiles with format: [profile <account-name>-<role>]")
            else:
                click.echo("✅ No AWS config file found")
        
        # Clean up SSO tokens
        if all or tokens:
            sso_cache_dir = os.path.expanduser("~/.aws/sso/cache")
            cli_cache_dir = os.path.expanduser("~/.aws/cli/cache")
            
            removed_files = 0
            
            for cache_dir in [sso_cache_dir, cli_cache_dir]:
                if os.path.exists(cache_dir):
                    for filename in os.listdir(cache_dir):
                        file_path = os.path.join(cache_dir, filename)
                        if os.path.isfile(file_path) and filename.endswith('.json'):
                            try:
                                os.remove(file_path)
                                removed_files += 1
                            except OSError as e:
                                click.echo(f"⚠️  Could not remove {file_path}: {e}")
            
            if removed_files > 0:
                click.echo(f"✅ Removed {removed_files} SSO token file(s)")
            else:
                click.echo("✅ No SSO token files found")
        
        # Clean up account data
        if all or accounts:
            account_file = config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json')
            account_path = os.path.expanduser(account_file)
            
            if os.path.exists(account_path):
                try:
                    os.remove(account_path)
                    click.echo(f"✅ Removed account data: {account_path}")
                except OSError as e:
                    click.echo(f"❌ Could not remove account data: {e}")
            else:
                click.echo("✅ No account data file found")
        
        # Clean up tool directory if everything was cleaned
        if all:
            tool_dir = os.path.expanduser("~/.multi-aws")
            
            if os.path.exists(tool_dir):
                try:
                    # Only remove if directory is empty or only contains config
                    remaining_files = os.listdir(tool_dir)
                    if not remaining_files or remaining_files == ['config.ini']:
                        if 'config.ini' in remaining_files:
                            click.echo("⚠️  Configuration file preserved")
                            click.echo(f"   Remove manually if needed: {os.path.join(tool_dir, 'config.ini')}")
                        else:
                            shutil.rmtree(tool_dir)
                            click.echo(f"✅ Removed tool directory: {tool_dir}")
                    else:
                        click.echo(f"⚠️  Tool directory not empty: {tool_dir}")
                        click.echo("   Remove manually if all contents should be deleted")
                except OSError as e:
                    click.echo(f"⚠️  Could not remove tool directory: {e}")
        
        click.echo("\n🎉 Cleanup completed!")
        
        if all or profiles:
            click.echo("\n💡 Tip:")
            click.echo("  Run 'multi-aws clean-duplicates' to check for and remove duplicate profiles")
        
        if all or tokens:
            click.echo("\n📖 Next steps:")
            click.echo("  Run 'multi-aws init' to re-authenticate and discover accounts")
            click.echo("  Run 'multi-aws sync' to sync existing profiles from AWS config")
        
    except Exception as e:
        click.echo(f"❌ Cleanup error: {e}", err=True)
        logger.exception("Unexpected error during cleanup")


@cli.command()
@click.option('--shell', type=click.Choice(['bash', 'zsh', 'fish']), 
              help='Shell type for completion script')
def completion(shell):
    """Generate shell completion script for multi-aws command."""
    if not shell:
        # Try to detect shell from environment
        import os
        shell_env = os.environ.get('SHELL', '').split('/')[-1]
        if shell_env in ['bash', 'zsh', 'fish']:
            shell = shell_env
        else:
            shell = 'bash'  # default fallback
    
    click.echo(f"# Shell completion for multi-aws command ({shell})")
    click.echo("# Add this to your shell configuration file:")
    click.echo()
    
    if shell == 'bash':
        click.echo("# For bash, add to ~/.bashrc or ~/.bash_profile:")
        click.echo('eval "$(_MULTI_AWS_COMPLETE=bash_source multi-aws)"')
    elif shell == 'zsh':
        click.echo("# For zsh, add to ~/.zshrc:")
        click.echo('eval "$(_MULTI_AWS_COMPLETE=zsh_source multi-aws)"')
    elif shell == 'fish':
        click.echo("# For fish, add to ~/.config/fish/completions/multi-aws.fish:")
        click.echo('eval (env _MULTI_AWS_COMPLETE=fish_source multi-aws)')
    
    click.echo()
    click.echo("# Or run this command to install completion directly:")
    if shell == 'bash':
        click.echo('_MULTI_AWS_COMPLETE=bash_source multi-aws > ~/.multi-aws-completion.bash')
        click.echo('echo "source ~/.multi-aws-completion.bash" >> ~/.bashrc')
    elif shell == 'zsh':
        click.echo('_MULTI_AWS_COMPLETE=zsh_source multi-aws > ~/.multi-aws-completion.zsh')
        click.echo('echo "source ~/.multi-aws-completion.zsh" >> ~/.zshrc')
    elif shell == 'fish':
        click.echo('_MULTI_AWS_COMPLETE=fish_source multi-aws > ~/.config/fish/completions/multi-aws.fish')


@cli.command()
@click.pass_context
def tui(ctx):
    """Launch the interactive Terminal UI (TUI).

    Provides an interactive interface for browsing accounts, managing
    teams, viewing templates, and running commands via a guided workflow.
    Any command execution requested inside the TUI is carried out after
    the TUI exits, using the same engine as the 'run' command.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from ..tui.app import TUIApp

    try:
        account_manager = get_account_manager(ctx)
    except Exception as e:
        click.echo(f"❌ Failed to initialise account manager: {e}", err=True)
        return

    config_manager = ctx.obj.config_manager if ctx.obj else None

    app = TUIApp(account_manager, config_manager)
    try:
        result = app.run()
    except Exception as e:
        click.echo(f"❌ TUI error: {e}", err=True)
        logger.exception("Unexpected error in TUI")
        return

    # If the user confirmed a 'run' action inside the TUI, execute it now.
    if result and result.get('action') == 'run':
        account_ids = result['accounts']
        command_str = result['command']
        parallel    = result['parallel']
        region      = result['region'] or None
        dry_run     = result['dry_run']
        role_filter = result['role'] or None

        click.echo(f"\n🚀 Executing: aws {command_str}")
        click.echo(f"   Accounts : {len(account_ids)}")
        click.echo(f"   Mode     : {'parallel' if parallel else 'sequential'}")
        if region:
            click.echo(f"   Region   : {region}")
        if role_filter:
            click.echo(f"   Role     : {role_filter}")
        if dry_run:
            click.echo("   Dry-run  : YES")

        # Resolve Account objects
        try:
            collection = account_manager.data_manager.load_accounts()
        except Exception as e:
            click.echo(f"❌ Failed to load account data: {e}", err=True)
            return

        valid_accounts = []
        for aid in account_ids:
            acc = collection.get_account(aid)
            if acc is None:
                click.echo(f"⚠️  Account {aid} not found, skipping")
                continue
            if not acc.profile_name:
                click.echo(f"⚠️  No profile for {acc.name} ({aid}), skipping")
                continue
            valid_accounts.append(acc)

        if not valid_accounts:
            click.echo("❌ No valid accounts with profiles to run against.")
            return

        if dry_run:
            click.echo("\n📋 Dry-run – the following would be executed:")
            for acc in valid_accounts:
                r = region or 'default'
                click.echo(f"  aws --profile {acc.profile_name} --region {r} {command_str}")
            return

        # Delegate to the 'run' sub-command's core logic by re-invoking
        # it via ctx.invoke so all existing options / security checks apply.
        accounts_arg = ','.join(account_ids)
        cmd_tuple    = tuple(command_str.split())
        ctx.invoke(
            run,
            command=cmd_tuple,
            accounts=accounts_arg,
            team=None,
            tags=None,
            output_dir=None,
            region=region,
            all_regions=False,
            parallel=parallel,
            timeout=300,
            dry_run=False,
            save=False,
            verbose=False,
        )


if __name__ == '__main__':
    cli()