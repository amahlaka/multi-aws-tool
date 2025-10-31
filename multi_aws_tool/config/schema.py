"""
Configuration schema for MultiAWSTool
Defines the structure and defaults for the config.ini file
"""

from dataclasses import dataclass, field
from pathlib import Path
import os

# Default configuration values
DEFAULT_CONFIG = {
    'general': {
        'prefix': 'multi-aws',
        'sso-session': 'default',
        'account-file': '~/.multi-aws/accounts.json',
        'region': 'us-east-1'
    },
    'output': {
        'pattern': '!A-!c-!d',  # !A=account name, !c=command, !d=date
        'format': 'json',
        'path': '~/.multi-aws/outputs/'
    },
    'execution': {
        'mode': 'parallel',  # parallel or sequential
        'stop-on-errors': '5'  # 0 for never stop
    },
    'security': {
        'allow-destructive-commands': 'false'  # boolean stored as string
    },
    'logging': {
        'level': 'INFO',  # DEBUG, INFO, WARNING, ERROR, CRITICAL
        'file': '~/.multi-aws/logs/multi-aws.log',  # Log file path
        'console': 'true',  # Enable console logging
        'max-size': '10',  # Max log file size in MB
        'backup-count': '5'  # Number of backup log files to keep
    }
}

# Configuration file template
CONFIG_TEMPLATE = """# MultiAWSTool Configuration File
# Generated automatically - modify as needed

[general]
# Prefix for AWS profile names
prefix = {prefix}

# AWS SSO session name (must exist in ~/.aws/config)
sso-session = {sso_session}

# Path to JSON file storing account and role information
account-file = {account_file}

# Default AWS region
region = {region}

[output]
# Output filename pattern
# !a=account_id, !A=account_name, !c=command, !d=date, !t=time, !s=timestamp
pattern = {pattern}

# Output file format (json, yaml, txt)
format = {format}

# Directory to save output files
path = {path}

[execution]
# Execution mode: parallel or sequential
mode = {mode}

# Stop execution after this many errors (0 = never stop)
stop-on-errors = {stop_on_errors}

[security]
# Allow destructive commands (create, delete, modify operations)
# Set to true to enable all AWS CLI commands
allow-destructive-commands = {allow_destructive_commands}

[logging]
# Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
level = {level}

# Log file path (use empty string to disable file logging)
file = {file}

# Enable console logging (true/false)
console = {console}

# Maximum log file size in MB
max-size = {max_size}

# Number of backup log files to keep
backup-count = {backup_count}
"""

# Read-only commands that are always allowed
READ_ONLY_COMMANDS = {
    'describe', 'list', 'get', 'show', 'explain', 'wait',
    'help', 'validate', 'check', 'test', 'scan', 'search',
    'head', 'tail', 'cat', 'ls', 'query', 'count'
}

# Destructive command patterns (require allow-destructive-commands = true)
DESTRUCTIVE_COMMANDS = {
    'create', 'delete', 'remove', 'update', 'modify', 'put',
    'patch', 'post', 'start', 'stop', 'restart', 'terminate',
    'attach', 'detach', 'associate', 'disassociate', 'tag',
    'untag', 'enable', 'disable', 'activate', 'deactivate',
    'register', 'deregister', 'import', 'export', 'copy',
    'move', 'replace', 'reset', 'reboot', 'launch', 'run'
}

@dataclass
class ConfigPaths:
    """Paths used by the configuration system"""
    config_dir: Path = field(default_factory=lambda: Path.home() / '.multi-aws')
    config_file: Path = field(default_factory=lambda: Path.home() / '.multi-aws' / 'config.ini')
    sso_cache_dir: Path = field(default_factory=lambda: Path.home() / '.multi-aws' / 'sso-cache')
    
    def __post_init__(self):
        """Ensure all paths are Path objects"""
        self.config_dir = Path(self.config_dir).expanduser()
        self.config_file = Path(self.config_file).expanduser()
        self.sso_cache_dir = Path(self.sso_cache_dir).expanduser()

def get_default_account_file_path() -> str:
    """Get the default path for the account file"""
    return str(Path.home() / '.multi-aws' / 'accounts.json')

def get_default_output_path() -> str:
    """Get the default path for output files"""
    return str(Path.home() / '.multi-aws' / 'outputs')

def expand_path(path_str: str) -> Path:
    """Expand user home and environment variables in path"""
    return Path(os.path.expanduser(os.path.expandvars(path_str)))

def validate_execution_mode(mode: str) -> bool:
    """Validate execution mode value"""
    return mode.lower() in ['parallel', 'sequential']

def validate_output_format(format_str: str) -> bool:
    """Validate output format value"""
    return format_str.lower() in ['json', 'yaml', 'txt', 'csv']

def validate_stop_on_errors(value: str) -> bool:
    """Validate stop-on-errors value"""
    try:
        int_val = int(value)
        return int_val >= 0
    except ValueError:
        return False

def validate_log_level(level: str) -> bool:
    """Validate logging level value"""
    return level.upper() in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

def validate_log_max_size(value: str) -> bool:
    """Validate log max size value"""
    try:
        int_val = int(value)
        return int_val > 0
    except ValueError:
        return False

def validate_log_backup_count(value: str) -> bool:
    """Validate log backup count value"""
    try:
        int_val = int(value)
        return int_val >= 0
    except ValueError:
        return False

def is_destructive_command(command: str) -> bool:
    """Check if a command is considered destructive"""
    if not command:
        return False
    
    # Split command and check first word (the actual AWS service command)
    command_parts = command.strip().split()
    if not command_parts:
        return False
    
    # Check the second part (action) if it exists
    if len(command_parts) > 1:
        action = command_parts[1].lower()
        
        # Check against destructive patterns
        for destructive_pattern in DESTRUCTIVE_COMMANDS:
            if destructive_pattern in action:
                return True
        
        # Check against read-only patterns
        for readonly_pattern in READ_ONLY_COMMANDS:
            if readonly_pattern in action:
                return False
    
    # Default to safe (destructive) if we can't determine
    return True