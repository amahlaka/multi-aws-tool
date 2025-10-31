"""
Configuration data models for MultiAWSTool
Provides type-safe configuration handling
"""

from dataclasses import dataclass
from pathlib import Path

@dataclass
class GeneralConfig:
    """General configuration settings"""
    prefix: str = "multi-aws"
    sso_session: str = "default"
    account_file: str = "~/.multi-aws/accounts.json"
    region: str = "us-east-1"

@dataclass
class OutputConfig:
    """Output configuration settings"""
    pattern: str = "!A-!c-!d"  # !A=account name, !c=command, !d=date
    format: str = "json"
    path: str = "~/.multi-aws/outputs/"

@dataclass
class ExecutionConfig:
    """Execution configuration settings"""
    mode: str = "parallel"  # parallel or sequential
    stop_on_errors: int = 5  # 0 for never stop

@dataclass
class SecurityConfig:
    """Security configuration settings"""
    allow_destructive_commands: bool = False

@dataclass
class LoggingConfig:
    """Logging configuration settings"""
    level: str = "INFO"
    file: str = "~/.multi-aws/logs/multi-aws.log"
    console: bool = True
    max_size: int = 10  # MB
    backup_count: int = 5

@dataclass
class MultiAWSConfig:
    """Complete MultiAWSTool configuration"""
    general: GeneralConfig
    output: OutputConfig
    execution: ExecutionConfig
    security: SecurityConfig
    logging: LoggingConfig
    
    @classmethod
    def default(cls) -> 'MultiAWSConfig':
        """Create a configuration with default values"""
        return cls(
            general=GeneralConfig(),
            output=OutputConfig(),
            execution=ExecutionConfig(),
            security=SecurityConfig(),
            logging=LoggingConfig()
        )
    
    @classmethod
    def from_config_manager(cls, config_manager) -> 'MultiAWSConfig':
        """Create configuration from ConfigManager instance"""
        return cls(
            general=GeneralConfig(
                prefix=config_manager.get('general', 'prefix', 'multi-aws'),
                sso_session=config_manager.get('general', 'sso-session', 'default'),
                account_file=config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json'),
                region=config_manager.get('general', 'region', 'us-east-1')
            ),
            output=OutputConfig(
                pattern=config_manager.get('output', 'pattern', '%A-%c-%d'),
                format=config_manager.get('output', 'format', 'json'),
                path=config_manager.get('output', 'path', '~/.multi-aws/outputs/')
            ),
            execution=ExecutionConfig(
                mode=config_manager.get('execution', 'mode', 'parallel'),
                stop_on_errors=config_manager.get_int('execution', 'stop-on-errors', 5)
            ),
            security=SecurityConfig(
                allow_destructive_commands=config_manager.get_bool('security', 'allow-destructive-commands', False)
            ),
            logging=LoggingConfig(
                level=config_manager.get('logging', 'level', 'INFO'),
                file=config_manager.get('logging', 'file', '~/.multi-aws/logs/multi-aws.log'),
                console=config_manager.get_bool('logging', 'console', True),
                max_size=config_manager.get_int('logging', 'max-size', 10),
                backup_count=config_manager.get_int('logging', 'backup-count', 5)
            )
        )
    
    def to_config_manager(self, config_manager) -> None:
        """Apply this configuration to a ConfigManager instance"""
        # General settings
        config_manager.set('general', 'prefix', self.general.prefix)
        config_manager.set('general', 'sso-session', self.general.sso_session)
        config_manager.set('general', 'account-file', self.general.account_file)
        config_manager.set('general', 'region', self.general.region)
        
        # Output settings
        config_manager.set('output', 'pattern', self.output.pattern)
        config_manager.set('output', 'format', self.output.format)
        config_manager.set('output', 'path', self.output.path)
        
        # Execution settings
        config_manager.set('execution', 'mode', self.execution.mode)
        config_manager.set('execution', 'stop-on-errors', str(self.execution.stop_on_errors))
        
        # Security settings
        config_manager.set('security', 'allow-destructive-commands', str(self.security.allow_destructive_commands).lower())
        
        # Logging settings
        config_manager.set('logging', 'level', self.logging.level)
        config_manager.set('logging', 'file', self.logging.file)
        config_manager.set('logging', 'console', str(self.logging.console).lower())
        config_manager.set('logging', 'max-size', str(self.logging.max_size))
        config_manager.set('logging', 'backup-count', str(self.logging.backup_count))
    
    def get_expanded_account_file_path(self) -> Path:
        """Get the account file path with expansions"""
        return Path(self.general.account_file).expanduser().resolve()
    
    def get_expanded_output_path(self) -> Path:
        """Get the output path with expansions"""
        return Path(self.output.path).expanduser().resolve()
    
    def get_expanded_log_file_path(self) -> Path:
        """Get the log file path with expansions"""
        if not self.logging.file:
            return None
        return Path(self.logging.file).expanduser().resolve()
    
    def is_parallel_execution(self) -> bool:
        """Check if parallel execution is enabled"""
        return self.execution.mode.lower() == 'parallel'
    
    def should_stop_on_errors(self) -> bool:
        """Check if execution should stop on errors"""
        return self.execution.stop_on_errors > 0
    
    def validate(self) -> list:
        """
        Validate the configuration
        
        Returns:
            List of validation error messages
        """
        errors = []
        
        # Validate execution mode
        if self.execution.mode.lower() not in ['parallel', 'sequential']:
            errors.append(f"Invalid execution mode: {self.execution.mode}. Must be 'parallel' or 'sequential'")
        
        # Validate output format
        if self.output.format.lower() not in ['json', 'yaml', 'txt', 'csv']:
            errors.append(f"Invalid output format: {self.output.format}. Must be 'json', 'yaml', 'txt', or 'csv'")
        
        # Validate stop-on-errors
        if self.execution.stop_on_errors < 0:
            errors.append(f"Invalid stop-on-errors value: {self.execution.stop_on_errors}. Must be >= 0")
        
        # Validate prefix (basic check)
        if not self.general.prefix or not self.general.prefix.strip():
            errors.append("Prefix cannot be empty")
        
        # Validate SSO session name
        if not self.general.sso_session or not self.general.sso_session.strip():
            errors.append("SSO session name cannot be empty")
        
        return errors