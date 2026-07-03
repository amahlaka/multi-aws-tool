"""
Account data model for MultiAWSTool
Represents AWS accounts and their associated data
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum

class AccountStatus(Enum):
    """Account status enumeration"""
    ACTIVE = "active"
    DISABLED = "disabled"
    UNKNOWN = "unknown"

@dataclass
class Role:
    """AWS IAM Role information"""
    name: str
    arn: str
    description: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'name': self.name,
            'arn': self.arn,
            'description': self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Role':
        """Create Role from dictionary"""
        return cls(
            name=data['name'],
            arn=data['arn'],
            description=data.get('description')
        )

@dataclass
class Account:
    """AWS Account information and metadata"""
    id: str
    name: str
    status: AccountStatus = AccountStatus.ACTIVE
    roles: List[Role] = field(default_factory=list)
    profile_name: Optional[str] = None
    last_updated: datetime = field(default_factory=datetime.now)
    product_team: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        """Post-initialization validation and conversion"""
        # Ensure status is AccountStatus enum
        if isinstance(self.status, str):
            try:
                self.status = AccountStatus(self.status.lower())
            except ValueError:
                self.status = AccountStatus.UNKNOWN
        elif not isinstance(self.status, AccountStatus):
            self.status = AccountStatus.UNKNOWN
        
        # Ensure last_updated is datetime
        if isinstance(self.last_updated, str):
            try:
                self.last_updated = datetime.fromisoformat(self.last_updated)
            except ValueError:
                self.last_updated = datetime.now()
    
    def set_team(self, team_name: str) -> None:
        """Set the product team for this account"""
        self.product_team = team_name
        self.last_updated = datetime.now()
    
    def add_role(self, role: Role) -> None:
        """Add a role to this account"""
        # Check if role already exists (by name)
        existing_role_names = {r.name for r in self.roles}
        if role.name not in existing_role_names:
            self.roles.append(role)
            self.last_updated = datetime.now()
    
    def remove_role(self, role_name: str) -> bool:
        """Remove a role by name. Returns True if removed, False if not found"""
        for i, role in enumerate(self.roles):
            if role.name == role_name:
                del self.roles[i]
                self.last_updated = datetime.now()
                return True
        return False
    
    def get_role(self, role_name: str) -> Optional[Role]:
        """Get a role by name"""
        for role in self.roles:
            if role.name == role_name:
                return role
        return None
    
    def has_role(self, role_name: str) -> bool:
        """Check if account has a specific role"""
        return any(role.name == role_name for role in self.roles)
    
    def set_status(self, status: AccountStatus) -> None:
        """Set account status and update timestamp"""
        self.status = status
        self.last_updated = datetime.now()
    
    def is_active(self) -> bool:
        """Check if account is active"""
        return self.status == AccountStatus.ACTIVE
    
    def set_profile_name(self, profile_name: str) -> None:
        """Set the AWS profile name for this account"""
        self.profile_name = profile_name
        self.last_updated = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status.value,
            'roles': [role.to_dict() for role in self.roles],
            'profile_name': self.profile_name,
            'last_updated': self.last_updated.isoformat(),
            'product_team': self.product_team,
            'tags': self.tags
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Account':
        """Create Account from dictionary"""
        return cls(
            id=data['id'],
            name=data['name'],
            status=data.get('status', 'active'),
            roles=[Role.from_dict(role_data) for role_data in data.get('roles', [])],
            profile_name=data.get('profile_name'),
            last_updated=data.get('last_updated', datetime.now().isoformat()),
            product_team=data.get('product_team'),
            tags=data.get('tags', {})
        )
    
    def __str__(self) -> str:
        """String representation of the account"""
        return f"Account(id={self.id}, name={self.name}, status={self.status.value}, roles={len(self.roles)})"
    
    def __repr__(self) -> str:
        """Detailed representation of the account"""
        parts = [f"Account(id='{self.id}', name='{self.name}'"]
        
        if self.product_team:
            parts.append(f"product_team='{self.product_team}'")
        
        parts.extend([
            f"status={self.status}",
            f"roles={len(self.roles)}",
            f"profile_name='{self.profile_name}'",
            f"last_updated='{self.last_updated.isoformat()}'"
        ])
        
        return ", ".join(parts) + ")"

@dataclass
class AccountCollection:
    """Collection of AWS accounts with management utilities"""
    accounts: List[Account] = field(default_factory=list)
    last_discovery: Optional[datetime] = None
    
    def __post_init__(self):
        """Post-initialization"""
        if isinstance(self.last_discovery, str):
            try:
                self.last_discovery = datetime.fromisoformat(self.last_discovery)
            except ValueError:
                self.last_discovery = None
    
    def add_account(self, account: Account) -> None:
        """Add an account to the collection"""
        # Remove existing account with same ID if present
        self.remove_account(account.id)
        self.accounts.append(account)
    
    def remove_account(self, account_id: str) -> bool:
        """Remove an account by ID. Returns True if removed, False if not found"""
        for i, account in enumerate(self.accounts):
            if account.id == account_id:
                del self.accounts[i]
                return True
        return False
    
    def get_account(self, account_id: str) -> Optional[Account]:
        """Get an account by ID"""
        for account in self.accounts:
            if account.id == account_id:
                return account
        return None
    
    def get_accounts_by_status(self, status: AccountStatus) -> List[Account]:
        """Get all accounts with a specific status"""
        return [account for account in self.accounts if account.status == status]
    
    def get_accounts_by_product_team(self, product_team: str) -> List[Account]:
        """Get all accounts belonging to a specific product team"""
        return [account for account in self.accounts if account.product_team == product_team]
    
    def get_accounts_by_name(self, name: str) -> List[Account]:
        """Get all accounts with a specific name"""
        return [account for account in self.accounts if account.name == name]
    
    def get_accounts_by_tags(self, tags: Dict[str, str]) -> List['Account']:
        """Get all accounts that match all specified tags (key=value pairs)"""
        return [
            account for account in self.accounts
            if all(account.tags.get(k) == v for k, v in tags.items())
        ]
    
    def get_active_accounts(self) -> List[Account]:
        """Get all active accounts"""
        return self.get_accounts_by_status(AccountStatus.ACTIVE)
    
    def get_disabled_accounts(self) -> List[Account]:
        """Get all disabled accounts"""
        return self.get_accounts_by_status(AccountStatus.DISABLED)
    
    def disable_account(self, account_id: str) -> bool:
        """Disable an account by ID"""
        account = self.get_account(account_id)
        if account:
            account.set_status(AccountStatus.DISABLED)
            return True
        return False
    
    def enable_account(self, account_id: str) -> bool:
        """Enable an account by ID"""
        account = self.get_account(account_id)
        if account:
            account.set_status(AccountStatus.ACTIVE)
            return True
        return False
    
    def update_discovery_time(self) -> None:
        """Update the last discovery timestamp"""
        self.last_discovery = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'accounts': [account.to_dict() for account in self.accounts],
            'last_discovery': self.last_discovery.isoformat() if self.last_discovery else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AccountCollection':
        """Create AccountCollection from dictionary"""
        return cls(
            accounts=[Account.from_dict(acc_data) for acc_data in data.get('accounts', [])],
            last_discovery=data.get('last_discovery')
        )
    
    def __len__(self) -> int:
        """Return number of accounts"""
        return len(self.accounts)
    
    def __iter__(self):
        """Make collection iterable"""
        return iter(self.accounts)
    
    def __str__(self) -> str:
        """String representation"""
        active_count = len(self.get_active_accounts())
        disabled_count = len(self.get_disabled_accounts())
        return f"AccountCollection({len(self.accounts)} accounts: {active_count} active, {disabled_count} disabled)"