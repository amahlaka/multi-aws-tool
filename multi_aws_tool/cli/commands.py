"""
CLI command definitions for MultiAWSTool
"""

import click
import logging
import sys
from pathlib import Path
import os

# Import dependencies at module level
from ..config.manager import load_or_create_config, ConfigurationError
from ..aws.account_manager import AccountManager, AccountManagerError
from ..utils.validators import parse_account_list
from ..utils.logging_config import setup_logging_from_config
from ..models.config import MultiAWSConfig

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


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
        columns, lines = os.get_terminal_size()
        self.max_content_width = columns
        self.terminal_width = columns
        print("SET SIZE:", columns)
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
                from utils.logging_config import setup_logging
                setup_logging(logging.DEBUG if verbose else logging.INFO)
            
            # Get config values
            sso_session = self.config_manager.get('general', 'sso-session', 'default')
            region = self.config_manager.get('general', 'region', 'us-east-1')
            account_file = self.config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json')
            
            # Initialize account manager
            self.account_manager = AccountManager(sso_session, region, account_file)
            
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


def sanitize_profile_name_component(name: str) -> str:
    """
    Sanitize a name component for use in AWS profile names.
    
    AWS profile names should contain only alphanumeric characters, hyphens, and underscores.
    This function replaces spaces and other problematic characters with hyphens.
    """
    # Replace spaces, dots, and underscores with hyphens
    sanitized = name.replace(' ', '-').replace('_', '-').replace('.', '-')
    # Remove any characters that aren't alphanumeric or hyphens
    sanitized = ''.join(c for c in sanitized if c.isalnum() or c == '-')
    # Remove consecutive hyphens and ensure no leading/trailing hyphens
    sanitized = '-'.join(filter(None, sanitized.split('-')))
    return sanitized

@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0")
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.pass_context
def cli(ctx: click.Context, verbose):
    """MultiAWSTool - Multi-AWS Account Management Tool"""
    # Initialize application context
    ctx.ensure_object(AppContext)
    ctx.obj.verbose = verbose
    columns, lines = os.get_terminal_size()
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
        from config.manager import ConfigManager
        from config.manager import ConfigurationError
        from models.config import MultiAWSConfig
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
        click.echo("  1. Run 'python main.py init' to initialize SSO and discover accounts")
        click.echo("  2. Run 'python main.py roles --accounts <account-ids>' to fetch available roles")
        click.echo("  3. Run 'python main.py profiles --accounts <account-ids> --role <role-name>' to generate profiles")
        click.echo("  OR run 'python main.py sync' to sync existing profiles from ~/.aws/config")
        
    except ConfigurationError as e:
        click.echo(f"❌ Configuration error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during configuration")

@cli.command()
@click.option('--sso-session', default='default', help='SSO session name to use')
@click.pass_context
def init(ctx, sso_session):
    """Initialize SSO and discover AWS accounts"""
    click.echo(f"🚀 Initializing with SSO session: {sso_session}")
    
    try:
        from aws.sso_client import is_sso_configured
        
        # If a specific SSO session is provided, we need to reinitialize the account manager
        if sso_session != 'default' or not ctx.obj.account_manager:
            config_manager = ctx.obj.config_manager or load_or_create_config()
            region = config_manager.get('general', 'region', 'us-east-1')
            account_file = config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json')
            
            # Check if SSO session is configured
            if not is_sso_configured(sso_session):
                click.echo(f"❌ SSO session '{sso_session}' not found in AWS config")
                click.echo("Please configure SSO in ~/.aws/config first. Example:")
                click.echo(f"""
[sso-session {sso_session}]
sso_start_url = https://your-sso-portal.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access
""")
                return
            
            # Initialize account manager with specific session
            account_manager = AccountManager(sso_session, region, account_file)
            ctx.obj.account_manager = account_manager
        else:
            account_manager = get_account_manager(ctx)
        
        click.echo("🔐 Authenticating with AWS SSO...")
        if not account_manager.authenticate():
            click.echo("❌ SSO authentication failed")
            return
        
        click.echo("🔍 Discovering AWS accounts...")
        collection = account_manager.discover_accounts(force_refresh=True)
        
        # Sanitize account names for profile compatibility
        click.echo("🧹 Sanitizing account names for profile compatibility...")
        sanitized_count = 0
        for account in collection.accounts:
            original_name = account.name
            sanitized_name = sanitize_profile_name_component(account.name)
            
            if original_name != sanitized_name:
                account.name = sanitized_name
                click.echo(f"   Sanitized: '{original_name}' -> '{sanitized_name}' (ID: {account.id})")
                sanitized_count += 1
        
        if sanitized_count > 0:
            # Save the updated account collection with sanitized names
            try:
                account_manager.data_manager.save_accounts(collection)
                click.echo(f"📝 Sanitized {sanitized_count} account name(s)")
            except Exception as e:
                click.echo(f"⚠️  Could not save sanitized names: {e}")
        
        active_accounts = collection.get_active_accounts()
        disabled_accounts = collection.get_disabled_accounts()
        
        click.echo(f"\n✅ Account discovery complete!")
        click.echo(f"📊 Found {len(active_accounts)} active accounts, {len(disabled_accounts)} disabled")
        
        if active_accounts:
            click.echo(f"\n🏢 Active Accounts:")
            for account in active_accounts:
                click.echo(f"  • {account.id} - {account.name}")
        
        if disabled_accounts:
            click.echo(f"\n⚠️  Disabled Accounts:")
            for account in disabled_accounts:
                click.echo(f"  • {account.id} - {account.name}")
        
        click.echo(f"\n💾 Account data saved to: {account_manager.data_manager.file_path}")
        click.echo(f"\n🚀 Next steps:")
        click.echo(f"  1. Run 'python main.py roles --accounts <account-ids>' to fetch available roles")
        click.echo(f"  2. Run 'python main.py profiles --accounts <account-ids> --role <role-name>' to generate profiles")
        if sanitized_count == 0:
            click.echo(f"  OR run 'python main.py sanitize-names' if you have existing accounts with problematic names")
        
    except AccountManagerError as e:
        click.echo(f"❌ Account discovery error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during initialization")

