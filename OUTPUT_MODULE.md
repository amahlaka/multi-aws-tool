# MultiAWSTool Output Structure Module

This module provides importable classes and utilities for working with MultiAWSTool command execution outputs. Use this in other tools to parse and process MultiAWSTool result files.

## Installation

```bash
# If MultiAWSTool is installed as a package
pip install multi-aws-tool

# Or install from source
pip install -e .
```

## Quick Start

```python
from multi_aws_tool.output import parse_execution_summary, analyze_execution_summary

# Parse execution summary
summary = parse_execution_summary('execution_summary_20251031_120000.json')
print(f"Success rate: {summary.success_rate:.1f}%")

# Analyze execution
analysis = analyze_execution_summary('execution_summary_20251031_120000.json')
print(f"Recommendations: {analysis['recommendations']}")
```

## Classes

### AccountResult

Represents the result of executing a command on a single AWS account.

```python
from multi_aws_tool.output import AccountResult

# Properties
result.account_id        # AWS account ID
result.account_name      # Human-readable account name
result.profile_name      # AWS CLI profile used
result.command          # Command that was executed
result.status           # SUCCESS, ERROR, or TIMEOUT
result.output           # Command output (if successful)
result.error            # Error message (if failed)
result.timestamp        # ISO timestamp of execution
result.execution_time   # Execution time in seconds
result.exit_code        # Command exit code
result.output_file      # Path to individual output file

# Methods
result.is_success()     # Returns True if successful
result.has_output()     # Returns True if there's output
result.has_error()      # Returns True if there's an error
result.to_dict()        # Convert to dictionary
```

### MultiAWSExecutionSummary

Represents a complete execution summary with all account results.

```python
from multi_aws_tool.output import MultiAWSExecutionSummary

# Properties
summary.execution_id         # Unique execution identifier
summary.command             # Command that was executed
summary.timestamp           # Execution timestamp
summary.total_accounts      # Total number of accounts
summary.successful_accounts # Number of successful executions
summary.failed_accounts     # Number of failed executions
summary.timeout_accounts    # Number of timed out executions
summary.execution_mode      # parallel or sequential
summary.total_execution_time # Total time for all accounts
summary.results             # List of AccountResult objects
summary.output_directory    # Directory containing output files
summary.config_used         # Configuration used for execution

# Calculated properties
summary.success_rate        # Success rate as percentage

# Methods
summary.get_successful_results()  # Get only successful results
summary.get_failed_results()      # Get only failed results
summary.get_timeout_results()     # Get only timeout results
summary.get_results_by_account(account_id)  # Get result for specific account
summary.to_dict()                 # Convert to dictionary
```

### OutputParser

Parser for MultiAWSTool output files.

```python
from multi_aws_tool.output import OutputParser

# Initialize parser
parser = OutputParser('/path/to/output/directory')

# Parse execution summary
summary = parser.parse_execution_summary('execution_summary_20251031_120000.json')

# Parse individual account output
account_output = parser.parse_account_output('account-123456789012-command-20251031.json')

# Find files
summary_files = parser.find_execution_summaries()
account_files = parser.find_account_outputs(account_id='123456789012')
```

### OutputAnalyzer

Analyzer for execution results with insights and recommendations.

```python
from multi_aws_tool.output import OutputAnalyzer, OutputParser

parser = OutputParser('/path/to/output')
analyzer = OutputAnalyzer(parser)

# Analyze single execution
summary = parser.parse_execution_summary('execution_summary.json')
analysis = analyzer.analyze_execution(summary)

# Compare multiple executions
summaries = [parser.parse_execution_summary(f) for f in summary_files]
comparison = analyzer.compare_executions(summaries)
```

## Output File Formats

### Execution Summary Format

