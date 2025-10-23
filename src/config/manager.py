"""
Configuration manager for MultiAWSTool
Handles reading, writing, and validating configuration files
"""

import configparser
import os
from pathlib import Path
from typing import Optional, Dict
import logging

from .schema import (
    DEFAULT_CONFIG, CONFIG_TEMPLATE, ConfigPaths,
    validate_execution_mode, validate_output_format, validate_stop_on_errors,
    expand_path
)

logger = logging.getLogger(__name__)

class ConfigurationError(Exception):
    """Raised when configuration operations fail"""

class ConfigManager:
    """Manages MultiAWSTool configuration files"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration manager
        
        Args:
            config_path: Optional custom path to config file
        """
        self.paths = ConfigPaths()
        if config_path:
            self.paths.config_file = Path(config_path).expanduser()
            self.paths.config_dir = self.paths.config_file.parent
        
        self._config = configparser.ConfigParser()
        self._config.read_dict(DEFAULT_CONFIG)
    
    def ensure_config_directory(self) -> None:
        """Ensure the configuration directory exists"""
        try:
            self.paths.config_dir.mkdir(parents=True, exist_ok=True)
            self.paths.sso_cache_dir.mkdir(parents=True, exist_ok=True)
            
            # Set appropriate permissions (readable only by owner)
            os.chmod(self.paths.config_dir, 0o700)
            os.chmod(self.paths.sso_cache_dir, 0o700)
            
            logger.debug(f"Configuration directory ensured: {self.paths.config_dir}")
        except OSError as e:
            raise ConfigurationError(f"Failed to create configuration directory: {e}")
    
    def config_exists(self) -> bool:
        """Check if configuration file exists"""
        return self.paths.config_file.exists()
    
    def load_config(self) -> None:
        """Load configuration from file"""
        if not self.config_exists():
            logger.info("Configuration file not found, using defaults")
            return
        
        try:
            self._config.read(self.paths.config_file)
            logger.debug(f"Configuration loaded from {self.paths.config_file}")
        except configparser.Error as e:
            raise ConfigurationError(f"Failed to parse configuration file: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to read configuration file: {e}")
    
    def save_config(self) -> None:
        """Save current configuration to file"""
        self.ensure_config_directory()
        
        try:
            with open(self.paths.config_file, 'w') as f:
                self._config.write(f)
            
            # Set appropriate permissions (readable only by owner)
            os.chmod(self.paths.config_file, 0o600)
            
            logger.info(f"Configuration saved to {self.paths.config_file}")
        except Exception as e:
            raise ConfigurationError(f"Failed to save configuration: {e}")
    
    def create_default_config(self) -> None:
        """Create a default configuration file with template"""
        self.ensure_config_directory()
        
        try:
            # Prepare template values
            template_values = {
                'prefix': DEFAULT_CONFIG['general']['prefix'],
                'sso_session': DEFAULT_CONFIG['general']['sso-session'],
                'account_file': DEFAULT_CONFIG['general']['account-file'],
                'region': DEFAULT_CONFIG['general']['region'],
                'pattern': DEFAULT_CONFIG['output']['pattern'],
                'format': DEFAULT_CONFIG['output']['format'],
                'path': DEFAULT_CONFIG['output']['path'],
                'mode': DEFAULT_CONFIG['execution']['mode'],
                'stop_on_errors': DEFAULT_CONFIG['execution']['stop-on-errors'],
                'allow_destructive_commands': DEFAULT_CONFIG['security']['allow-destructive-commands']
            }
            
            # Write template
            with open(self.paths.config_file, 'w') as f:
                f.write(CONFIG_TEMPLATE.format(**template_values))
            
            # Set appropriate permissions
            os.chmod(self.paths.config_file, 0o600)
            
            # Load the created config
            self.load_config()
            
            logger.info(f"Default configuration created at {self.paths.config_file}")
        except Exception as e:
            raise ConfigurationError(f"Failed to create default configuration: {e}")
    
    def get(self, section: str, key: str, fallback: Optional[str] = None) -> str:
        """Get a configuration value"""
        try:
            return self._config.get(section, key, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError):
            if fallback is not None:
                return fallback
            raise ConfigurationError(f"Configuration key not found: [{section}] {key}")
    
    def set(self, section: str, key: str, value: str) -> None:
        """Set a configuration value"""
        if not self._config.has_section(section):
            self._config.add_section(section)
        self._config.set(section, key, value)
    
    def get_bool(self, section: str, key: str, fallback: bool = False) -> bool:
        """Get a boolean configuration value"""
        try:
            return self._config.getboolean(section, key, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback
        except ValueError as e:
            raise ConfigurationError(f"Invalid boolean value for [{section}] {key}: {e}")
    
    def get_int(self, section: str, key: str, fallback: int = 0) -> int:
        """Get an integer configuration value"""
        try:
            return self._config.getint(section, key, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback
        except ValueError as e:
            raise ConfigurationError(f"Invalid integer value for [{section}] {key}: {e}")
    
    def validate_config(self) -> Dict[str, list]:
        """
        Validate current configuration
        
        Returns:
            Dict with 'errors' and 'warnings' lists
        """
        errors = []
        warnings = []
        
        # Validate execution mode
        mode = self.get('execution', 'mode', 'parallel')
        if not validate_execution_mode(mode):
            errors.append(f"Invalid execution mode: {mode}. Must be 'parallel' or 'sequential'")
        
        # Validate output format
        format_val = self.get('output', 'format', 'json')
        if not validate_output_format(format_val):
            errors.append(f"Invalid output format: {format_val}. Must be 'json', 'yaml', 'txt', or 'csv'")
        
        # Validate stop-on-errors
        stop_errors = self.get('execution', 'stop-on-errors', '5')
        if not validate_stop_on_errors(stop_errors):
            errors.append(f"Invalid stop-on-errors value: {stop_errors}. Must be a non-negative integer")
        
        # Validate paths
        account_file = expand_path(self.get('general', 'account-file', ''))
        if account_file.parent and not account_file.parent.exists():
            warnings.append(f"Account file directory does not exist: {account_file.parent}")
        
        output_path = expand_path(self.get('output', 'path', ''))
        if output_path and not output_path.exists():
            warnings.append(f"Output directory does not exist: {output_path}")
        
        return {'errors': errors, 'warnings': warnings}
    
    def get_expanded_path(self, section: str, key: str, fallback: str = '') -> Path:
        """Get a path value with user home and environment variable expansion"""
        path_str = self.get(section, key, fallback)
        return expand_path(path_str)
    
    def to_dict(self) -> Dict[str, Dict[str, str]]:
        """Convert configuration to dictionary"""
        result = {}
        for section_name in self._config.sections():
            result[section_name] = dict(self._config[section_name])
        return result
    
    def update_from_dict(self, config_dict: Dict[str, Dict[str, str]]) -> None:
        """Update configuration from dictionary"""
        for section_name, section_data in config_dict.items():
            if not self._config.has_section(section_name):
                self._config.add_section(section_name)
            for key, value in section_data.items():
                self._config.set(section_name, key, str(value))

# Convenience functions
def get_config_manager() -> ConfigManager:
    """Get a default configuration manager instance"""
    return ConfigManager()

def load_or_create_config() -> ConfigManager:
    """Load existing config or create default if none exists"""
    manager = ConfigManager()
    if manager.config_exists():
        manager.load_config()
    else:
        manager.create_default_config()
    return manager