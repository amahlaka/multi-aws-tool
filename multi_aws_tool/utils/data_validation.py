"""
Data validation utilities for MultiAWSTool
Provides validation functions for account data, roles, and command results
"""

import re
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import logging

from ..models.account import Account, Role, AccountCollection, AccountStatus
from ..models.result import CommandResult, ExecutionSummary, ResultStatus

class ValidationError(Exception):
    """Raised when data model validation fails"""

class ValidationResult:
    """Result of a validation operation"""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def add_error(self, error: str) -> None:
        """Add a validation error"""
        self.errors.append(error)
    
    def add_warning(self, warning: str) -> None:
        """Add a validation warning"""
        self.warnings.append(warning)
    
    def is_valid(self) -> bool:
        """Check if validation passed (no errors)"""
        return len(self.errors) == 0
    
    def has_warnings(self) -> bool:
        """Check if there are warnings"""
        return len(self.warnings) > 0
    
    def get_summary(self) -> str:
        """Get a summary of validation results"""
        if self.is_valid() and not self.has_warnings():
            return "Validation passed"
        
        parts = []
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s)")
        
        return f"Validation failed: {', '.join(parts)}"

def validate_aws_account_id(account_id: str) -> bool:
    """Validate AWS account ID format (12-digit number)"""
    if not account_id:
        return False
    return bool(re.match(r'^\d{12}$', account_id.strip()))

def validate_iam_role_name(role_name: str) -> bool:
    """Validate AWS IAM role name format"""
    if not role_name:
        return False
    # AWS IAM role names: 1-64 chars, alphanumeric plus + = , . @ - _
    return bool(re.match(r'^[a-zA-Z0-9+=,.@_-]{1,64}$', role_name.strip()))

def validate_iam_role_arn(role_arn: str) -> bool:
    """Validate AWS IAM role ARN format"""
    if not role_arn:
        return False
    # Basic ARN format: arn:partition:service:region:account:resource
    arn_pattern = r'^arn:[^:]+:iam::[0-9]{12}:role/[a-zA-Z0-9+=,.@_/-]+$'
    return bool(re.match(arn_pattern, role_arn.strip()))

def validate_profile_name(profile_name: str) -> bool:
    """Validate AWS profile name format"""
    if not profile_name:
        return False
    # AWS profile names: alphanumeric, hyphens, underscores
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', profile_name.strip()))

def validate_role(role: Role) -> ValidationResult:
    """
    Validate a Role object
    
    Args:
        role: Role to validate
        
    Returns:
        ValidationResult with errors and warnings
    """
    result = ValidationResult()
    
    # Validate role name
    if not role.name:
        result.add_error("Role name is required")
    elif not validate_iam_role_name(role.name):
        result.add_error(f"Invalid role name format: '{role.name}'")
    
    # Validate role ARN
    if not role.arn:
        result.add_error("Role ARN is required")
    elif not validate_iam_role_arn(role.arn):
        result.add_error(f"Invalid role ARN format: '{role.arn}'")
    
    # Check ARN consistency
    if role.name and role.arn and validate_iam_role_arn(role.arn):
        # Extract role name from ARN and compare
        try:
            arn_role_name = role.arn.split('/')[-1]
            if arn_role_name != role.name:
                result.add_warning(f"Role name '{role.name}' doesn't match ARN role name '{arn_role_name}'")
        except (IndexError, AttributeError):
            pass
    
    # Validate description length
    if role.description and len(role.description) > 1000:
        result.add_warning("Role description is very long (>1000 characters)")
    
    return result

def validate_account(account: Account) -> ValidationResult:
    """
    Validate an Account object
    
    Args:
        account: Account to validate
        
    Returns:
        ValidationResult with errors and warnings
    """
    result = ValidationResult()
    
    # Validate account ID
    if not account.id:
        result.add_error("Account ID is required")
    elif not validate_aws_account_id(account.id):
        result.add_error(f"Invalid account ID format: '{account.id}'")
    
    # Validate account name
    if not account.name:
        result.add_error("Account name is required")
    elif len(account.name.strip()) < 1:
        result.add_error("Account name cannot be empty")
    elif len(account.name) > 256:
        result.add_warning("Account name is very long (>256 characters)")
    
    # Validate status
    if not isinstance(account.status, AccountStatus):
        result.add_error(f"Invalid account status type: {type(account.status)}")
    
    # Validate profile name if set
    if account.profile_name and not validate_profile_name(account.profile_name):
        result.add_error(f"Invalid profile name format: '{account.profile_name}'")
    
    # Validate last_updated timestamp
    if not isinstance(account.last_updated, datetime):
        result.add_error(f"Invalid last_updated type: {type(account.last_updated)}")
    
    # Validate roles
    role_names = set()
    for i, role in enumerate(account.roles):
        if not isinstance(role, Role):
            result.add_error(f"Role {i} is not a Role object")
            continue
        
        # Validate individual role
        role_validation = validate_role(role)
        for error in role_validation.errors:
            result.add_error(f"Role '{role.name}': {error}")
        for warning in role_validation.warnings:
            result.add_warning(f"Role '{role.name}': {warning}")
        
        # Check for duplicate role names
        if role.name in role_names:
            result.add_error(f"Duplicate role name: '{role.name}'")
        role_names.add(role.name)
    
    # Check role count
    if len(account.roles) > 100:
        result.add_warning(f"Account has many roles ({len(account.roles)}), this may impact performance")
    
    return result

