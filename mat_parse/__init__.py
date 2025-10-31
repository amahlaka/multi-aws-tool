"""
MAT Parse - MultiAWSTool Output Parser

A collection of parsers and analyzers for MultiAWSTool (MAT) output files.
This module provides specialized tools for analyzing various AWS service outputs
collected through the MultiAWSTool.

Modules:
    iam: IAM credential report analysis and inactive user detection
"""

__version__ = "0.1.0"
__author__ = "MultiAWSTool Contributors"
__description__ = "Parser collection for AWS MultiAWSTool outputs"

# Import main classes for easier access
from .iam import IAMReportParser, IAMUser, ExecutionSummaryProcessor

__all__ = [
    'IAMReportParser',
    'IAMUser',
    'ExecutionSummaryProcessor',
]