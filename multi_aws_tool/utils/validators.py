"""
Input validation utilities for MultiAWSTool
"""

import re
from pathlib import Path
from typing import List

def validate_aws_account_id(account_id: str) -> bool:
    """
    Validate AWS account ID format
    
    Args:
        account_id: Account ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not account_id:
        return False
    
    # AWS account IDs are 12-digit numbers
    return bool(re.match(r'^\d{12}$', account_id.strip()))

def validate_aws_region(region: str) -> bool:
    """
    Validate AWS region format
    
    Args:
        region: Region name to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not region:
        return False
    
    # Basic AWS region format validation
    return bool(re.match(r'^[a-z]{2}-[a-z]+-\d+$', region.strip()))

def validate_profile_prefix(prefix: str) -> bool:
    """
    Validate AWS profile prefix
    
    Args:
        prefix: Prefix to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not prefix:
        return False
    
    # AWS profile names can contain letters, numbers, hyphens, and underscores
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', prefix.strip()))

def validate_sso_session_name(session_name: str) -> bool:
    """
    Validate SSO session name
    
    Args:
        session_name: Session name to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not session_name:
        return False
    
    # SSO session names should be valid identifiers
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', session_name.strip()))

def validate_file_path(file_path: str, must_exist: bool = False) -> bool:
    """
    Validate file path
    
    Args:
        file_path: Path to validate
        must_exist: Whether the file must already exist
        
    Returns:
        True if valid, False otherwise
    """
    if not file_path:
        return False
    
    try:
        path = Path(file_path).expanduser()
        
        if must_exist:
            return path.exists() and path.is_file()
        else:
            # Check if parent directory exists or can be created
            return path.parent.exists() or path.parent == path  # Root directory
    except (OSError, ValueError):
        return False

def validate_directory_path(dir_path: str, must_exist: bool = False) -> bool:
    """
    Validate directory path
    
    Args:
        dir_path: Directory path to validate
        must_exist: Whether the directory must already exist
        
    Returns:
        True if valid, False otherwise
    """
    if not dir_path:
        return False
    
    try:
        path = Path(dir_path).expanduser()
        
        if must_exist:
            return path.exists() and path.is_dir()
        else:
            # Check if path is valid and can be created
            return True  # Most paths can be created if valid
    except (OSError, ValueError):
        return False

def validate_output_pattern(pattern: str) -> bool:
    """
    Validate output filename pattern
    
    Args:
        pattern: Pattern to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not pattern:
        return False
    
    # Check for valid placeholders and no invalid characters
    valid_placeholders = {'!a', '!A', '!c', '!d', '!t', '!s'}
    
    # Find all ! placeholders
    placeholders = re.findall(r'![a-zA-Z]', pattern)
    
    # Check if all placeholders are valid
    for placeholder in placeholders:
        if placeholder not in valid_placeholders:
            return False
    
    # Check for invalid filename characters (basic check)
    invalid_chars = ['<', '>', ':', '"', '|', '?', '*']
    for char in invalid_chars:
        if char in pattern:
            return False
    
    return True

def parse_account_list(accounts_input: str) -> List[str]:
    """
    Parse account list from comma-separated string or file
    
    Args:
        accounts_input: Comma-separated account IDs or file path
        
    Returns:
        List of account IDs
    """
    accounts = []
    
    # Check if it's a file path
    if accounts_input.strip().endswith('.txt') or accounts_input.strip().endswith('.json'):
        try:
            file_path = Path(accounts_input.strip()).expanduser()
            if file_path.exists():
                content = file_path.read_text(encoding='utf-8').strip()
                if content:
                    # Try to parse as comma-separated values first
                    accounts = [acc.strip() for acc in content.replace('\n', ',').split(',') if acc.strip()]
        except (OSError, ValueError):
            pass
    
    # If not a file or file parsing failed, treat as comma-separated
    if not accounts:
        accounts = [acc.strip() for acc in accounts_input.split(',') if acc.strip()]
    
    # Validate account IDs
    valid_accounts = []
    for account in accounts:
        if validate_aws_account_id(account):
            valid_accounts.append(account)
    
    return valid_accounts

def validate_role_name(role_name: str) -> bool:
    """
    Validate AWS IAM role name
    
    Args:
        role_name: Role name to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not role_name:
        return False
    
    # AWS IAM role names can contain letters, numbers, and some special characters
    return bool(re.match(r'^[a-zA-Z0-9+=,.@_-]+$', role_name.strip()))

def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by removing invalid characters
    
    Args:
        filename: Filename to sanitize
        
    Returns:
        Sanitized filename
    """
    # Replace invalid characters with underscores
    invalid_chars = ['<', '>', ':', '"', '|', '?', '*', '/', '\\']
    sanitized = filename
    for char in invalid_chars:
        sanitized = sanitized.replace(char, '_')
    
    # Remove multiple consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    
    return sanitized or 'unnamed'