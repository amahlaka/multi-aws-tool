"""
MultiAWSTool - Multi-AWS Account Management Tool
A CLI application for managing AWS operations across multiple accounts via AWS SSO.

This package can be used as a library to manage AWS accounts and SSO authentication
in other Python projects.
"""

__version__ = "0.1.2"
__author__ = "MultiAWSTool Team"
__description__ = "Multi AWS tool for managing operations across multiple AWS accounts via SSO"

# Expose key classes for library usage
from .aws.account_manager import AccountManager, AccountManagerError
from .aws.sso_client import SSOClient, SSOAuthenticationError
from .config.manager import ConfigManager, ConfigurationError
from .models.account import Account, AccountCollection, Role, AccountStatus
from .models.config import MultiAWSConfig
from .models.result import CommandResult, ResultStatus, ExecutionSummary
from .utils.account_data import AccountDataManager, AccountDataError

# Output parsing and analysis
from .output import (
    AccountResult, 
    MultiAWSExecutionSummary,
    OutputParser,
    OutputAnalyzer,
    parse_execution_summary,
    analyze_execution_summary
)

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
    'CommandResult',
    'ResultStatus',
    'ExecutionSummary',
    
    # Output parsing and analysis
    'AccountResult',
    'MultiAWSExecutionSummary',
    'OutputParser',
    'OutputAnalyzer',
    'parse_execution_summary',
    'analyze_execution_summary',
    
    # Utility classes
    'AccountDataManager',
    
    # Exceptions
    'AccountManagerError',
    'SSOAuthenticationError',
    'ConfigurationError',
    'AccountDataError',
]