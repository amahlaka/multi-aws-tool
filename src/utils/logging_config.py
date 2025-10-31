"""
Logging configuration for MultiAWSTool
"""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

def setup_logging(log_level=logging.INFO, log_file=None, enable_console=True, 
                  max_size_mb=10, backup_count=5):
    """
    Setup logging configuration for the application
    
    Args:
        log_level: Logging level (default: INFO)
        log_file: Optional log file path
        enable_console: Enable console logging (default: True)
        max_size_mb: Maximum log file size in MB (default: 10)
        backup_count: Number of backup log files to keep (default: 5)
    """
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear any existing handlers
    root_logger.handlers.clear()
    
    # Console handler (if enabled)
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # File handler (if specified)
    if log_file:
        # Ensure log directory exists
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_size_mb * 1024 * 1024,  # Convert MB to bytes
            backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    return root_logger

def setup_logging_from_config(config) -> logging.Logger:
    """
    Setup logging configuration from a MultiAWSConfig instance
    
    Args:
        config: MultiAWSConfig instance with logging configuration
        
    Returns:
        Configured root logger
    """
    # Convert string log level to logging constant
    log_level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    
    log_level = log_level_map.get(config.logging.level.upper(), logging.INFO)
    log_file = config.get_expanded_log_file_path() if config.logging.file else None
    
    return setup_logging(
        log_level=log_level,
        log_file=str(log_file) if log_file else None,
        enable_console=config.logging.console,
        max_size_mb=config.logging.max_size,
        backup_count=config.logging.backup_count
    )

def get_logger(name):
    """Get a logger instance with the specified name"""
    return logging.getLogger(name)