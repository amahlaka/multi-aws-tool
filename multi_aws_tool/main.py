#!/usr/bin/env python3
"""
MultiAWSTool - Multi-AWS Account Management Tool
CLI entry point for managing multiple AWS accounts through SSO
"""

import sys
import os

# Add the current package to the Python path if needed
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from cli.commands import cli

def main():
    """Main entry point for the multi-aws command"""
    cli()

if __name__ == '__main__':
    main()