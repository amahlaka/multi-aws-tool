"""
Result data model for MultiAWSTool
Represents command execution results across AWS accounts
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum

class ResultStatus(Enum):
    """Command execution result status"""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PENDING = "pending"

@dataclass
class CommandResult:
    """Result of a command execution on a specific account"""
    account_id: str
    command: str
    status: ResultStatus
    team: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    execution_time: float = 0.0  # in seconds
    exit_code: Optional[int] = None
    
    def __post_init__(self):
        """Post-initialization validation and conversion"""
        # Ensure status is ResultStatus enum
        if isinstance(self.status, str):
            try:
                self.status = ResultStatus(self.status.lower())
            except ValueError:
                self.status = ResultStatus.ERROR
        elif not isinstance(self.status, ResultStatus):
            self.status = ResultStatus.ERROR
        
        # Ensure timestamp is datetime
        if isinstance(self.timestamp, str):
            try:
                self.timestamp = datetime.fromisoformat(self.timestamp)
            except ValueError:
                self.timestamp = datetime.now()
    
    def is_success(self) -> bool:
        """Check if the command execution was successful"""
        return self.status == ResultStatus.SUCCESS
    
    def is_error(self) -> bool:
        """Check if the command execution failed"""
        return self.status == ResultStatus.ERROR
    
    def has_output(self) -> bool:
        """Check if the result has output"""
        return self.output is not None and len(self.output.strip()) > 0
    
    def has_error(self) -> bool:
        """Check if the result has an error message"""
        return self.error is not None and len(self.error.strip()) > 0
    
    def get_formatted_output(self) -> str:
        """Get formatted output for display"""
        if self.is_success() and self.has_output():
            return self.output.strip()
        elif self.has_error():
            return f"Error: {self.error.strip()}"
        else:
            return f"Status: {self.status.value}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'account_id': self.account_id,
            'command': self.command,
            'status': self.status.value,
            'output': self.output,
            'error': self.error,
            'timestamp': self.timestamp.isoformat(),
            'execution_time': self.execution_time,
            'exit_code': self.exit_code,
            'team': self.team
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CommandResult':
        """Create CommandResult from dictionary"""
        return cls(
            account_id=data['account_id'],
            command=data['command'],
            status=data.get('status', 'error'),
            output=data.get('output'),
            error=data.get('error'),
            timestamp=data.get('timestamp', datetime.now().isoformat()),
            execution_time=data.get('execution_time', 0.0),
            exit_code=data.get('exit_code')
        )
    
    def __str__(self) -> str:
        """String representation of the result"""
        return f"CommandResult(account={self.account_id}, command='{self.command}', status={self.status.value})"
    
    def __repr__(self) -> str:
        """Detailed representation of the result"""
        return (f"CommandResult(account_id='{self.account_id}', command='{self.command}', "
                f"status={self.status}, execution_time={self.execution_time}s, "
                f"timestamp='{self.timestamp.isoformat()}')")

@dataclass
class ExecutionSummary:
    """Summary of command execution across multiple accounts"""
    command: str
    results: List[CommandResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    total_execution_time: float = 0.0  # in seconds
    
    def __post_init__(self):
        """Post-initialization validation"""
        if isinstance(self.started_at, str):
            try:
                self.started_at = datetime.fromisoformat(self.started_at)
            except ValueError:
                self.started_at = datetime.now()
        
        if isinstance(self.completed_at, str):
            try:
                self.completed_at = datetime.fromisoformat(self.completed_at)
            except ValueError:
                self.completed_at = None
    
    def add_result(self, result: CommandResult) -> None:
        """Add a command result to the summary"""
        self.results.append(result)
    
    def mark_completed(self) -> None:
        """Mark the execution as completed"""
        self.completed_at = datetime.now()
        if self.started_at:
            self.total_execution_time = (self.completed_at - self.started_at).total_seconds()
    
    def get_successful_results(self) -> List[CommandResult]:
        """Get all successful results"""
        return [result for result in self.results if result.is_success()]
    
    def get_failed_results(self) -> List[CommandResult]:
        """Get all failed results"""
        return [result for result in self.results if result.is_error()]
    
    def get_success_count(self) -> int:
        """Get number of successful executions"""
        return len(self.get_successful_results())
    
    def get_failure_count(self) -> int:
        """Get number of failed executions"""
        return len(self.get_failed_results())
    
    def get_total_count(self) -> int:
        """Get total number of executions"""
        return len(self.results)
    
    def get_success_rate(self) -> float:
        """Get success rate as percentage"""
        total = self.get_total_count()
        if total == 0:
            return 0.0
        return (self.get_success_count() / total) * 100.0
    
    def is_completed(self) -> bool:
        """Check if execution is completed"""
        return self.completed_at is not None
    
    def get_results_by_account(self, account_id: str) -> List[CommandResult]:
        """Get all results for a specific account"""
        return [result for result in self.results if result.account_id == account_id]
    
    def get_average_execution_time(self) -> float:
        """Get average execution time across all results"""
        if not self.results:
            return 0.0
        total_time = sum(result.execution_time for result in self.results)
        return total_time / len(self.results)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'command': self.command,
            'results': [result.to_dict() for result in self.results],
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'total_execution_time': self.total_execution_time
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ExecutionSummary':
        """Create ExecutionSummary from dictionary"""
        return cls(
            command=data['command'],
            results=[CommandResult.from_dict(result_data) for result_data in data.get('results', [])],
            started_at=data.get('started_at', datetime.now().isoformat()),
            completed_at=data.get('completed_at'),
            total_execution_time=data.get('total_execution_time', 0.0)
        )
    
    def __str__(self) -> str:
        """String representation of the summary"""
        return (f"ExecutionSummary(command='{self.command}', "
                f"results={self.get_total_count()}, "
                f"success_rate={self.get_success_rate():.1f}%)")
    
    def __repr__(self) -> str:
        """Detailed representation of the summary"""
        return (f"ExecutionSummary(command='{self.command}', "
                f"results={self.get_total_count()}, "
                f"successful={self.get_success_count()}, "
                f"failed={self.get_failure_count()}, "
                f"completed={self.is_completed()})")

# Helper functions for creating results
def create_success_result(account_id: str, command: str, output: str, 
                         execution_time: float = 0.0, exit_code: int = 0) -> CommandResult:
    """Create a successful command result"""
    return CommandResult(
        account_id=account_id,
        command=command,
        status=ResultStatus.SUCCESS,
        output=output,
        execution_time=execution_time,
        exit_code=exit_code
    )

def create_error_result(account_id: str, command: str, error: str,
                       execution_time: float = 0.0, exit_code: Optional[int] = None) -> CommandResult:
    """Create an error command result"""
    return CommandResult(
        account_id=account_id,
        command=command,
        status=ResultStatus.ERROR,
        error=error,
        execution_time=execution_time,
        exit_code=exit_code
    )

def create_timeout_result(account_id: str, command: str, 
                         execution_time: float = 0.0) -> CommandResult:
    """Create a timeout command result"""
    return CommandResult(
        account_id=account_id,
        command=command,
        status=ResultStatus.TIMEOUT,
        error="Command execution timed out",
        execution_time=execution_time
    )