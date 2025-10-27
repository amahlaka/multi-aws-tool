"""
CLI command definitions for MultiAWSTool
"""

import click
import logging
import sys
from pathlib import Path

# Import dependencies at module level
from config.manager import load_or_create_config, ConfigurationError
from aws.account_manager import AccountManager, AccountManagerError
from utils.validators import parse_account_list

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

    def initialize(self, verbose=False):
        """Initialize the application context"""
        self.verbose = verbose
        
        try:
            # Load configuration
            self.config_manager = load_or_create_config()
            
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

@click.group()
@click.version_option(version="0.1.0")
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.pass_context
def cli(ctx, verbose):
    """MultiAWSTool - Multi-AWS Account Management Tool"""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Verbose mode enabled")
    
    # Initialize application context
    ctx.ensure_object(AppContext)
    try:
        ctx.obj.initialize(verbose=verbose)
    except Exception as e:
        # For some commands (like configure), we might not have a config yet
        # So we'll defer initialization to individual commands that need it
        logger.debug(f"Deferred context initialization: {e}")
        ctx.obj.verbose = verbose

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
        
        click.echo(f"\n💾 Account data saved to: {account_manager.data_manager.account_file}")
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
        
        click.echo(f"\n💾 Role data saved to: {account_manager.data_manager.account_file}")
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
    click.echo(f"� Generating {format} profiles for role '{role}'")
    
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
                profiles_data.append(f"sso_session = {account_manager.sso_session}")
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
                    click.echo(f"💾 Account data saved to: {account_manager.data_manager.account_file}")
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
                    click.echo(f"💾 Account data saved to: {account_manager.data_manager.account_file}")
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
@click.argument('command')
@click.option('--accounts', required=True, help='Comma-separated account IDs or file path')
@click.option('--output-dir', help='Directory to save output files')
@click.option('--region', help='AWS region override')
@click.option('--parallel', is_flag=True, help='Execute commands in parallel')
@click.option('--timeout', type=int, default=300, help='Command timeout in seconds')
@click.pass_context
def run(ctx, command, accounts, output_dir, region, parallel, timeout):
    """Execute AWS CLI command across multiple accounts using their configured profiles"""
    click.echo(f"⚡ Running command: {command}")
    click.echo(f"Across accounts: {accounts}")
    click.echo("Using each account's configured profile")
    
    try:
        from models.result import CommandResult, ResultStatus
        import subprocess
        import os
        import json
        from datetime import datetime
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        # Get configuration values
        config_manager = ctx.obj.config_manager or load_or_create_config()
        config_region = region or config_manager.get('general', 'region', 'us-east-1')
        output_format = config_manager.get('output', 'format', 'json')
        output_pattern = config_manager.get('output', 'pattern', '!A-!c-!d')  # Get configurable pattern
        
        # Parse account list
        account_ids = parse_account_list(accounts)
        if not account_ids:
            click.echo("❌ No valid account IDs found", err=True)
            return
        
        click.echo(f"📋 Processing {len(account_ids)} account(s)")
        
        # Get account manager and ensure authentication
        account_manager = get_account_manager(ctx)
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
        
        # Prepare output directory
        if output_dir:
            output_path = os.path.expanduser(output_dir)
            os.makedirs(output_path, exist_ok=True)
            click.echo(f"💾 Output will be saved to: {output_path}")
        
        def execute_command_for_account(account):
            """Execute command for a single account using its configured profile"""
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
            
            # Build AWS CLI command
            aws_command = [
                'aws', '--profile', profile_name,
                '--region', config_region,
                '--output', output_format
            ] + command.split()
            
            start_time = datetime.now()
            
            try:
                click.echo(f"🔄 Executing on {account.name} ({account.id})...")
                
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
                    status=ResultStatus.SUCCESS if result.returncode == 0 else ResultStatus.ERROR,
                    output=result.stdout,
                    error=result.stderr,
                    timestamp=start_time,
                    execution_time=duration
                )
                
                # Save output to file if specified
                if output_dir:
                    timestamp_str = start_time.strftime('%Y%m%d_%H%M%S')
                    date_str = start_time.strftime('%Y%m%d')
                    time_str = start_time.strftime('%H%M%S')
                    
                    # Extract role from profile name for filename (profile format: prefix-account-role)
                    profile_parts = profile_name.split('-')
                    role_name = profile_parts[-1] if len(profile_parts) > 2 else 'unknown'
                    
                    # Generate filename using configurable pattern
                    # Pattern placeholders: !a=account_id, !A=account_name, !c=command, !d=date, !t=time, !s=timestamp, !r=role
                    # Default pattern: '!A-!c-!d' (account_name-command-date)
                    filename_base = output_pattern
                    filename_base = filename_base.replace('!a', account.id)
                    filename_base = filename_base.replace('!A', account.name.replace(' ', '_').replace('/', '_'))
                    filename_base = filename_base.replace('!c', command.replace(' ', '_').replace('/', '_'))
                    filename_base = filename_base.replace('!d', date_str)
                    filename_base = filename_base.replace('!t', time_str)
                    filename_base = filename_base.replace('!s', timestamp_str)
                    filename_base = filename_base.replace('!r', role_name)
                    
                    filename = f"{filename_base}.{output_format}"
                    file_path = os.path.join(output_path, filename)
                    
                    with open(file_path, 'w') as f:
                        if result.returncode == 0:
                            f.write(result.stdout)
                        else:
                            f.write(f"ERROR: {result.stderr}\nSTDOUT: {result.stdout}")
                
                if result.returncode == 0:
                    click.echo(f"✅ {account.name}: Command completed successfully")
                    if not output_dir and result.stdout.strip():
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
        results = []
        
        if parallel and len(valid_accounts) > 1:
            click.echo(f"🚀 Executing commands in parallel...")
            
            with ThreadPoolExecutor(max_workers=min(len(valid_accounts), 10)) as executor:
                future_to_account = {
                    executor.submit(execute_command_for_account, account): account 
                    for account in valid_accounts
                }
                
                for future in as_completed(future_to_account):
                    result = future.result()
                    results.append(result)
        else:
            click.echo(f"📋 Executing commands sequentially...")
            
            for account in valid_accounts:
                result = execute_command_for_account(account)
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
        
        if output_dir:
            click.echo(f"\n💾 All outputs saved to: {output_path}")
        
        # Save results summary
        if output_dir:
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