@cli.command()
@click.option('--accounts', required=True, help='Comma-separated account IDs or file path')
@click.pass_context
def roles(ctx, accounts):
    """Fetch available roles for specified accounts"""
    click.echo(f"🔍 Fetching roles for accounts: {accounts}")
    
    try:
        # Parse account list
        account_ids = parse_account_list(accounts)
        if not account_ids:
            click.echo("❌ No valid account IDs found", err=True)
            return
        
        click.echo(f"📋 Processing {len(account_ids)} account(s)")
        
        # Get account manager and ensure authentication
        account_manager = get_account_manager(ctx)
        ctx.obj.ensure_authenticated()
        
        # Update roles for accounts
        click.echo("🔍 Fetching roles...")
        results = account_manager.update_roles_for_accounts(account_ids, force_refresh=True)
        
        # Display results
        successful_accounts = []
        failed_accounts = []
        
        for account_id, success in results.items():
            if success:
                successful_accounts.append(account_id)
            else:
                failed_accounts.append(account_id)
        
        if successful_accounts:
            click.echo(f"\n✅ Successfully fetched roles for {len(successful_accounts)} account(s):")
            
            for account_id in successful_accounts:
                account = account_manager.get_account(account_id)
                if account:
                    click.echo(f"\n🏢 {account.name} ({account.id}):")
                    if account.roles:
                        for role in account.roles:
                            click.echo(f"  • {role.name}")
                    else:
                        click.echo("  (No roles found)")
        
        if failed_accounts:
            click.echo(f"\n❌ Failed to fetch roles for {len(failed_accounts)} account(s):")
            for account_id in failed_accounts:
                click.echo(f"  • {account_id}")
        
        click.echo(f"\n💾 Role data saved to: {account_manager.data_manager.file_path}")
        click.echo(f"\n🚀 Next step:")
        click.echo(f"  Run 'python main.py profiles --accounts <account-ids> --role <role-name>' to generate profiles")
        
    except AccountManagerError as e:
        click.echo(f"❌ Role discovery error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during role discovery")

