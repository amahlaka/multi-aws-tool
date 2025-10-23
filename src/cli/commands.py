"""
CLI command definitions for MultiAWSTool
"""

import click
import logging
import sys
from pathlib import Path

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

@click.group()
@click.version_option(version="0.1.0")
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
def cli(verbose):
    """MultiAWSTool - Multi-AWS Account Management Tool"""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Verbose mode enabled")

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
def init(sso_session):
    """Initialize SSO and discover AWS accounts"""
    click.echo(f"🚀 Initializing with SSO session: {sso_session}")
    
    try:
        from config.manager import load_or_create_config
        from aws.account_manager import AccountManager, AccountManagerError
        from aws.sso_client import is_sso_configured
        
        # Load configuration to get region and account file settings
        config_manager = load_or_create_config()
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
        
        # Initialize account manager
        account_manager = AccountManager(sso_session, region, account_file)
        
        click.echo("🔐 Authenticating with AWS SSO...")
        if not account_manager.authenticate():
            click.echo("❌ SSO authentication failed")
            return
        
        click.echo("🔍 Discovering AWS accounts...")
        collection = account_manager.discover_accounts(force_refresh=True)
        
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
        
        click.echo(f"\n💾 Account data saved to: {account_file}")
        click.echo(f"\n🚀 Next steps:")
        click.echo(f"  1. Run 'python main.py roles --accounts <account-ids>' to fetch available roles")
        click.echo(f"  2. Run 'python main.py profiles --accounts <account-ids> --role <role-name>' to generate profiles")
        
    except AccountManagerError as e:
        click.echo(f"❌ Account discovery error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during initialization")

