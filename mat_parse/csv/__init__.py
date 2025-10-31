"""
CSV Module for MAT Parse
"""

from .csv import extract_csv_from_execution_summary
__version__ = "0.1.0"
__author__ = "MultiAWSTool Contributors"
__description__ = "CSV extractor for AWS MultiAWSTool execution summaries"

__all__ = [
    'extract_csv_from_execution_summary',
]