```json
{
  "execution_id": "20251031_120000",
  "command": "sts get-caller-identity",
  "timestamp": "2025-10-31T12:00:00",
  "total_accounts": 5,
  "successful_accounts": 4,
  "failed_accounts": 1,
  "timeout_accounts": 0,
  "execution_mode": "parallel",
  "total_execution_time": 12.5,
  "output_directory": "/path/to/outputs",
  "config_used": {
    "region": "us-east-1",
    "timeout": 300
  },
  "results": [
    {
      "account_id": "123456789012",
      "account_name": "production-account",
      "profile_name": "multi-aws-production-PowerUser",
      "command": "sts get-caller-identity",
      "status": "SUCCESS",
      "output": "{\"Account\": \"123456789012\", ...}",
      "error": null,
      "timestamp": "2025-10-31T12:00:01",
      "execution_time": 2.3,
      "exit_code": 0,
      "output_file": "production-account-sts-get-caller-identity-20251031.json"
    }
  ]
}
```

### Individual Account Output

The individual account output files contain the raw output from the AWS CLI command:

```json
{
  "Account": "123456789012",
  "UserId": "AIDACKCEVSQ6C2EXAMPLE",
  "Arn": "arn:aws:iam::123456789012:user/DevUser"
}
```

## Usage Examples

### Basic Parsing

```python
from multi_aws_tool.output import parse_execution_summary

# Parse execution summary
summary = parse_execution_summary('execution_summary_20251031_120000.json')

print(f"Command: {summary.command}")
print(f"Success Rate: {summary.success_rate:.1f}%")
print(f"Total Time: {summary.total_execution_time:.2f}s")

# Access individual results
for result in summary.results:
    if result.is_success():
        print(f"✅ {result.account_name}: {result.execution_time:.2f}s")
    else:
        print(f"❌ {result.account_name}: {result.error}")
```

### Filtering Results

```python
from multi_aws_tool.output import OutputParser

parser = OutputParser('./outputs')
summary = parser.parse_execution_summary('execution_summary.json')

# Get only failed results
failed_results = summary.get_failed_results()
print(f"Failed accounts: {len(failed_results)}")

# Filter by execution time
slow_accounts = [r for r in summary.results if r.execution_time > 10.0]
print(f"Slow accounts (>10s): {len(slow_accounts)}")

# Filter by error type
access_denied = [r for r in summary.results 
                if r.error and 'AccessDenied' in r.error]
print(f"Access denied errors: {len(access_denied)}")
```

### Analysis and Insights

```python
from multi_aws_tool.output import analyze_execution_summary

# Analyze execution
analysis = analyze_execution_summary('execution_summary.json')

# Performance insights
print(f"Average time per account: {analysis['overview']['avg_time_per_account']:.2f}s")
print(f"Fastest account: {analysis['performance']['fastest_account']['account_id']}")
print(f"Slowest account: {analysis['performance']['slowest_account']['account_id']}")

# Error patterns
for error_type, count in analysis['errors']['error_patterns'].items():
    print(f"{error_type}: {count} occurrences")

# Recommendations
for recommendation in analysis['recommendations']:
    print(f"💡 {recommendation}")
```

### Custom Report Generation

```python
from multi_aws_tool.output import OutputParser
import json

parser = OutputParser('./outputs')
summary = parser.parse_execution_summary('execution_summary.json')

# Create custom report
report = {
    'execution_date': summary.timestamp,
    'command': summary.command,
    'summary': {
        'total': summary.total_accounts,
        'successful': summary.successful_accounts,
        'failed': summary.failed_accounts,
        'success_rate': summary.success_rate
    },
    'top_performers': [
        {
            'account': r.account_name,
            'time': r.execution_time
        }
        for r in sorted(summary.results, key=lambda x: x.execution_time)[:5]
    ],
    'failures': [
        {
            'account': r.account_name,
            'error': r.error
        }
        for r in summary.get_failed_results()
    ]
}

# Save custom report
with open('custom_report.json', 'w') as f:
    json.dump(report, f, indent=2)
```