def validate_account_collection(collection: AccountCollection) -> ValidationResult:
    """
    Validate an AccountCollection object
    
    Args:
        collection: AccountCollection to validate
        
    Returns:
        ValidationResult with errors and warnings
    """
    result = ValidationResult()
    
    # Validate collection structure
    if not isinstance(collection.accounts, list):
        result.add_error(f"Accounts must be a list, got {type(collection.accounts)}")
        return result
    
    # Validate last_discovery timestamp
    if collection.last_discovery and not isinstance(collection.last_discovery, datetime):
        result.add_error(f"Invalid last_discovery type: {type(collection.last_discovery)}")
    
    # Validate individual accounts
    account_ids = set()
    for i, account in enumerate(collection.accounts):
        if not isinstance(account, Account):
            result.add_error(f"Account {i} is not an Account object")
            continue
        
        # Validate individual account
        account_validation = validate_account(account)
        for error in account_validation.errors:
            result.add_error(f"Account '{account.id}': {error}")
        for warning in account_validation.warnings:
            result.add_warning(f"Account '{account.id}': {warning}")
        
        # Check for duplicate account IDs
        if account.id in account_ids:
            result.add_error(f"Duplicate account ID: '{account.id}'")
        account_ids.add(account.id)
    
    # Check collection size
    if len(collection.accounts) > 1000:
        result.add_warning(f"Large account collection ({len(collection.accounts)} accounts)")
    
    return result

def validate_command_result(result_obj: CommandResult) -> ValidationResult:
    """
    Validate a CommandResult object
    
    Args:
        result_obj: CommandResult to validate
        
    Returns:
        ValidationResult with errors and warnings
    """
    result = ValidationResult()
    
    # Validate account ID
    if not result_obj.account_id:
        result.add_error("Account ID is required")
    elif not validate_aws_account_id(result_obj.account_id):
        result.add_error(f"Invalid account ID format: '{result_obj.account_id}'")
    
    # Validate command
    if not result_obj.command:
        result.add_error("Command is required")
    elif len(result_obj.command.strip()) < 1:
        result.add_error("Command cannot be empty")
    
    # Validate status
    if not isinstance(result_obj.status, ResultStatus):
        result.add_error(f"Invalid status type: {type(result_obj.status)}")
    
    # Validate timestamp
    if not isinstance(result_obj.timestamp, datetime):
        result.add_error(f"Invalid timestamp type: {type(result_obj.timestamp)}")
    
    # Validate execution time
    if result_obj.execution_time < 0:
        result.add_error("Execution time cannot be negative")
    elif result_obj.execution_time > 3600:  # 1 hour
        result.add_warning(f"Very long execution time: {result_obj.execution_time}s")
    
    # Validate exit code
    if result_obj.exit_code is not None:
        if not isinstance(result_obj.exit_code, int):
            result.add_error(f"Exit code must be an integer, got {type(result_obj.exit_code)}")
        elif result_obj.exit_code < 0 or result_obj.exit_code > 255:
            result.add_warning(f"Unusual exit code: {result_obj.exit_code}")
    
    # Validate output/error consistency
    if result_obj.status == ResultStatus.SUCCESS:
        if not result_obj.output and not result_obj.has_output():
            result.add_warning("Successful result has no output")
        if result_obj.error:
            result.add_warning("Successful result has error message")
    elif result_obj.status == ResultStatus.ERROR:
        if not result_obj.error and not result_obj.has_error():
            result.add_warning("Error result has no error message")
    
    return result

def validate_execution_summary(summary: ExecutionSummary) -> ValidationResult:
    """
    Validate an ExecutionSummary object
    
    Args:
        summary: ExecutionSummary to validate
        
    Returns:
        ValidationResult with errors and warnings
    """
    result = ValidationResult()
    
    # Validate command
    if not summary.command:
        result.add_error("Command is required")
    
    # Validate timestamps
    if not isinstance(summary.started_at, datetime):
        result.add_error(f"Invalid started_at type: {type(summary.started_at)}")
    
    if summary.completed_at and not isinstance(summary.completed_at, datetime):
        result.add_error(f"Invalid completed_at type: {type(summary.completed_at)}")
    
    # Validate timing consistency
    if summary.completed_at and summary.started_at:
        if summary.completed_at < summary.started_at:
            result.add_error("Completed time is before started time")
    
    # Validate execution time
    if summary.total_execution_time < 0:
        result.add_error("Total execution time cannot be negative")
    
    # Validate results
    if not isinstance(summary.results, list):
        result.add_error(f"Results must be a list, got {type(summary.results)}")
        return result
    
    # Validate individual results
    for i, cmd_result in enumerate(summary.results):
        if not isinstance(cmd_result, CommandResult):
            result.add_error(f"Result {i} is not a CommandResult object")
            continue
        
        result_validation = validate_command_result(cmd_result)
        for error in result_validation.errors:
            result.add_error(f"Result {i}: {error}")
        for warning in result_validation.warnings:
            result.add_warning(f"Result {i}: {warning}")
    
    return result

# Convenience functions
def is_valid_account(account: Account) -> bool:
    """Check if an account is valid (no validation errors)"""
    return validate_account(account).is_valid()

def is_valid_role(role: Role) -> bool:
    """Check if a role is valid (no validation errors)"""
    return validate_role(role).is_valid()

def is_valid_command_result(result: CommandResult) -> bool:
    """Check if a command result is valid (no validation errors)"""
    return validate_command_result(result).is_valid()

def validate_and_raise(obj: Any, validator_func) -> None:
    """
    Validate an object and raise ValidationError if invalid
    
    Args:
        obj: Object to validate
        validator_func: Validation function to use
        
    Raises:
        ValidationError: If validation fails
    """
    validation_result = validator_func(obj)
    if not validation_result.is_valid():
        error_msg = f"Validation failed: {'; '.join(validation_result.errors)}"
        raise ValidationError(error_msg)