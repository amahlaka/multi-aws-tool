#!/usr/bin/env python3
"""
MultiAWSTool - Multi-AWS Account Management Tool
CLI entry point for managing multiple AWS accounts through SSO
"""

import sys
import os

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.cli.commands import cli

if __name__ == '__main__':
    cli()