### Integration with Data Analysis Tools

```python
import pandas as pd
from multi_aws_tool.output import parse_execution_summary

# Convert to pandas DataFrame
summary = parse_execution_summary('execution_summary.json')
df = pd.DataFrame([result.to_dict() for result in summary.results])

# Analyze with pandas
print(df['status'].value_counts())
print(df['execution_time'].describe())
print(df.groupby('status')['execution_time'].mean())

# Plot results (if matplotlib is available)
# df['execution_time'].hist(bins=20)
# df['status'].value_counts().plot(kind='bar')
```

### Monitoring and Alerting

```python
from multi_aws_tool.output import parse_execution_summary

def check_execution_health(summary_file):
    """Check if execution meets health criteria"""
    summary = parse_execution_summary(summary_file)
    
    alerts = []
    
    # Check success rate
    if summary.success_rate < 95.0:
        alerts.append(f"Low success rate: {summary.success_rate:.1f}%")
    
    # Check for timeouts
    if summary.timeout_accounts > 0:
        alerts.append(f"Timeouts detected: {summary.timeout_accounts} accounts")
    
    # Check execution time
    avg_time = summary.total_execution_time / summary.total_accounts
    if avg_time > 30.0:  # 30 seconds threshold
        alerts.append(f"Slow execution: {avg_time:.1f}s average per account")
    
    return alerts

# Usage
alerts = check_execution_health('execution_summary.json')
if alerts:
    print("🚨 Health check alerts:")
    for alert in alerts:
        print(f"  • {alert}")
else:
    print("✅ Execution health check passed")
```

## Integration with Other Tools

### Jupyter Notebooks

```python
# In a Jupyter notebook cell
from multi_aws_tool.output import parse_execution_summary
import matplotlib.pyplot as plt

summary = parse_execution_summary('execution_summary.json')

# Plot success rate over time
execution_times = [r.execution_time for r in summary.results]
plt.hist(execution_times, bins=20)
plt.xlabel('Execution Time (seconds)')
plt.ylabel('Number of Accounts')
plt.title('Execution Time Distribution')
plt.show()
```

### CI/CD Pipelines

```python
#!/usr/bin/env python3
# Script for CI/CD pipeline
import sys
from multi_aws_tool.output import parse_execution_summary

def validate_execution(summary_file, min_success_rate=95.0):
    """Validate execution for CI/CD pipeline"""
    try:
        summary = parse_execution_summary(summary_file)
        
        if summary.success_rate < min_success_rate:
            print(f"❌ Execution failed: {summary.success_rate:.1f}% success rate")
            return False
        
        print(f"✅ Execution passed: {summary.success_rate:.1f}% success rate")
        return True
        
    except Exception as e:
        print(f"❌ Failed to validate execution: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: validate_execution.py <summary_file>")
        sys.exit(1)
    
    success = validate_execution(sys.argv[1])
    sys.exit(0 if success else 1)
```

## Error Handling

```python
from multi_aws_tool.output import OutputParser, parse_execution_summary

try:
    summary = parse_execution_summary('execution_summary.json')
    print(f"Parsed {summary.total_accounts} accounts")
    
except FileNotFoundError:
    print("❌ Execution summary file not found")
except json.JSONDecodeError:
    print("❌ Invalid JSON in execution summary file")
except KeyError as e:
    print(f"❌ Missing required field in execution summary: {e}")
except Exception as e:
    print(f"❌ Unexpected error parsing execution summary: {e}")
```

## Best Practices

1. **Always handle exceptions** when parsing files
2. **Use the OutputParser** for consistent file handling
3. **Filter results** to focus on specific scenarios
4. **Cache parsed results** for repeated analysis
5. **Validate file formats** before processing
6. **Use type hints** in your analysis code
7. **Document custom analysis functions**

For more examples, see `examples/parse_outputs.py` in the project repository.