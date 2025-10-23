"""
Account data persistence utilities for MultiAWSTool
Handles saving and loading account data to/from JSON files
"""

import json
import os
from pathlib import Path
from typing import Optional, List
import logging
from datetime import datetime

from models.account import Account, AccountCollection, Role

logger = logging.getLogger(__name__)

class AccountDataError(Exception):
    """Raised when account data operations fail"""

class AccountDataManager:
    """Manages persistence of account data to JSON files"""
    
    def __init__(self, file_path: Optional[str] = None):
        """
        Initialize account data manager
        
        Args:
            file_path: Optional custom path to account data file
        """
        if file_path:
            self.file_path = Path(file_path).expanduser().resolve()
        else:
            self.file_path = Path.home() / '.multi-aws' / 'accounts.json'
        
        # Ensure parent directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
    
    def file_exists(self) -> bool:
        """Check if the account data file exists"""
        return self.file_path.exists()
    
    def load_accounts(self) -> AccountCollection:
        """
        Load accounts from the JSON file
        
        Returns:
            AccountCollection with loaded accounts
            
        Raises:
            AccountDataError: If loading fails
        """
        if not self.file_exists():
            logger.info(f"Account file not found at {self.file_path}, creating empty collection")
            return AccountCollection()
        
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle both old format (just accounts list) and new format (with metadata)
            if isinstance(data, list):
                # Old format - just a list of accounts
                accounts_data = data
                last_discovery = None
            else:
                # New format - with metadata
                accounts_data = data.get('accounts', [])
                last_discovery = data.get('last_discovery')
            
            collection = AccountCollection()
            
            # Load accounts
            for account_data in accounts_data:
                try:
                    account = Account.from_dict(account_data)
                    collection.add_account(account)
                except Exception as e:
                    logger.warning(f"Failed to load account {account_data.get('id', 'unknown')}: {e}")
                    continue
            
            # Set last discovery time
            if last_discovery:
                try:
                    collection.last_discovery = datetime.fromisoformat(last_discovery)
                except ValueError:
                    logger.warning(f"Invalid last_discovery format: {last_discovery}")
            
            logger.info(f"Loaded {len(collection)} accounts from {self.file_path}")
            return collection
            
        except json.JSONDecodeError as e:
            raise AccountDataError(f"Invalid JSON in account file {self.file_path}: {e}") from e
        except Exception as e:
            raise AccountDataError(f"Failed to load accounts from {self.file_path}: {e}") from e
    
    def save_accounts(self, collection: AccountCollection) -> None:
        """
        Save accounts to the JSON file
        
        Args:
            collection: AccountCollection to save
            
        Raises:
            AccountDataError: If saving fails
        """
        try:
            # Create backup if file exists
            if self.file_exists():
                backup_path = self.file_path.with_suffix('.json.backup')
                import shutil
                shutil.copy2(self.file_path, backup_path)
                logger.debug(f"Created backup at {backup_path}")
            
            # Save collection data
            data = collection.to_dict()
            
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Set appropriate permissions (readable only by owner)
            os.chmod(self.file_path, 0o600)
            
            logger.info(f"Saved {len(collection)} accounts to {self.file_path}")
            
        except Exception as e:
            raise AccountDataError(f"Failed to save accounts to {self.file_path}: {e}") from e
    
    def add_account(self, account: Account) -> None:
        """
        Add or update a single account
        
        Args:
            account: Account to add or update
        """
        collection = self.load_accounts()
        collection.add_account(account)
        self.save_accounts(collection)
    
    def remove_account(self, account_id: str) -> bool:
        """
        Remove an account by ID
        
        Args:
            account_id: ID of account to remove
            
        Returns:
            True if account was removed, False if not found
        """
        collection = self.load_accounts()
        removed = collection.remove_account(account_id)
        if removed:
            self.save_accounts(collection)
        return removed
    
    def get_account(self, account_id: str) -> Optional[Account]:
        """
        Get a single account by ID
        
        Args:
            account_id: ID of account to retrieve
            
        Returns:
            Account if found, None otherwise
        """
        collection = self.load_accounts()
        return collection.get_account(account_id)
    
    def update_account(self, account: Account) -> bool:
        """
        Update an existing account
        
        Args:
            account: Account with updated data
            
        Returns:
            True if account was updated, False if not found
        """
        collection = self.load_accounts()
        existing = collection.get_account(account.id)
        if existing:
            collection.add_account(account)  # This replaces the existing one
            self.save_accounts(collection)
            return True
        return False
    
    def disable_account(self, account_id: str) -> bool:
        """
        Disable an account
        
        Args:
            account_id: ID of account to disable
            
        Returns:
            True if account was disabled, False if not found
        """
        collection = self.load_accounts()
        result = collection.disable_account(account_id)
        if result:
            self.save_accounts(collection)
        return result
    
    def enable_account(self, account_id: str) -> bool:
        """
        Enable an account
        
        Args:
            account_id: ID of account to enable
            
        Returns:
            True if account was enabled, False if not found
        """
        collection = self.load_accounts()
        result = collection.enable_account(account_id)
        if result:
            self.save_accounts(collection)
        return result
    
    def get_active_accounts(self) -> List[Account]:
        """Get all active accounts"""
        collection = self.load_accounts()
        return collection.get_active_accounts()
    
    def get_disabled_accounts(self) -> List[Account]:
        """Get all disabled accounts"""
        collection = self.load_accounts()
        return collection.get_disabled_accounts()
    
    def update_discovery_time(self) -> None:
        """Update the last discovery timestamp"""
        collection = self.load_accounts()
        collection.update_discovery_time()
        self.save_accounts(collection)
    
    def add_role_to_account(self, account_id: str, role: Role) -> bool:
        """
        Add a role to an account
        
        Args:
            account_id: ID of the account
            role: Role to add
            
        Returns:
            True if role was added, False if account not found
        """
        collection = self.load_accounts()
        account = collection.get_account(account_id)
        if account:
            account.add_role(role)
            self.save_accounts(collection)
            return True
        return False
    
    def remove_role_from_account(self, account_id: str, role_name: str) -> bool:
        """
        Remove a role from an account
        
        Args:
            account_id: ID of the account
            role_name: Name of the role to remove
            
        Returns:
            True if role was removed, False if account or role not found
        """
        collection = self.load_accounts()
        account = collection.get_account(account_id)
        if account:
            removed = account.remove_role(role_name)
            if removed:
                self.save_accounts(collection)
            return removed
        return False
    
    def set_profile_name(self, account_id: str, profile_name: str) -> bool:
        """
        Set the AWS profile name for an account
        
        Args:
            account_id: ID of the account
            profile_name: Profile name to set
            
        Returns:
            True if profile name was set, False if account not found
        """
        collection = self.load_accounts()
        account = collection.get_account(account_id)
        if account:
            account.set_profile_name(profile_name)
            self.save_accounts(collection)
            return True
        return False
    
    def export_accounts(self, export_path: str, account_ids: Optional[List[str]] = None) -> None:
        """
        Export accounts to a different file
        
        Args:
            export_path: Path to export file
            account_ids: Optional list of specific account IDs to export
        """
        collection = self.load_accounts()
        
        if account_ids:
            # Export only specified accounts
            export_collection = AccountCollection()
            for account_id in account_ids:
                account = collection.get_account(account_id)
                if account:
                    export_collection.add_account(account)
        else:
            # Export all accounts
            export_collection = collection
        
        # Save to export path
        export_manager = AccountDataManager(export_path)
        export_manager.save_accounts(export_collection)
    
    def import_accounts(self, import_path: str, merge: bool = True) -> int:
        """
        Import accounts from another file
        
        Args:
            import_path: Path to file to import from
            merge: If True, merge with existing accounts; if False, replace all
            
        Returns:
            Number of accounts imported
        """
        import_manager = AccountDataManager(import_path)
        import_collection = import_manager.load_accounts()
        
        if merge:
            # Merge with existing accounts
            existing_collection = self.load_accounts()
            for account in import_collection:
                existing_collection.add_account(account)
            self.save_accounts(existing_collection)
        else:
            # Replace all accounts
            self.save_accounts(import_collection)
        
        return len(import_collection)

# Convenience functions
def get_account_manager(file_path: Optional[str] = None) -> AccountDataManager:
    """Get a default account data manager instance"""
    return AccountDataManager(file_path)

def load_accounts(file_path: Optional[str] = None) -> AccountCollection:
    """Load accounts from the default or specified file"""
    manager = AccountDataManager(file_path)
    return manager.load_accounts()

def save_accounts(collection: AccountCollection, file_path: Optional[str] = None) -> None:
    """Save accounts to the default or specified file"""
    manager = AccountDataManager(file_path)
    manager.save_accounts(collection)