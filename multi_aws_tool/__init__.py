"""
MultiAWSTool - Multi-AWS Account Management Tool
A CLI application for managing AWS operations across multiple accounts via AWS SSO.

This package can be used as a library to manage AWS accounts and SSO authentication
in other Python projects.
"""

__version__ = "0.1.1"
__author__ = "MultiAWSTool Team"
__description__ = "Multi AWS tool for managing operations across multiple AWS accounts via SSO"

# Expose key classes for library usage
from .aws.account_manager import AccountManager, AccountManagerError
from .aws.sso_client import SSOClient, SSOAuthenticationError
from .config.manager import ConfigManager, ConfigurationError
from .models.account import Account, AccountCollection, Role, AccountStatus
from .models.config import MultiAWSConfig
from .utils.account_data import AccountDataManager, AccountDataError

# Convenience imports for common use cases
__all__ = [
    # Main management classes
    'AccountManager',
    'SSOClient', 
    'ConfigManager',
    
    # Data models
    'Account',
    'AccountCollection', 
    'Role',
    'AccountStatus',
    'MultiAWSConfig',
    
    # Utility classes
    'AccountDataManager',
    
    # Exceptions
    'AccountManagerError',
    'SSOAuthenticationError',
    'ConfigurationError',
    'AccountDataError',
]