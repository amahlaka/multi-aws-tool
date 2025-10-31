"""
MultiAWSTool Output Structure Module

This module provides importable classes and utilities for working with
MultiAWSTool command execution outputs. Use this in other tools to parse
and process MultiAWSTool result files.

Example usage:
    from multi_aws_tool.output import OutputParser, ExecutionSummary, AccountResult
    
    # Parse execution summary file
    parser = OutputParser()
    summary = parser.parse_execution_summary('execution_summary_20251031_120000.json')
    
    # Access results
    for result in summary.results:
        print(f"Account {result.account_id}: {result.status}")
    
    # Parse individual account output
    account_output = parser.parse_account_output('account-123456789012-command-20251031.json')
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

# Import existing models
try:
    from .models.result import CommandResult, ResultStatus, ExecutionSummary
    from .models.account import Account
except ImportError:
    # Fallback for when used as standalone module
    CommandResult = None
    ResultStatus = None
    ExecutionSummary = None
    Account = None


@dataclass
class AccountResult:
    """Individual account command execution result with enhanced metadata"""
    account_id: str
    account_name: Optional[str]
    profile_name: Optional[str]
    command: str
    status: str  # SUCCESS, ERROR, TIMEOUT
    output: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    execution_time: float = 0.0
    exit_code: Optional[int] = None
    output_file: Optional[str] = None  # Path to individual output file
    
    @classmethod
    def from_command_result(cls, result: Any, account_name: str = None, 
                          profile_name: str = None, output_file: str = None) -> 'AccountResult':
        """Create AccountResult from CommandResult"""
        return cls(
            account_id=result.account_id,
            account_name=account_name,
            profile_name=profile_name,
            command=result.command if isinstance(result.command, str) else ' '.join(result.command),
            status=result.status.value.upper() if ResultStatus and isinstance(result.status, ResultStatus) else str(result.status).upper(),
            output=result.output,
            error=result.error,
            timestamp=result.timestamp.isoformat() if isinstance(result.timestamp, datetime) else str(result.timestamp),
            execution_time=result.execution_time,
            exit_code=result.exit_code,
            output_file=output_file
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)
    
    def is_success(self) -> bool:
        """Check if execution was successful"""
        return self.status == 'SUCCESS'
    
    def has_output(self) -> bool:
        """Check if there is command output"""
        return bool(self.output and self.output.strip())
    
    def has_error(self) -> bool:
        """Check if there is an error"""
        return bool(self.error and self.error.strip())


@dataclass 
class MultiAWSExecutionSummary:
    """Complete execution summary with enhanced metadata"""
    execution_id: str
    command: str
    timestamp: str
    total_accounts: int
    successful_accounts: int
    failed_accounts: int
    timeout_accounts: int
    execution_mode: str  # parallel or sequential
    total_execution_time: float
    results: List[AccountResult] = field(default_factory=list)
    output_directory: Optional[str] = None
    config_used: Optional[Dict[str, Any]] = None
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage"""
        if self.total_accounts == 0:
            return 0.0
        return (self.successful_accounts / self.total_accounts) * 100
    
    def get_successful_results(self) -> List[AccountResult]:
        """Get only successful results"""
        return [r for r in self.results if r.is_success()]
    
    def get_failed_results(self) -> List[AccountResult]:
        """Get only failed results"""
        return [r for r in self.results if not r.is_success() and r.status != 'TIMEOUT']
    
    def get_timeout_results(self) -> List[AccountResult]:
        """Get only timeout results"""
        return [r for r in self.results if r.status == 'TIMEOUT']
    
    def get_results_by_account(self, account_id: str) -> Optional[AccountResult]:
        """Get result for specific account"""
        return next((r for r in self.results if r.account_id == account_id), None)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)


