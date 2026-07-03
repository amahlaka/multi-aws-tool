"""
Account management service for MultiAWSTool
Handles AWS account discovery, role enumeration, and account data management
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime

from .sso_client import SSOClient, SSOAuthenticationError
from .organizations_client import OrganizationsClient, OrganizationsAccessError
from ..models.account import Account, AccountCollection, AccountStatus, Role
from ..utils.account_data import AccountDataManager, AccountDataError

logger = logging.getLogger(__name__)

class AccountManagerError(Exception):
    """Raised when account management operations fail"""

class AccountManager:
    """Manages AWS accounts, roles, and their data persistence"""
    
    def __init__(self, sso_session_name: str = "default", region: str = "us-east-1", 
                 account_file_path: Optional[str] = None):
        """
        Initialize account manager
        
        Args:
            sso_session_name: SSO session name for authentication
            region: AWS region for SSO operations
            account_file_path: Optional custom path for account data file
        """
        self.sso_client = SSOClient(sso_session_name, region)
        self.data_manager = AccountDataManager(account_file_path)
        
    def discover_accounts(self, force_refresh: bool = False) -> AccountCollection:
        """
        Discover AWS accounts through SSO and update local data
        
        Args:
            force_refresh: If True, force fresh discovery even if recently updated
            
        Returns:
            AccountCollection with discovered accounts
            
        Raises:
            AccountManagerError: If discovery fails
        """
        try:
            # Load existing accounts
            existing_collection = self.data_manager.load_accounts()
            
            # Check if we need to refresh
            if not force_refresh and existing_collection.last_discovery:
                # If discovered within last hour, use cached data
                time_since_discovery = datetime.now() - existing_collection.last_discovery
                if time_since_discovery.total_seconds() < 3600:  # 1 hour
                    logger.info("Using cached account discovery (less than 1 hour old)")
                    return existing_collection
            
            logger.info("Discovering AWS accounts through SSO...")
            
            # Authenticate and discover accounts
            accounts_data = self.sso_client.list_accounts()
            
            # Get set of existing account IDs for comparison
            existing_account_ids = {acc.id for acc in existing_collection.accounts}
            discovered_account_ids = {acc_data['accountId'] for acc_data in accounts_data}
            
            # Create new collection
            new_collection = AccountCollection()
            
            # Process discovered accounts
            for account_data in accounts_data:
                account_id = account_data['accountId']
                account_name = account_data['accountName']
                
                # Check if we have existing data for this account
                existing_account = existing_collection.get_account(account_id)
                
                if existing_account:
                    # Update existing account with new discovery info
                    existing_account.name = account_name  # Update name in case it changed
                    existing_account.set_status(AccountStatus.ACTIVE)  # Mark as active
                    existing_account.last_updated = datetime.now()
                    new_collection.add_account(existing_account)
                    logger.debug(f"Updated existing account: {account_id} ({account_name})")
                else:
                    # Create new account
                    new_account = Account(
                        id=account_id,
                        name=account_name,
                        status=AccountStatus.ACTIVE
                    )
                    new_collection.add_account(new_account)
                    logger.info(f"Discovered new account: {account_id} ({account_name})")
            
            # Mark accounts that are no longer accessible as disabled
            disabled_accounts = existing_account_ids - discovered_account_ids
            for account_id in disabled_accounts:
                existing_account = existing_collection.get_account(account_id)
                if existing_account and existing_account.status == AccountStatus.ACTIVE:
                    existing_account.set_status(AccountStatus.DISABLED)
                    new_collection.add_account(existing_account)
                    logger.warning(f"Account no longer accessible, marking as disabled: {account_id}")
            
            # Update discovery timestamp
            new_collection.update_discovery_time()
            
            # Save updated collection
            self.data_manager.save_accounts(new_collection)
            
            active_count = len(new_collection.get_active_accounts())
            disabled_count = len(new_collection.get_disabled_accounts())
            logger.info(f"Account discovery complete: {active_count} active, {disabled_count} disabled")
            
            return new_collection
            
        except SSOAuthenticationError as e:
            raise AccountManagerError(f"SSO authentication failed during account discovery: {e}") from e
        except AccountDataError as e:
            raise AccountManagerError(f"Failed to save account data: {e}") from e
        except Exception as e:
            raise AccountManagerError(f"Account discovery failed: {e}") from e
    
    def discover_roles_for_account(self, account_id: str) -> List[Role]:
        """
        Discover roles for a specific account
        
        Args:
            account_id: AWS account ID
            
        Returns:
            List of discovered roles
            
        Raises:
            AccountManagerError: If role discovery fails
        """
        try:
            logger.info(f"Discovering roles for account {account_id}...")
            
            # Get roles from SSO
            roles_data = self.sso_client.list_account_roles(account_id)
            
            discovered_roles = []
            for role_data in roles_data:
                role_name = role_data['roleName']
                # Construct ARN (SSO doesn't provide full ARN)
                role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
                
                role = Role(
                    name=role_name,
                    arn=role_arn,
                    description=f"Role discovered via SSO for account {account_id}"
                )
                discovered_roles.append(role)
                logger.debug(f"Discovered role: {role_name}")
            
            logger.info(f"Discovered {len(discovered_roles)} roles for account {account_id}")
            return discovered_roles
            
        except SSOAuthenticationError as e:
            raise AccountManagerError(f"SSO authentication failed during role discovery: {e}") from e
        except Exception as e:
            raise AccountManagerError(f"Role discovery failed for account {account_id}: {e}") from e
    
    def update_account_roles(self, account_id: str, force_refresh: bool = False) -> bool:
        """
        Update roles for a specific account
        
        Args:
            account_id: AWS account ID
            force_refresh: If True, force fresh role discovery
            
        Returns:
            True if roles were updated, False if account not found
            
        Raises:
            AccountManagerError: If role update fails
        """
        try:
            # Load accounts
            collection = self.data_manager.load_accounts()
            account = collection.get_account(account_id)
            
            if not account:
                logger.warning(f"Account {account_id} not found in local data")
                return False
            
            if not account.is_active():
                logger.warning(f"Account {account_id} is disabled, skipping role update")
                return False
            
            # Check if we need to refresh roles
            if not force_refresh and account.roles:
                time_since_update = datetime.now() - account.last_updated
                if time_since_update.total_seconds() < 1800:  # 30 minutes
                    logger.info(f"Using cached roles for account {account_id} (updated recently)")
                    return True
            
            # Discover roles
            discovered_roles = self.discover_roles_for_account(account_id)
            
            # Update account with new roles
            account.roles.clear()  # Clear existing roles
            for role in discovered_roles:
                account.add_role(role)
            
            account.last_updated = datetime.now()
            
            # Save updated data
            self.data_manager.save_accounts(collection)
            
            logger.info(f"Updated {len(discovered_roles)} roles for account {account_id}")
            return True
            
        except AccountDataError as e:
            raise AccountManagerError(f"Failed to save role data: {e}") from e
    
    def update_roles_for_accounts(self, account_ids: List[str], force_refresh: bool = False) -> Dict[str, bool]:
        """
        Update roles for multiple accounts
        
        Args:
            account_ids: List of AWS account IDs
            force_refresh: If True, force fresh role discovery
            
        Returns:
            Dictionary mapping account ID to success status
        """
        results = {}
        
        for account_id in account_ids:
            try:
                success = self.update_account_roles(account_id, force_refresh)
                results[account_id] = success
                if success:
                    logger.info(f"Successfully updated roles for account {account_id}")
                else:
                    logger.warning(f"Failed to update roles for account {account_id}")
            except AccountManagerError as e:
                logger.error(f"Error updating roles for account {account_id}: {e}")
                results[account_id] = False
        
        successful_updates = sum(1 for success in results.values() if success)
        logger.info(f"Role update complete: {successful_updates}/{len(account_ids)} accounts updated")
        
        return results
    
    def get_accounts(self, status_filter: Optional[AccountStatus] = None) -> List[Account]:
        """
        Get accounts with optional status filter
        
        Args:
            status_filter: Optional filter by account status
            
        Returns:
            List of accounts
        """
        collection = self.data_manager.load_accounts()
        
        if status_filter:
            return collection.get_accounts_by_status(status_filter)
        else:
            return list(collection.accounts)
    
    def get_active_accounts(self) -> List[Account]:
        """Get all active accounts"""
        return self.get_accounts(AccountStatus.ACTIVE)
    
    def get_disabled_accounts(self) -> List[Account]:
        """Get all disabled accounts"""
        return self.get_accounts(AccountStatus.DISABLED)
    
    def get_account(self, account_id: str) -> Optional[Account]:
        """Get a specific account by ID"""
        return self.data_manager.get_account(account_id)
    
    def get_accounts_by_team(self, product_team: str) -> List[Account]:
        """
        Get accounts belonging to a specific product team
        
        Args:
            product_team: Name of the product team
            
        Returns:
            List of accounts in the specified team
        """
        collection = self.data_manager.load_accounts()
        return collection.get_accounts_by_product_team(product_team)
    
    def get_accounts_with_role(self, role_name: str) -> List[Account]:
        """
        Get accounts that have a specific role
        
        Args:
            role_name: Name of the role to search for
            
        Returns:
            List of accounts with the specified role
        """
        accounts = self.get_active_accounts()
        return [account for account in accounts if account.has_role(role_name)]
    
    def get_accounts_by_tags(self, tags: Dict[str, str]) -> List[Account]:
        """
        Get accounts that match all specified tags.

        Args:
            tags: Dict of tag key/value pairs that accounts must have

        Returns:
            List of accounts matching all supplied tags
        """
        collection = self.data_manager.load_accounts()
        return collection.get_accounts_by_tags(tags)

    def sync_account_tags(self, profile_name: Optional[str] = None) -> Dict[str, int]:
        """
        Sync account tags from AWS Organizations and persist them locally.

        Fetches tags for every account in the local data file using the
        Organizations ``list_tags_for_resource`` API.  Falls back cleanly
        when Organizations access is unavailable for any account.

        Args:
            profile_name: AWS profile with Organizations access (management /
                          delegated-admin account).  If *None*, the default
                          credential chain is used.

        Returns:
            Dict with keys ``synced``, ``skipped``, and ``failed`` containing
            the respective per-account counts.

        Raises:
            AccountManagerError: If the account data cannot be saved.
        """
        collection = self.data_manager.load_accounts()
        accounts = collection.accounts

        if not accounts:
            logger.info("No accounts in local data; nothing to sync")
            return {'synced': 0, 'skipped': 0, 'failed': 0}

        org_client = OrganizationsClient(profile_name=profile_name)

        synced = 0
        skipped = 0
        failed = 0

        for account in accounts:
            try:
                tags = org_client.get_tags_for_account(account.id)
                if tags:
                    account.tags = tags
                    account.last_updated = datetime.now()
                    synced += 1
                    logger.info(
                        f"Synced {len(tags)} tag(s) for account "
                        f"{account.id} ({account.name})"
                    )
                else:
                    skipped += 1
                    logger.debug(
                        f"No tags returned for account {account.id} "
                        f"({account.name})"
                    )
            except OrganizationsAccessError as exc:
                logger.error(
                    f"Organizations access error for account {account.id}: {exc}"
                )
                failed += 1
            except Exception as exc:
                logger.error(
                    f"Unexpected error syncing tags for account {account.id}: {exc}"
                )
                failed += 1

        if synced > 0:
            try:
                self.data_manager.save_accounts(collection)
            except AccountDataError as exc:
                raise AccountManagerError(
                    f"Failed to save synced tag data: {exc}"
                ) from exc

        logger.info(
            f"Tag sync complete: {synced} synced, {skipped} skipped, "
            f"{failed} failed"
        )
        return {'synced': synced, 'skipped': skipped, 'failed': failed}
    
    def is_authenticated(self) -> bool:
        """Check if SSO is authenticated"""
        return self.sso_client.is_authenticated()
    
    def authenticate(self) -> bool:
        """Authenticate with SSO"""
        try:
            return self.sso_client.authenticate()
        except SSOAuthenticationError as e:
            logger.error(f"SSO authentication failed: {e}")
            return False
    
    def logout(self) -> None:
        """Logout from SSO"""
        self.sso_client.logout()
        logger.info("Logged out from SSO")

# Convenience functions
def get_account_manager(sso_session_name: str = "default", region: str = "us-east-1",
                       account_file_path: Optional[str] = None) -> AccountManager:
    """Get an account manager instance"""
    return AccountManager(sso_session_name, region, account_file_path)

def discover_accounts_quick(sso_session_name: str = "default", region: str = "us-east-1") -> AccountCollection:
    """Quick account discovery"""
    manager = AccountManager(sso_session_name, region)
    return manager.discover_accounts()

def get_available_roles(account_id: str, sso_session_name: str = "default", region: str = "us-east-1") -> List[Role]:
    """Get available roles for an account"""
    manager = AccountManager(sso_session_name, region)
    return manager.discover_roles_for_account(account_id)