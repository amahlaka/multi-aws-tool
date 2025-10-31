#!/usr/bin/env python3
"""
Example: Using MultiAWSTool as a library in another Python project

This example shows how to:
1. Initialize the account manager
2. Discover AWS accounts via SSO
3. Access account information
4. Work with configuration
"""

from multi_aws_tool import (
    AccountManager, 
    ConfigManager, 
    Account,
    AccountManagerError,
    ConfigurationError
)

def main():
    """Example usage of MultiAWSTool as a library"""
    
    try:
        # Initialize configuration manager
        print("🔧 Loading configuration...")
        config = ConfigManager()
        
        # Load or create default configuration
        if not config.config_exists():
            print("📝 Creating default configuration...")
            config.save_config()
        config.load_config()
        print(f"✅ Configuration loaded. SSO session: {config.get('general', 'sso-session')}")
        
        # Initialize account manager
        print("\n🏢 Initializing account manager...")
        account_manager = AccountManager(
            sso_session_name=config.get('general', 'sso-session'),
            region=config.get('general', 'region')
        )
        # Discover accounts (this will use cached data if available)
        print("🔍 Discovering AWS accounts...")
        accounts = account_manager.discover_accounts()
        
        print(f"✅ Found {len(accounts.accounts)} accounts")
        print(f"📅 Last discovery: {accounts.discovery_timestamp}")
        
        # Display account information
        print("\n📋 Account Details:")
        for account in accounts.accounts:
            print(f"  • {account.name} ({account.id}) - Status: {account.status.value}")
            if account.roles:
                print(f"    Roles: {', '.join([role.name for role in account.roles])}")
        
        # Example: Get specific account
        if accounts.accounts:
            first_account = accounts.accounts[0]
            print(f"\n🎯 Example: Working with account '{first_account.name}'")
            print(f"   Account ID: {first_account.id}")
            print(f"   Profile Name: {first_account.profile_name}")
            print(f"   Last Updated: {first_account.last_updated}")
            
            if first_account.roles:
                print(f"   Available Roles:")
                for role in first_account.roles:
                    print(f"     - {role.name}: {role.arn}")
        
        # Example: Filter accounts by status
        active_accounts = [acc for acc in accounts.accounts if acc.status.value == "ACTIVE"]
        print(f"\n✅ Active accounts: {len(active_accounts)}")
        
        return accounts
        
    except AccountManagerError as e:
        print(f"❌ Account management error: {e}")
        return None
    except ConfigurationError as e:
        print(f"❌ Configuration error: {e}")
        return None
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return None

if __name__ == "__main__":
    accounts = main()