class OutputParser:
    """Parser for MultiAWSTool output files"""
    
    def __init__(self, output_directory: Optional[str] = None):
        """
        Initialize parser
        
        Args:
            output_directory: Default directory to look for output files
        """
        self.output_directory = Path(output_directory) if output_directory else None
    
    def parse_execution_summary(self, file_path: Union[str, Path]) -> MultiAWSExecutionSummary:
        """
        Parse execution summary JSON file
        
        Args:
            file_path: Path to execution summary file
            
        Returns:
            MultiAWSExecutionSummary object
            
        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If file is not valid JSON
            KeyError: If required fields are missing
        """
        file_path = Path(file_path).expanduser()
        if not file_path.is_absolute() and self.output_directory:
            file_path = self.output_directory / file_path
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Handle both list format (legacy) and dict format (new)
        if isinstance(data, list):
            # Legacy format - list of results
            results = [self._parse_result_dict(item) for item in data]
            
            # Calculate summary statistics
            successful = sum(1 for r in results if r.is_success())
            failed = sum(1 for r in results if not r.is_success() and r.status != 'TIMEOUT')
            timeout = sum(1 for r in results if r.status == 'TIMEOUT')
            
            summary = MultiAWSExecutionSummary(
                execution_id=file_path.stem,
                command=results[0].command if results else "",
                timestamp=results[0].timestamp if results else datetime.now().isoformat(),
                total_accounts=len(results),
                successful_accounts=successful,
                failed_accounts=failed,
                timeout_accounts=timeout,
                execution_mode="unknown",
                total_execution_time=sum(r.execution_time for r in results),
                results=results,
                output_directory=str(file_path.parent)
            )
        else:
            # New dict format
            results = [self._parse_result_dict(item) for item in data.get('results', [])]
            
            summary = MultiAWSExecutionSummary(
                execution_id=data.get('execution_id', file_path.stem),
                command=data.get('command', ''),
                timestamp=data.get('timestamp', datetime.now().isoformat()),
                total_accounts=data.get('total_accounts', len(results)),
                successful_accounts=data.get('successful_accounts', 0),
                failed_accounts=data.get('failed_accounts', 0),
                timeout_accounts=data.get('timeout_accounts', 0),
                execution_mode=data.get('execution_mode', 'unknown'),
                total_execution_time=data.get('total_execution_time', 0.0),
                results=results,
                output_directory=data.get('output_directory', str(file_path.parent)),
                config_used=data.get('config_used')
            )
        
        return summary
    
    def _parse_result_dict(self, data: Dict[str, Any]) -> AccountResult:
        """Parse individual result dictionary"""
        return AccountResult(
            account_id=data.get('account_id', ''),
            account_name=data.get('account_name'),
            profile_name=data.get('profile_name'),
            command=data.get('command', ''),
            status=str(data.get('status', 'ERROR')).upper(),
            output=data.get('output'),
            error=data.get('error'),
            timestamp=data.get('timestamp', datetime.now().isoformat()),
            execution_time=float(data.get('execution_time', 0.0)),
            exit_code=data.get('exit_code'),
            output_file=data.get('output_file')
        )
    
    def parse_account_output(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Parse individual account output file
        
        Args:
            file_path: Path to account output file
            
        Returns:
            Dictionary containing the parsed output
        """
        file_path = Path(file_path)
        if not file_path.is_absolute() and self.output_directory:
            file_path = self.output_directory / file_path
        
        with open(file_path, 'r') as f:
            if file_path.suffix.lower() == '.json':
                return json.load(f)
            else:
                return {'content': f.read()}
    
    def find_execution_summaries(self, pattern: str = "execution_summary_*.json") -> List[Path]:
        """
        Find execution summary files matching pattern
        
        Args:
            pattern: Glob pattern to match files
            
        Returns:
            List of Path objects for matching files
        """
        if not self.output_directory:
            raise ValueError("Output directory not set")
        
        return list(self.output_directory.glob(pattern))
    
    def find_account_outputs(self, account_id: str = None, 
                           command_pattern: str = None) -> List[Path]:
        """
        Find account output files
        
        Args:
            account_id: Filter by specific account ID
            command_pattern: Filter by command pattern
            
        Returns:
            List of Path objects for matching files
        """
        if not self.output_directory:
            raise ValueError("Output directory not set")
        
        patterns = []
        if account_id and command_pattern:
            patterns.append(f"*{account_id}*{command_pattern}*")
        elif account_id:
            patterns.append(f"*{account_id}*")
        elif command_pattern:
            patterns.append(f"*{command_pattern}*")
        else:
            patterns.append("*.json")
            patterns.append("*.txt")
            patterns.append("*.yaml")
            patterns.append("*.csv")
        
        files = []
        for pattern in patterns:
            files.extend(self.output_directory.glob(pattern))
        
        # Filter out execution summaries
        return [f for f in files if not f.name.startswith('execution_summary_')]


class OutputAnalyzer:
    """Analyzer for MultiAWSTool execution results"""
    
    def __init__(self, parser: OutputParser):
        self.parser = parser
    
    def analyze_execution(self, summary: MultiAWSExecutionSummary) -> Dict[str, Any]:
        """
        Analyze execution summary and provide insights
        
        Args:
            summary: Execution summary to analyze
            
        Returns:
            Dictionary with analysis results
        """
        analysis = {
            'overview': {
                'total_accounts': summary.total_accounts,
                'success_rate': summary.success_rate,
                'total_time': summary.total_execution_time,
                'avg_time_per_account': summary.total_execution_time / summary.total_accounts if summary.total_accounts > 0 else 0
            },
            'performance': {
                'fastest_account': None,
                'slowest_account': None,
                'avg_execution_time': 0,
                'execution_time_distribution': {}
            },
            'errors': {
                'error_patterns': {},
                'most_common_errors': [],
                'accounts_with_errors': []
            },
            'recommendations': []
        }
        
        if summary.results:
            # Performance analysis
            execution_times = [r.execution_time for r in summary.results]
            analysis['performance']['avg_execution_time'] = sum(execution_times) / len(execution_times)
            
            fastest = min(summary.results, key=lambda x: x.execution_time)
            slowest = max(summary.results, key=lambda x: x.execution_time)
            
            analysis['performance']['fastest_account'] = {
                'account_id': fastest.account_id,
                'time': fastest.execution_time
            }
            analysis['performance']['slowest_account'] = {
                'account_id': slowest.account_id,
                'time': slowest.execution_time
            }
            
            # Error analysis
            failed_results = summary.get_failed_results()
            error_messages = [r.error for r in failed_results if r.error]
            
            # Simple error pattern detection
            error_counts = {}
            for error in error_messages:
                # Extract key phrases from errors
                if 'AccessDenied' in error:
                    key = 'AccessDenied'
                elif 'Throttling' in error:
                    key = 'Throttling'
                elif 'timeout' in error.lower():
                    key = 'Timeout'
                else:
                    key = 'Other'
                
                error_counts[key] = error_counts.get(key, 0) + 1
            
            analysis['errors']['error_patterns'] = error_counts
            analysis['errors']['accounts_with_errors'] = [r.account_id for r in failed_results]
            
            # Recommendations
            if summary.success_rate < 50:
                analysis['recommendations'].append("Low success rate - check authentication and permissions")
            
            if summary.timeout_accounts > 0:
                analysis['recommendations'].append(f"{summary.timeout_accounts} accounts timed out - consider increasing timeout")
            
            if error_counts.get('Throttling', 0) > 0:
                analysis['recommendations'].append("Throttling detected - consider using sequential execution mode")
        
        return analysis
    
    def compare_executions(self, summaries: List[MultiAWSExecutionSummary]) -> Dict[str, Any]:
        """
        Compare multiple execution summaries
        
        Args:
            summaries: List of execution summaries to compare
            
        Returns:
            Dictionary with comparison results
        """
        if not summaries:
            return {}
        
        comparison = {
            'execution_count': len(summaries),
            'success_rate_trend': [s.success_rate for s in summaries],
            'performance_trend': [s.total_execution_time / s.total_accounts if s.total_accounts > 0 else 0 for s in summaries],
            'best_execution': None,
            'worst_execution': None,
            'average_success_rate': sum(s.success_rate for s in summaries) / len(summaries)
        }
        
        # Find best and worst executions
        best = max(summaries, key=lambda x: x.success_rate)
        worst = min(summaries, key=lambda x: x.success_rate)
        
        comparison['best_execution'] = {
            'execution_id': best.execution_id,
            'success_rate': best.success_rate,
            'timestamp': best.timestamp
        }
        
        comparison['worst_execution'] = {
            'execution_id': worst.execution_id,
            'success_rate': worst.success_rate,
            'timestamp': worst.timestamp
        }
        
        return comparison


# Convenience functions for quick access
def parse_execution_summary(file_path: Union[str, Path], 
                          output_directory: Optional[str] = None) -> MultiAWSExecutionSummary:
    """
    Quick function to parse execution summary
    
    Args:
        file_path: Path to execution summary file
        output_directory: Optional output directory
        
    Returns:
        MultiAWSExecutionSummary object
    """
    parser = OutputParser(output_directory)
    return parser.parse_execution_summary(file_path)


def analyze_execution_summary(file_path: Union[str, Path], 
                            output_directory: Optional[str] = None) -> Dict[str, Any]:
    """
    Quick function to analyze execution summary
    
    Args:
        file_path: Path to execution summary file
        output_directory: Optional output directory
        
    Returns:
        Analysis results dictionary
    """
    parser = OutputParser(output_directory)
    summary = parser.parse_execution_summary(file_path)
    analyzer = OutputAnalyzer(parser)
    return analyzer.analyze_execution(summary)


# Re-export commonly used classes and functions
__all__ = [
    'AccountResult',
    'MultiAWSExecutionSummary', 
    'OutputParser',
    'OutputAnalyzer',
    'parse_execution_summary',
    'analyze_execution_summary',
    'ResultStatus',
    'CommandResult'
]