@cli.command()
@click.option('--accounts', required=True, help='Comma-separated account IDs or file path')
@click.option('--role', required=True, help='Role name to use for all accounts')
@click.option('--region', help='AWS region override')
@click.option('--format', type=click.Choice(['aws-cli', 'env-vars']), default='aws-cli', help='Output format')
@click.option('--output-file', help='File to write profiles to')
@click.option('--append-to-config', is_flag=True, help='Append profiles directly to ~/.aws/config')
@click.pass_context
def profiles(ctx, accounts, role, region, format, output_file, append_to_config):
    """Generate AWS CLI profiles for specified accounts and role"""
    click.echo(f"🔧 Generating {format} profiles for role '{role}'")
    
    try:
        from datetime import datetime
        import os
        
        # Get configuration values
        config_manager = ctx.obj.config_manager or load_or_create_config()
        config_region = region or config_manager.get('general', 'region', 'us-east-1')
        prefix = config_manager.get('general', 'prefix', 'multi-aws')
        
        # Parse account list
        account_ids = parse_account_list(accounts)
        if not account_ids:
            click.echo("❌ No valid account IDs found", err=True)
            return
        
        click.echo(f"📋 Processing {len(account_ids)} account(s)")
        
        # Get account manager and ensure authentication
        account_manager = get_account_manager(ctx)
        ctx.obj.ensure_authenticated()
        
        # Validate accounts and role
        profiles_data = []
        valid_accounts = []
        
        for account_id in account_ids:
            account = account_manager.get_account(account_id)
            if not account:
                click.echo(f"⚠️  Account {account_id} not found. Run 'init' command first.")
                continue
                
            if not account.roles:
                click.echo(f"⚠️  No roles found for account {account_id}. Run 'roles' command first.")
                continue
                
            # Check if role exists
            role_found = any(r.name == role for r in account.roles)
            if not role_found:
                click.echo(f"⚠️  Role '{role}' not found in account {account_id}")
                available_roles = [r.name for r in account.roles]
                click.echo(f"   Available roles: {', '.join(available_roles)}")
                continue
            
            valid_accounts.append(account)
            
            # Generate profile data
            if format == 'aws-cli':
                # Sanitize account name for profile naming
                sanitized_account_name = sanitize_profile_name_component(account.name)
                
                profile_name = f"{prefix}-{sanitized_account_name}-{role}"
                click.echo(f"   Creating profile: {profile_name} (from account: {account.name})")
                
                profiles_data.append(f"[profile {profile_name}]")
                profiles_data.append(f"sso_session = {account_manager.sso_client.sso_session_name}")
                profiles_data.append(f"sso_account_id = {account.id}")
                profiles_data.append(f"sso_role_name = {role}")
                profiles_data.append(f"region = {config_region}")
                profiles_data.append("")
                
                # Store the profile name in the account for future reference
                account.set_profile_name(profile_name)
            else:  # env-vars
                # Sanitize account name for profile naming
                sanitized_account_name = sanitize_profile_name_component(account.name)
                
                profile_name = f"{prefix}-{sanitized_account_name}-{role}"
                clean_name = account.name.replace('-', '_').replace(' ', '_').upper()
                profiles_data.append(f"# {account.name} ({account.id})")
                profiles_data.append(f"export AWS_PROFILE_{clean_name}='{profile_name}'")
                profiles_data.append("")
                
                # Store the profile name in the account for future reference
                account.set_profile_name(profile_name)
        
        if not valid_accounts:
            click.echo("❌ No valid accounts with the specified role found", err=True)
            return
        
        # Save profile names to account data
        try:
            # Load current account collection, update it, and save it back
            account_collection = account_manager.data_manager.load_accounts()
            account_manager.data_manager.save_accounts(account_collection)
            click.echo(f"📝 Updated account data with profile names")
        except Exception as e:
            logger.warning(f"Failed to save profile names to account data: {e}")
        
        # Output profiles
        profiles_content = '\n'.join(profiles_data)
        
        if append_to_config and format == 'aws-cli':
            # Append to AWS config file with duplicate checking
            aws_config_path = os.path.expanduser('~/.aws/config')
            
            # Ensure .aws directory exists
            aws_dir = os.path.dirname(aws_config_path)
            os.makedirs(aws_dir, exist_ok=True)
            
            # Check if config file exists, if not create with basic structure
            if not os.path.exists(aws_config_path):
                with open(aws_config_path, 'w') as f:
                    f.write("# AWS Config File\n\n")
            
            # Read existing config to check for duplicates
            existing_profiles = set()
            updated_profiles = []
            new_profiles = []
            
            try:
                with open(aws_config_path, 'r') as f:
                    existing_content = f.read()
                    
                # Parse existing profiles
                for line in existing_content.split('\n'):
                    if line.strip().startswith('[profile '):
                        profile_name = line.strip()[9:-1]  # Remove '[profile ' and ']'
                        existing_profiles.add(profile_name)
                
                # Separate new and existing profiles
                current_profiles = []
                for line in profiles_data:
                    if line.startswith('[profile '):
                        profile_name = line[9:-1]  # Remove '[profile ' and ']'
                        current_profiles.append(profile_name)
                        if profile_name in existing_profiles:
                            updated_profiles.append(profile_name)
                        else:
                            new_profiles.append(profile_name)
                
                if updated_profiles:
                    click.echo(f"🔄 Updating {len(updated_profiles)} existing profile(s):")
                    for profile in updated_profiles:
                        click.echo(f"   • {profile}")
                    
                    # Remove existing profiles from config content
                    lines = existing_content.split('\n')
                    new_lines = []
                    skip_section = False
                    current_section = None
                    
                    for line in lines:
                        line_stripped = line.strip()
                        
                        # Check for profile section
                        if line_stripped.startswith('[profile ') and line_stripped.endswith(']'):
                            current_section = line_stripped[9:-1]  # Remove '[profile ' and ']'
                            skip_section = current_section in updated_profiles
                            
                        # Add line if we're not skipping this section
                        if not skip_section:
                            new_lines.append(line)
                        
                        # Reset skip flag if we hit an empty line (end of section)
                        if not line_stripped:
                            skip_section = False
                    
                    existing_content = '\n'.join(new_lines)
                
                if new_profiles:
                    click.echo(f"➕ Creating {len(new_profiles)} new profile(s):")
                    for profile in new_profiles:
                        click.echo(f"   • {profile}")
                
            except Exception as e:
                click.echo(f"⚠️  Could not parse existing config: {e}")
                existing_content = ""
            
            # Write updated config file
            try:
                with open(aws_config_path, 'w') as f:
                    if existing_content.strip():
                        f.write(existing_content.rstrip() + '\n\n')
                    
                    f.write(f"# Generated by MultiAWSTool - {role} profiles\n")
                    f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(profiles_content)
                    f.write("\n")
                
                click.echo(f"✅ Generated {len(valid_accounts)} profile(s) for role '{role}'")
                click.echo(f"📝 Profiles written to: {aws_config_path}")
                
                # Validate that all profiles can be found
                click.echo("\n🔍 Validating created profiles...")
                validation_errors = []
                
                try:
                    with open(aws_config_path, 'r') as f:
                        final_content = f.read()
                    
                    for account in valid_accounts:
                        profile_name = f"{prefix}-{sanitize_profile_name_component(account.name)}-{role}"
                        if f"[profile {profile_name}]" not in final_content:
                            validation_errors.append(profile_name)
                    
                    if validation_errors:
                        click.echo(f"❌ Failed to validate {len(validation_errors)} profile(s):")
                        for profile in validation_errors:
                            click.echo(f"   • {profile}")
                        click.echo("   These profiles may not have been created correctly.")
                    else:
                        click.echo(f"✅ All {len(valid_accounts)} profile(s) validated successfully")
                        
                except Exception as e:
                    click.echo(f"⚠️  Could not validate profiles: {e}")
                
            except Exception as e:
                click.echo(f"❌ Failed to write config file: {e}", err=True)
                return
            
        elif output_file:
            output_path = os.path.expanduser(output_file)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w') as f:
                f.write(profiles_content)
            
            click.echo(f"✅ Generated {len(valid_accounts)} profile(s) for role '{role}'")
            click.echo(f"💾 Profiles written to: {output_path}")
        else:
            click.echo(f"✅ Generated {len(valid_accounts)} profile(s) for role '{role}':")
            click.echo("\n" + profiles_content)
        
        # Show usage instructions
        if format == 'aws-cli':
            if append_to_config:
                click.echo("\n📖 Usage instructions:")
                click.echo("  Profiles have been added to your AWS config.")
                click.echo("  Use profiles with: aws --profile <profile-name> <command>")
            else:
                click.echo("\n📖 Usage instructions:")
                click.echo("1. Append the profiles to your ~/.aws/config file")
                click.echo("2. Use profiles with: aws --profile <profile-name> <command>")
            
            example_profile = f"{prefix}-{valid_accounts[0].name}-{role}"
            click.echo(f"   Example: aws --profile {example_profile} sts get-caller-identity")
        else:
            click.echo("\n📖 Usage instructions:")
            click.echo("1. Source the environment variables: source <output-file>")
            click.echo("2. Use variables with: aws --profile $AWS_PROFILE_<ACCOUNT> <command>")
        
        click.echo("\n🚀 Next step:")
        click.echo("  Run 'python main.py run \"<aws-command>\" --accounts <account-ids>' to execute commands")
        
    except AccountManagerError as e:
        click.echo(f"❌ Profile generation error: {e}", err=True)
    except (OSError, IOError) as e:
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
        import configparser
        import os
        
        # Get configuration values
        config_manager = ctx.obj.config_manager or load_or_create_config()
        prefix = config_manager.get('general', 'prefix', 'multi-aws')
        
        click.echo(f"📋 Looking for profiles with prefix: {prefix}")
        
        # Check if AWS config exists
        aws_config_path = os.path.expanduser('~/.aws/config')
        if not os.path.exists(aws_config_path):
            click.echo("❌ AWS config file not found at ~/.aws/config", err=True)
            return
        
        # Parse AWS config file
        config = configparser.ConfigParser()
        try:
            config.read(aws_config_path)
        except Exception as e:
            click.echo(f"❌ Failed to parse AWS config file: {e}", err=True)
            return
        
        # Get account manager
        account_manager = get_account_manager(ctx)
        
        # Find profiles with our prefix
        found_profiles = {}
        for section_name in config.sections():
            if section_name.startswith('profile '):
                profile_name = section_name[8:]  # Remove 'profile ' prefix
                
                if profile_name.startswith(prefix + '-'):
                    # This profile matches our prefix
                    profile_section = config[section_name]
                    
                    # Get account ID from the profile
                    account_id = profile_section.get('sso_account_id')
                    if account_id:
                        found_profiles[account_id] = profile_name
                        click.echo(f"🔍 Found profile: {profile_name} for account {account_id}")
        
        if not found_profiles:
            click.echo(f"✅ No profiles found with prefix '{prefix}' in AWS config")
            return
        
        click.echo(f"\n📊 Found {len(found_profiles)} matching profile(s)")
        
        # Load current account data
        try:
            account_collection = account_manager.data_manager.load_accounts()
        except Exception as e:
            click.echo(f"❌ Failed to load account data: {e}", err=True)
            return
        
        # Update accounts with profile names
        updates_made = 0
        for account_id, profile_name in found_profiles.items():
            account = account_collection.get_account(account_id)
            
            if account:
                old_profile = account.profile_name
                if old_profile != profile_name:
                    if dry_run:
                        click.echo(f"🔄 Would update {account.name} ({account_id}): '{old_profile}' -> '{profile_name}'")
                    else:
                        account.set_profile_name(profile_name)
                        click.echo(f"✅ Updated {account.name} ({account_id}): '{old_profile}' -> '{profile_name}'")
                    updates_made += 1
                else:
                    click.echo(f"✓ {account.name} ({account_id}): profile already up to date")
            else:
                click.echo(f"⚠️  Account {account_id} not found in account data (profile: {profile_name})")
        
        if updates_made > 0:
            if dry_run:
                click.echo(f"\n📝 Dry run: {updates_made} account(s) would be updated")
                click.echo("   Run without --dry-run to apply changes")
            else:
                # Save the updated account collection
                try:
                    account_manager.data_manager.save_accounts(account_collection)
                    click.echo(f"\n✅ Successfully updated {updates_made} account(s)")
                    click.echo(f"💾 Account data saved to: {account_manager.data_manager.file_path}")
                except Exception as e:
                    click.echo(f"❌ Failed to save account data: {e}", err=True)
                    return
        else:
            click.echo("\n✅ All profiles are already up to date")
        
        # Show summary
        click.echo(f"\n📋 Sync Summary:")
        click.echo(f"  🔍 Profiles found: {len(found_profiles)}")
        click.echo(f"  ✅ Updates made: {updates_made}")
        
        if not dry_run and updates_made > 0:
            click.echo(f"\n🚀 Next step:")
            click.echo(f"  Run 'python main.py run \"<aws-command>\" --accounts <account-ids>' to test the synced profiles")
        
    except AccountManagerError as e:
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
        # Get account manager
        account_manager = get_account_manager(ctx)
        
        # Load current account data
        try:
            account_collection = account_manager.data_manager.load_accounts()
        except Exception as e:
            click.echo(f"❌ Failed to load account data: {e}", err=True)
            return
        
        if not account_collection.accounts:
            click.echo("ℹ️  No accounts found in account data")
            return
        
        # Check each account for sanitization needs
        updates_made = 0
        for account in account_collection.accounts:
            original_name = account.name
            sanitized_name = sanitize_profile_name_component(account.name)
            
            if original_name != sanitized_name:
                if dry_run:
                    click.echo(f"🔄 Would sanitize: '{original_name}' -> '{sanitized_name}' (ID: {account.id})")
                else:
                    account.name = sanitized_name
                    click.echo(f"✅ Sanitized: '{original_name}' -> '{sanitized_name}' (ID: {account.id})")
                updates_made += 1
            else:
                click.echo(f"✓ {account.name} (ID: {account.id}): already sanitized")
        
        if updates_made > 0:
            if dry_run:
                click.echo(f"\n📝 Dry run: {updates_made} account name(s) would be sanitized")
                click.echo("   Run without --dry-run to apply changes")
            else:
                # Save the updated account collection
                try:
                    account_manager.data_manager.save_accounts(account_collection)
                    click.echo(f"\n✅ Successfully sanitized {updates_made} account name(s)")
                    click.echo(f"💾 Account data saved to: {account_manager.data_manager.file_path}")
                except Exception as e:
                    click.echo(f"❌ Failed to save account data: {e}", err=True)
                    return
        else:
            click.echo("\n✅ All account names are already sanitized")
        
        # Show summary
        click.echo(f"\n📋 Sanitization Summary:")
        click.echo(f"  📊 Accounts checked: {len(account_collection.accounts)}")
        click.echo(f"  ✅ Names sanitized: {updates_made}")
        
        if not dry_run and updates_made > 0:
            click.echo(f"\n🚀 Next steps:")
            click.echo(f"  1. Run 'python main.py profiles --accounts <account-ids> --role <role-name>' to regenerate profiles")
            click.echo(f"  2. Run 'python main.py sync' if you have existing profiles to update")
        
    except AccountManagerError as e:
        click.echo(f"❌ Sanitization error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during name sanitization")

