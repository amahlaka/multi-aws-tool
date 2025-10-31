"""
IAM Parser Module for MultiAWSTool

This module provides tools for analyzing AWS IAM credential reports
and identifying inactive users with valid credentials.
"""

__version__ = "0.1.0"
__author__ = "MultiAWSTool Contributors"
__description__ = "Parser for AWS IAM related MAT outputs"

from .iamparse import IAMReportParser, IAMUser, ExecutionSummaryProcessor, main as iam_main

__all__ = [
    'IAMReportParser',
    'IAMUser',
    'ExecutionSummaryProcessor',
    'iam_main',
]