@cli.command()
@click.option('--accounts', required=True, help='Comma-separated account IDs or file path')
def roles(accounts):
    """Fetch available roles for specified accounts"""
    click.echo(f"🔍 Fetching roles for accounts: {accounts}")
    
    try:
        from config.manager import load_or_create_config
        from aws.account_manager import AccountManager, AccountManagerError
        from utils.validators import parse_account_list
        
        # Load configuration
        config_manager = load_or_create_config()
        sso_session = config_manager.get('general', 'sso-session', 'default')
        region = config_manager.get('general', 'region', 'us-east-1')
        account_file = config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json')
        
        # Parse account list
        account_ids = parse_account_list(accounts)
        if not account_ids:
            click.echo("❌ No valid account IDs found", err=True)
            return
        
        click.echo(f"📋 Processing {len(account_ids)} account(s)")
        
        # Initialize account manager
        account_manager = AccountManager(sso_session, region, account_file)
        
        # Check if authenticated
        if not account_manager.is_authenticated():
            click.echo("🔐 Authenticating with AWS SSO...")
            if not account_manager.authenticate():
                click.echo("❌ SSO authentication failed", err=True)
                return
        
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
        
        click.echo(f"\n💾 Role data saved to: {account_file}")
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
def profiles(accounts, role, region, format, output_file, append_to_config):
    """Generate AWS CLI profiles for specified accounts and role"""
    click.echo(f"� Generating {format} profiles for role '{role}'")
    
    try:
        from config.manager import load_or_create_config
        from aws.account_manager import AccountManager, AccountManagerError
        from utils.validators import parse_account_list
        from datetime import datetime
        import os
        
        # Load configuration
        config_manager = load_or_create_config()
        sso_session = config_manager.get('general', 'sso-session', 'default')
        config_region = region or config_manager.get('general', 'region', 'us-east-1')
        account_file = config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json')
        prefix = config_manager.get('general', 'prefix', 'multi-aws')
        
        # Parse account list
        account_ids = parse_account_list(accounts)
        if not account_ids:
            click.echo("❌ No valid account IDs found", err=True)
            return
        
        click.echo(f"📋 Processing {len(account_ids)} account(s)")
        
        # Initialize account manager
        account_manager = AccountManager(sso_session, config_region, account_file)
        
        # Check if authenticated
        if not account_manager.is_authenticated():
            click.echo("🔐 Authenticating with AWS SSO...")
            if not account_manager.authenticate():
                click.echo("❌ SSO authentication failed", err=True)
                return
        
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
                profile_name = f"{prefix}-{account.name}-{role}"
                profiles_data.append(f"[profile {profile_name}]")
                profiles_data.append(f"sso_session = {sso_session}")
                profiles_data.append(f"sso_account_id = {account.id}")
                profiles_data.append(f"sso_role_name = {role}")
                profiles_data.append(f"region = {config_region}")
                profiles_data.append("")
                
                # Store the profile name in the account for future reference
                account.set_profile_name(profile_name)
            else:  # env-vars
                profile_name = f"{prefix}-{account.name}-{role}"
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
            # Append to AWS config file
            aws_config_path = os.path.expanduser('~/.aws/config')
            
            # Ensure .aws directory exists
            aws_dir = os.path.dirname(aws_config_path)
            os.makedirs(aws_dir, exist_ok=True)
            
            # Check if config file exists, if not create with basic structure
            if not os.path.exists(aws_config_path):
                with open(aws_config_path, 'w') as f:
                    f.write("# AWS Config File\n\n")
            
            # Append profiles to config file
            with open(aws_config_path, 'a') as f:
                f.write(f"\n# Generated by MultiAWSTool - {role} profiles\n")
                f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(profiles_content)
                f.write("\n")
            
            click.echo(f"✅ Generated {len(valid_accounts)} profile(s) for role '{role}'")
            click.echo(f"📝 Profiles appended to: {aws_config_path}")
            
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
def sync(dry_run):
    """Sync profile names from ~/.aws/config to account data"""
    click.echo("🔄 Syncing profiles from AWS config to account data")
    
    try:
        from config.manager import load_or_create_config
        from aws.account_manager import AccountManager, AccountManagerError
        import configparser
        import os
        
        # Load configuration
        config_manager = load_or_create_config()
        prefix = config_manager.get('general', 'prefix', 'multi-aws')
        sso_session = config_manager.get('general', 'sso-session', 'default')
        region = config_manager.get('general', 'region', 'us-east-1')
        account_file = config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json')
        
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
        
        # Initialize account manager
        account_manager = AccountManager(sso_session, region, account_file)
        
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
                    click.echo(f"💾 Account data saved to: {account_file}")
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
@click.argument('command')
@click.option('--accounts', required=True, help='Comma-separated account IDs or file path')
@click.option('--output-dir', help='Directory to save output files')
@click.option('--region', help='AWS region override')
@click.option('--parallel', is_flag=True, help='Execute commands in parallel')
@click.option('--timeout', type=int, default=300, help='Command timeout in seconds')
def run(command, accounts, output_dir, region, parallel, timeout):
    """Execute AWS CLI command across multiple accounts using their configured profiles"""
    click.echo(f"⚡ Running command: {command}")
    click.echo(f"Across accounts: {accounts}")
    click.echo("Using each account's configured profile")
    
    try:
        from config.manager import load_or_create_config
        from aws.account_manager import AccountManager, AccountManagerError
        from utils.validators import parse_account_list
        from models.result import CommandResult, ResultStatus
        import subprocess
        import os
        import json
        from datetime import datetime
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        # Load configuration
        config_manager = load_or_create_config()
        sso_session = config_manager.get('general', 'sso-session', 'default')
        config_region = region or config_manager.get('general', 'region', 'us-east-1')
        account_file = config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json')
        output_format = config_manager.get('output', 'format', 'json')
        
        # Parse account list
        account_ids = parse_account_list(accounts)
        if not account_ids:
            click.echo("❌ No valid account IDs found", err=True)
            return
        
        click.echo(f"📋 Processing {len(account_ids)} account(s)")
        
        # Initialize account manager
        account_manager = AccountManager(sso_session, config_region, account_file)
        
        # Check if authenticated
        if not account_manager.is_authenticated():
            click.echo("🔐 Authenticating with AWS SSO...")
            if not account_manager.authenticate():
                click.echo("❌ SSO authentication failed", err=True)
                return
        
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
                    # Extract role from profile name for filename (profile format: prefix-account-role)
                    profile_parts = profile_name.split('-')
                    role_name = profile_parts[-1] if len(profile_parts) > 2 else 'unknown'
                    filename = f"{account.name}_{role_name}_{timestamp_str}.{output_format}"
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
        
        if all or tokens:
            click.echo("\n📖 Next steps:")
            click.echo("  Run 'python main.py init' to re-authenticate and discover accounts")
            click.echo("  Run 'python main.py sync' to sync existing profiles from AWS config")
        
    except Exception as e:
        click.echo(f"❌ Cleanup error: {e}", err=True)
        logger.exception("Unexpected error during cleanup")

if __name__ == '__main__':
    cli()