@cli.command('parse-iam-reports')
@click.option('--summary-file', '-s', type=click.Path(exists=True), 
              help='Path to execution summary JSON file containing IAM credential report commands')
@click.option('--inactive-days', '-d', type=int, default=90, 
              help='Number of days to consider credentials inactive (default: 90)')
@click.option('--output', '-o', type=click.Path(), 
              help='Output file path for parsed report (optional)')
@click.option('--format', 'output_format', type=click.Choice(['json', 'yaml', 'table']), 
              default='table', help='Output format (default: table)')
@click.pass_context
def parse_iam_reports(ctx, summary_file, inactive_days, output, output_format):
    """Parse IAM credential reports from execution summary files"""
    
    try:
        import json
        from datetime import datetime
        from utils.report_parser import (
            parse_iam_report, 
            extract_user_credentials, 
            summarize_inactive_credentials,
            generate_credential_report_summary,
            process_multi,
            load_from_summary
        )
        from models.result import ExecutionSummary, CommandResult
        
        # Auto-detect latest summary file if not provided
        if not summary_file:
            outputs_dir = Path("outputs")
            if outputs_dir.exists():
                summary_files = list(outputs_dir.glob("execution_summary_*.json"))
                if summary_files:
                    # Get the most recent summary file
                    summary_file = max(summary_files, key=lambda f: f.stat().st_mtime)
                    click.echo(f"📄 Using latest summary file: {summary_file}")
                else:
                    click.echo("❌ No execution summary files found in outputs/ directory", err=True)
                    return
            else:
                click.echo("❌ outputs/ directory not found", err=True)
                return
        
        # Load execution summary
        res = load_from_summary(summary_file)
        reports = []
        for ac in res:
            print(ac["account_id"])
            print(len(ac["report"]["Users"]))
            creds = extract_user_credentials(ac["report"])
            print(creds)
            inactive_summary = summarize_inactive_credentials(creds, inactive_days)
            print(inactive_summary)
            report_summary = generate_credential_report_summary(
                creds,
                account_id=ac["account_id"],
                account_name = get_account_name(ctx, ac["account_id"]),
                inactive_summary=inactive_summary,
                inactive_days=inactive_days
            )
            reports.append(report_summary)

        # Output results
        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                if output_format == 'json':
                    json.dump([r.to_dict() for r in reports], f, indent=2)
                elif output_format == 'yaml':
                    import yaml
                    yaml.dump([r.to_dict() for r in reports], f)
                else:
                    f.write('\n\n'.join(r.to_table() for r in reports))
            click.echo(f"💾 Parsed report saved to: {output_path}")
        else: #pretty print
            for report in reports:
                print("Account:", report.account_name, "(", report.account_id, ")")
                print("Inactive Credentials (> {} days):".format(inactive_days))


    except Exception as e:
        click.echo(f"❌ Error loading summary file: {e}", err=True)
        print(e)
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

if __name__ == '__main__':
    cli()