@cli.command()
@click.option('--dry-run', is_flag=True, help='Show what would be cleaned without making changes')
@click.option('--prefix-only', is_flag=True, help='Only check profiles with the configured prefix')
def clean_duplicates(dry_run, prefix_only):
    """Check for and clean up duplicate profiles in ~/.aws/config"""
    click.echo("🔍 Checking for duplicate profiles in AWS config")
    
    try:
        from config.manager import load_or_create_config
        import configparser
        import os
        import shutil
        from collections import defaultdict
        
        # Load configuration
        config_manager = load_or_create_config()
        prefix = config_manager.get('general', 'prefix', 'multi-aws')
        
        if prefix_only:
            click.echo(f"📋 Checking only profiles with prefix: {prefix}")
        else:
            click.echo("📋 Checking all profiles")
        
        # Check if AWS config exists
        aws_config_path = os.path.expanduser('~/.aws/config')
        if not os.path.exists(aws_config_path):
            click.echo("❌ AWS config file not found at ~/.aws/config", err=True)
            return
        
        # Read the config file content
        try:
            with open(aws_config_path, 'r') as f:
                config_content = f.read()
        except Exception as e:
            click.echo(f"❌ Failed to read AWS config file: {e}", err=True)
            return
        
        # Parse AWS config file manually to handle duplicates
        profiles_data = []
        current_section = None
        current_profile = {}
        
        for line_num, line in enumerate(config_content.split('\n'), 1):
            line = line.strip()
            
            # Check for profile section
            if line.startswith('[profile ') and line.endswith(']'):
                # Save previous profile if exists
                if current_section and current_profile:
                    profiles_data.append({
                        'name': current_section,
                        'line_num': current_profile.get('start_line', line_num),
                        'config': current_profile.copy()
                    })
                
                # Start new profile
                current_section = line[9:-1]  # Remove '[profile ' and ']'
                current_profile = {'start_line': line_num}
                
            elif current_section and '=' in line:
                # Parse config line
                key, value = line.split('=', 1)
                current_profile[key.strip()] = value.strip()
        
        # Handle last profile
        if current_section and current_profile:
            profiles_data.append({
                'name': current_section,
                'line_num': current_profile.get('start_line', len(config_content.split('\n'))),
                'config': current_profile.copy()
            })
        
        # Group profiles by their key attributes to find duplicates
        profile_groups = defaultdict(list)
        total_profiles = len(profiles_data)
        
        for profile_data in profiles_data:
            profile_name = profile_data['name']
            profile_config = profile_data['config']
            
            # Skip if prefix_only is set and profile doesn't match prefix
            if prefix_only and not profile_name.startswith(prefix + '-'):
                continue
            
            # Create a key based on account ID and role for grouping
            account_id = profile_config.get('sso_account_id', '')
            role_name = profile_config.get('sso_role_name', '')
            sso_session = profile_config.get('sso_session', '')
            
            if account_id and role_name:
                # Group by account_id + role_name + sso_session
                group_key = f"{account_id}-{role_name}-{sso_session}"
                profile_groups[group_key].append({
                    'name': profile_name,
                    'line_num': profile_data['line_num'],
                    'account_id': account_id,
                    'role_name': role_name,
                    'sso_session': sso_session,
                    'config': profile_config
                })
        
        click.echo(f"📊 Found {total_profiles} total profiles in AWS config")
        
        # Find duplicates
        duplicates_found = 0
        profiles_to_remove = []
        
        for group_key, profiles in profile_groups.items():
            if len(profiles) > 1:
                duplicates_found += len(profiles) - 1
                
                # Sort profiles to keep the most recent or appropriately named one
                # Keep the first one that matches our prefix pattern, or the first one alphabetically
                profiles.sort(key=lambda x: (
                    not x['name'].startswith(prefix + '-'),  # Prefer our prefix
                    x['name']  # Then alphabetical
                ))
                
                keeper = profiles[0]
                duplicates = profiles[1:]
                
                click.echo(f"\n🔍 Found duplicates for {keeper['account_id']} + {keeper['role_name']}:")
                click.echo(f"   ✅ Keeping: {keeper['name']}")
                
                for duplicate in duplicates:
                    click.echo(f"   ❌ Duplicate: {duplicate['name']}")
                    profiles_to_remove.append(duplicate['name'])  # Store profile name instead of section
        
        if duplicates_found == 0:
            if prefix_only:
                click.echo(f"✅ No duplicate profiles found with prefix '{prefix}'")
            else:
                click.echo("✅ No duplicate profiles found")
            return
        
        click.echo(f"\n📋 Summary:")
        click.echo(f"  🔍 Duplicate profiles found: {duplicates_found}")
        click.echo(f"  🗑️  Profiles to remove: {len(profiles_to_remove)}")
        
        if dry_run:
            click.echo("\n📝 Dry run: No changes made")
            click.echo("   Run without --dry-run to remove duplicates")
            return
        
        # Confirm removal
        if not click.confirm(f"\nAre you sure you want to remove {len(profiles_to_remove)} duplicate profile(s)?"):
            click.echo("Operation cancelled")
            return
        
        # Create backup
        backup_path = f"{aws_config_path}.backup.{int(__import__('time').time())}"
        try:
            shutil.copy2(aws_config_path, backup_path)
            click.echo(f"📋 Created backup: {backup_path}")
        except Exception as e:
            click.echo(f"⚠️  Could not create backup: {e}")
            if not click.confirm("Continue without backup?"):
                return
        
        # Remove duplicate sections from config by rebuilding the file
        lines = config_content.split('\n')
        new_lines = []
        skip_section = False
        current_section = None
        
        for line in lines:
            line_stripped = line.strip()
            
            # Check for profile section
            if line_stripped.startswith('[profile ') and line_stripped.endswith(']'):
                current_section = line_stripped[9:-1]  # Remove '[profile ' and ']'
                skip_section = current_section in profiles_to_remove
                
            # Add line if we're not skipping this section
            if not skip_section:
                new_lines.append(line)
            
            # Reset skip flag if we hit an empty line (end of section)
            if not line_stripped:
                skip_section = False
        
        # Write updated config back to file
        try:
            with open(aws_config_path, 'w') as f:
                f.write('\n'.join(new_lines))
            
            click.echo(f"\n✅ Successfully removed {len(profiles_to_remove)} duplicate profile(s)")
            click.echo(f"💾 Updated AWS config saved to: {aws_config_path}")
            
        except Exception as e:
            click.echo(f"❌ Failed to write updated config: {e}", err=True)
            if os.path.exists(backup_path):
                click.echo(f"   Backup available at: {backup_path}")
            return
        
        click.echo(f"\n🚀 Next steps:")
        click.echo(f"  Run 'python main.py sync' to update account data with current profiles")
        
    except Exception as e:
        click.echo(f"❌ Duplicate cleanup error: {e}", err=True)
        logger.exception("Unexpected error during duplicate cleanup")

@cli.command()
@click.option('--accounts', help='Comma-separated account IDs or file path')
@click.option('--team', help='Team name(s) to select accounts from')
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
def run(ctx: click.Context, command: tuple, accounts, team, output_dir, region, all_regions, parallel, timeout, dry_run, save, verbose):
    """Execute AWS CLI command across multiple accounts using their configured profiles"""
    click.echo(f"⚡ Running command: {command}")
    click.echo(f"Across accounts: {accounts}")
    click.echo(f"Selected team: {team}")
    click.echo("Using each account's configured profile")
    print(ctx.max_content_width)
    
    try:
        from models.result import CommandResult, ResultStatus
        import subprocess
        import os
        import json
        from datetime import datetime
        from concurrent.futures import ThreadPoolExecutor, as_completed
        if not accounts and not team:
            click.echo("❌ You must specify either --accounts or --team to select accounts", err=True)
            return
        if all_regions and region:
            click.echo("⚠️  --all-regions and --region are mutually exclusive; ignoring --region")
            region = None
        # Get configuration values
        config_manager = ctx.obj.config_manager or load_or_create_config()
        config_region = region or config_manager.get('general', 'region', 'us-east-1')
        output_format = config_manager.get('output', 'format', 'json')
        output_pattern = config_manager.get('output', 'pattern', '!A-!c-!d')  # Get configurable pattern
        
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
        else:
            account_ids = parse_account_list(accounts)
                
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
                click.echo(f"   Run 'python main.py profiles --accounts {account_id} --role <role-name>' to generate profile")
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
        if output_dir:
            output_path = os.path.expanduser(output_dir)
            os.makedirs(output_path, exist_ok=True)
            click.echo(f"💾 Output will be saved to: {output_path}")
        elif save: # use the default save location from the configfile
            output_path = os.path.expanduser(config_manager.get('output', 'path'))
            os.makedirs(output_path, exist_ok=True)
            click.echo(f"💾 Output will be saved to: {output_path}")

        
        command_list = list(command)

        def execute_command_for_account(account, region):
            """Execute command for a single account and region using its configured profile"""
            profile_name = account.profile_name

            if not profile_name:
                click.echo(f"❌ {account.name}: No profile configured")
                return CommandResult(
                    account_id=account.id,
                    command=command,
                    status=ResultStatus.ERROR,
                    output="",
                    error="No profile configured for this account",
                    timestamp=datetime.now(),
                    execution_time=0
                )
            aws_command = [
                'aws', '--profile', profile_name,
                '--region', region,
                '--output', output_format,
            ]
            for cmd_part in command_list:
                if ' ' in cmd_part:
                    cmd_part = f'"{cmd_part}"'
                aws_command.append(cmd_part)

            start_time = datetime.now()
            
            try:
                click.echo(f"🔄 Executing on {account.name} ({account.id}) in {region}...")
                if dry_run:
                    click.echo(f"   Dry run: {' '.join(aws_command)}")
                    return CommandResult(
                        account_id=account.id,
                        command=command,
                        status=ResultStatus.SUCCESS,
                        output="",
                        error="Dry run - command not executed",
                        timestamp=start_time,
                        execution_time=0
                    )
                
                # Execute command
                result = subprocess.run(
                    aws_command,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                # Create result object
                command_result = CommandResult(
                    account_id=account.id,
                    command=command,
                    team=account.product_team if account.product_team else "N/A",
                    status=ResultStatus.SUCCESS if result.returncode == 0 else ResultStatus.ERROR,
                    output=result.stdout,
                    error=result.stderr,
                    timestamp=start_time,
                    execution_time=duration
                )
                
                # Save output to file if specified
                if output_dir or save:
                    timestamp_str = start_time.strftime('%Y%m%d_%H%M%S')
                    date_str = start_time.strftime('%Y%m%d')
                    time_str = start_time.strftime('%H%M%S')
                    
                    # Extract role from profile name for filename (profile format: prefix-account-role)
                    profile_parts = profile_name.split('-')
                    role_name = profile_parts[-1] if len(profile_parts) > 2 else 'unknown'
                    
                    # Extract only the command name (first part) without parameters
                    command_parts = command_list
                    # Skip AWS CLI global options and get the service and operation
                    command_name_parts = []
                    skip_next = False
                    
                    for part in command_parts:
                        if skip_next:
                            skip_next = False
                            continue
                        
                        # Skip AWS CLI global options
                        if part.startswith('--'):
                            # Some options have values, so we need to skip the next part too
                            if part in ['--profile', '--region', '--output', '--endpoint-url']:
                                skip_next = True
                            continue
                        
                        # This should be service and operation (e.g., 'securityhub', 'get-findings')
                        command_name_parts.append(part)
                        
                        # Stop after getting service and operation (first two non-option parts)
                        if len(command_name_parts) >= 2:
                            break
                    
                    # Create clean command name for filename
                    command_name = '-'.join(command_name_parts) if command_name_parts else 'unknown-command'
                    command_name = command_name.replace('/', '_')  # Replace any slashes
                    
                    # Generate filename using configurable pattern
                    # Pattern placeholders: !a=account_id, !A=account_name, !c=command, !d=date, !t=time, !s=timestamp, !r=role
                    # Default pattern: '!A-!c-!d' (account_name-command-date)
                    filename_base = output_pattern
                    filename_base = filename_base.replace('!a', account.id)
                    filename_base = filename_base.replace('!A', account.name.replace(' ', '_').replace('/', '_'))
                    filename_base = filename_base.replace('!c', command_name)
                    filename_base = filename_base.replace('!d', date_str)
                    filename_base = filename_base.replace('!t', time_str)
                    filename_base = filename_base.replace('!s', timestamp_str)
                    filename_base = filename_base.replace('!r', role_name)
                    filename_base = filename_base.replace('!S', command_name_parts[0] if command_name_parts else 'unknown-service')
                    filename_base = filename_base.replace('!C', command_name_parts[1] if len(command_name_parts) > 1 else 'unknown-operation')
                    filename_base = filename_base.replace('!p', account.product_team.replace(' ', '_').replace('/', '_') if account.product_team else 'unknown-team')
                    filename_base = filename_base.replace('!R', region)
                    filename = f"{filename_base}.{output_format}"
                    
                    #If format is set, validate that the data is in that format
                    if output_format == 'json':
                        try:
                            json.loads(result.stdout)
                        except json.JSONDecodeError as e:
                            click.echo(f"⚠️  Warning: Output is not valid JSON for account {account.name}: {e}")
                            # Add "-corrupted" suffix to filename
                            filename = f"{filename_base}-corrupted.{output_format}"
                    elif output_format == 'yaml' or output_format == 'yml':
                        try:
                            import yaml
                            yaml.safe_load(result.stdout)
                        except Exception as e:
                            click.echo(f"⚠️  Warning: Output is not valid YAML for account {account.name}: {e}")
                            # Add "-corrupted" suffix to filename
                            filename = f"{filename_base}-corrupted.{output_format}"
                    


                    # Filename base might contain also slashes, this is to allow subdirectories, check and create them
                    if '/' in filename:
                        subdir = os.path.dirname(filename)
                        full_subdir_path = os.path.join(output_path, subdir)
                        os.makedirs(full_subdir_path, exist_ok=True)
                    file_path = os.path.join(output_path, filename)
                    
                    with open(file_path, 'w') as f:
                        if result.returncode == 0:
                            f.write(result.stdout)
                        else:
                            f.write(f"ERROR: {result.stderr}\nSTDOUT: {result.stdout}")
                
                if result.returncode == 0:
                    click.echo(f"✅ {account.name}: Command completed successfully")
                    if verbose and result.stdout.strip():
                        click.echo(f"📄 Output:\n{result.stdout[:500]}{'...' if len(result.stdout) > 500 else ''}")
                else:
                    click.echo(f"❌ {account.name}: Command failed")
                    click.echo(f"📄 Error: {result.stderr}")
                
                return command_result
                
            except subprocess.TimeoutExpired:
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                click.echo(f"⏰ {account.name}: Command timed out after {timeout}s")
                
                return CommandResult(
                    account_id=account.id,
                    command=command,
                    status=ResultStatus.TIMEOUT,
                    output="",
                    error=f"Command timed out after {timeout} seconds",
                    timestamp=start_time,
                    execution_time=duration
                )
                
            except Exception as e:
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                click.echo(f"💥 {account.name}: Execution error: {e}")
                #also print the stack trace to the log
                logger.exception(f"Execution error for account {account.name} ({account.id})")
                
                return CommandResult(
                    account_id=account.id,
                    command=command,
                    status=ResultStatus.ERROR,
                    output="",
                    error=str(e),
                    timestamp=start_time,
                    execution_time=duration
                )
        
        # Execute commands
        execution_pairs = [(account, rgn) for account in valid_accounts for rgn in regions_to_run]
        results = []

        if parallel and len(execution_pairs) > 1:
            click.echo(f"🚀 Executing commands in parallel across {len(valid_accounts)} account(s) and {len(regions_to_run)} region(s)...")

            with ThreadPoolExecutor(max_workers=min(len(execution_pairs), 10)) as executor:
                future_to_pair = {
                    executor.submit(execute_command_for_account, account, rgn): (account, rgn)
                    for account, rgn in execution_pairs
                }

                for future in as_completed(future_to_pair):
                    result = future.result()
                    results.append(result)
        else:
            click.echo(f"📋 Executing commands sequentially across {len(valid_accounts)} account(s) and {len(regions_to_run)} region(s)...")

            for account, rgn in execution_pairs:
                result = execute_command_for_account(account, rgn)
                results.append(result)
        
        # Summary
        successful = sum(1 for r in results if r.status == ResultStatus.SUCCESS)
        failed = sum(1 for r in results if r.status == ResultStatus.ERROR)
        timeouts = sum(1 for r in results if r.status == ResultStatus.TIMEOUT)
        
        click.echo(f"\n📊 Execution Summary:")
        click.echo(f"  ✅ Successful: {successful}")
        click.echo(f"  ❌ Failed: {failed}")
        click.echo(f"  ⏰ Timeouts: {timeouts}")
        click.echo(f"  📋 Total: {len(results)}")
        
        if output_dir or save:
            click.echo(f"\n💾 All outputs saved to: {output_path}")
        
        # Save results summary
        if output_dir or save:
            summary_file = os.path.join(output_path, f"execution_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(summary_file, 'w') as f:
                json.dump([r.to_dict() for r in results], f, indent=2, default=str)
            click.echo(f"📋 Summary saved to: {summary_file}")
        
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
        from config.manager import load_or_create_config
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
            click.echo("  Run 'python main.py clean-duplicates' to check for and remove duplicate profiles")
        
        if all or tokens:
            click.echo("\n📖 Next steps:")
            click.echo("  Run 'python main.py init' to re-authenticate and discover accounts")
            click.echo("  Run 'python main.py sync' to sync existing profiles from AWS config")
        
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


if __name__ == '__main__':
    cli()