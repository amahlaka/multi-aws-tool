# MultiAWSTool

A command-line tool for managing multiple AWS accounts through AWS SSO. Execute AWS CLI commands across multiple accounts safely and efficiently with built-in security controls and parallel execution support.

## Features

- **Multi-account Operations**: Execute AWS CLI commands across multiple accounts via SSO
- **Automated Profile Management**: Generate and manage AWS CLI profiles automatically
- **Parallel & Sequential Execution**: Choose between parallel (fast) or sequential (safe) execution modes
- **Smart Output Management**: Configurable output formatting with customizable file naming patterns
- **Security Controls**: Built-in protection against destructive operations with configurable overrides
- **Shell Completion**: Full shell completion support for bash, zsh, and fish
- **Library Integration**: Import as a Python library for use in other tools and scripts

## Installation

### Option 1: Install as Package (Recommended)

Install MultiAWSTool as a Python package to get the `multi-aws` command:

```bash
# Clone the repository
git clone <repository-url>
cd MultiAWSTool

# Install in development mode (creates multi-aws command)
pip install -e .

# Or install from PyPI when published
pip install multi-aws-tool
```

After installation, you can use the `multi-aws` command directly:
```bash
multi-aws --help
multi-aws configure
```

### Option 2: Development Setup

For development or if you prefer to run directly:

```bash
# Clone and setup
git clone <repository-url>
cd MultiAWSTool

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run directly
python main.py --help
```

### Shell Completion Setup

Enable shell completion for better command-line experience:

```bash
# Generate completion script for your shell
multi-aws completion --shell zsh  # or bash, fish

# For zsh, add to ~/.zshrc:
eval "$(_MULTI_AWS_COMPLETE=zsh_source multi-aws)"

# For bash, add to ~/.bashrc:
eval "$(_MULTI_AWS_COMPLETE=bash_source multi-aws)"

# Or install directly:
multi-aws completion --shell zsh > ~/.multi-aws-completion.zsh
echo "source ~/.multi-aws-completion.zsh" >> ~/.zshrc
```

## Quick Start

1. **Install the tool** (see Installation section above)

2. **Configure the tool**:
```bash
multi-aws configure
```

3. **Initialize SSO and discover accounts**:
```bash
multi-aws init --sso-session default
```

4. **Fetch roles for accounts**:
```bash
multi-aws roles --accounts 123456789012,987654321098
```

5. **Generate AWS profiles**:
```bash
multi-aws profiles --accounts 123456789012 --role PowerUserAccess --append-to-config
```

6. **Run commands across accounts**:
```bash
multi-aws run 'sts get-caller-identity' --accounts 123456789012,987654321098
```

### Advanced Usage Examples

**Run commands in parallel with output saving**:
```bash
multi-aws run 'ec2 describe-instances' --accounts all --parallel --save
```

**Filter accounts by team and run with custom timeout**:
```bash
multi-aws run 'iam list-users' --team production --timeout 60
```

**Dry run to see what would be executed**:
```bash
multi-aws run 'ec2 terminate-instances --instance-ids i-1234567890abcdef0' --accounts 123456789012 --dry-run
```

## Commands

### Core Commands
- **`configure`**: Interactive setup of tool configuration
- **`init`**: Initialize SSO authentication and discover AWS accounts
- **`roles`**: Fetch available IAM roles for specified accounts
- **`profiles`**: Generate AWS CLI profiles for account/role combinations
- **`run`**: Execute AWS CLI commands across multiple accounts
- **`sync`**: Sync profile names from AWS config to account data

### Management Commands
- **`cleanup`**: Remove tool-generated configurations (profiles, tokens, account data)
- **`clean-duplicates`**: Find and remove duplicate AWS profiles
- **`sanitize-names`**: Clean account names for profile compatibility
- **`assign-team`**: Assign product team labels to accounts
- **`list-team-accounts`**: List accounts by product team

### Utility Commands
- **`completion`**: Generate shell completion scripts

### Command Examples

```bash
# Interactive configuration
multi-aws configure

# Discover accounts with specific SSO session
multi-aws init --sso-session my-sso-session

# Get roles for specific accounts
multi-aws roles --accounts 123456789012,987654321098

# Generate profiles and add to AWS config
multi-aws profiles --accounts 123456789012 --role PowerUserAccess --append-to-config

# Execute commands across all active accounts
multi-aws run 'sts get-caller-identity' --accounts all

# Execute in parallel with custom output directory
multi-aws run 'ec2 describe-regions' --accounts file:accounts.txt --parallel --output-dir ./results

# Assign team to accounts
multi-aws assign-team --accounts 123456789012,987654321098 --team backend-team

# List accounts by team
multi-aws list-team-accounts --team backend-team

# Clean up duplicate profiles
multi-aws clean-duplicates --dry-run
```

## Configuration

The tool creates a configuration file at `~/.multi-aws/config.ini` with comprehensive settings:

### Configuration Sections

**General Settings**:
- AWS profile prefix for generated profiles
- SSO session name
- Default AWS region
- Account data file location

**Output Settings**:
- Filename pattern with placeholders (`!A`=account-name, `!c`=command, `!d`=date)
- Output format (json, yaml, txt, csv)
- Output directory path

**Execution Settings**:
- Execution mode (parallel or sequential)
- Error handling (stop after N errors)
- Command timeout settings

**Security Settings**:
- Allow/deny destructive commands
- Command validation rules

**Logging Settings**:
- Log level and file location
- Console logging preferences
- Log rotation settings

### Environment Variables

You can override configuration using environment variables with the `MULTI_AWS_` prefix:
```bash
export MULTI_AWS_REGION=eu-west-1
export MULTI_AWS_TIMEOUT=600
export MULTI_AWS_VERBOSE=1
```

### Configuration File Example

```ini
[general]
prefix = multi-aws
sso-session = default
region = us-east-1
account-file = ~/.multi-aws/accounts.json

[output]
pattern = !A-!c-!d
format = json
path = ~/.multi-aws/outputs

[execution]
mode = sequential
stop-on-errors = 0

[security]
allow-destructive-commands = false

[logging]
level = INFO
file = ~/.multi-aws/logs/multi-aws.log
console = true
```

## Using as a Python Library

MultiAWSTool can be imported and used as a library in other Python projects:

```python
from multi_aws_tool import AccountManager, ConfigManager, OutputParser

# Initialize managers
config_manager = ConfigManager()
account_manager = AccountManager()

# Discover accounts
accounts = account_manager.discover_accounts()

# Parse execution results
from multi_aws_tool.output import parse_execution_summary
summary = parse_execution_summary('execution_summary_20251031_120000.json')
print(f"Success rate: {summary.success_rate:.1f}%")
```

For detailed library usage, see [LIBRARY_USAGE.md](LIBRARY_USAGE.md) and [OUTPUT_MODULE.md](OUTPUT_MODULE.md).

## Output Structure

MultiAWSTool generates structured output files that can be easily parsed by other tools:

### Execution Summary Files
- **Format**: `execution_summary_YYYYMMDD_HHMMSS.json`
- **Content**: Complete execution results with metadata, timing, and error information
- **Usage**: Import using the `multi_aws_tool.output` module for analysis

### Individual Account Output Files  
- **Format**: `{account-name}-{command}-{date}.{format}`
- **Content**: Raw AWS CLI command output for each account
- **Customizable**: Filename patterns and formats configurable

### Example Output Structure
```
~/.multi-aws/outputs/
├── execution_summary_20251031_120000.json
├── production-account-sts-get-caller-identity-20251031.json
├── staging-account-sts-get-caller-identity-20251031.json
└── dev-account-sts-get-caller-identity-20251031.json
```

## Troubleshooting

### Common Issues

**Command not found after installation**:
```bash
# Ensure the virtual environment is activated
source venv/bin/activate

# Or check if ~/.local/bin is in your PATH
export PATH="$HOME/.local/bin:$PATH"
```

**SSO Authentication Failed**:
```bash
# Check SSO configuration in ~/.aws/config
cat ~/.aws/config

# Re-initialize if needed
multi-aws init --sso-session your-session-name
```

**Profile Generation Issues**:
```bash
# Clean up existing profiles first
multi-aws clean-duplicates

# Regenerate profiles
multi-aws profiles --accounts <account-ids> --role <role-name> --append-to-config
```

**Permission Errors**:
```bash
# Check account roles
multi-aws roles --accounts <account-id>

# Verify profile works
aws --profile <profile-name> sts get-caller-identity
```

### Debug Mode

Enable verbose logging for troubleshooting:
```bash
multi-aws --verbose <command>
```

## Development

### Setting up Development Environment

```bash
# Clone and setup
git clone <repository-url>
cd MultiAWSTool

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in development mode
pip install -e .

# Install development dependencies
pip install -r requirements-dev.txt  # if available

# Run tests
python -m pytest tests/  # if tests exist
```

### Project Structure

```
MultiAWSTool/
├── multi_aws_tool/           # Main package
│   ├── __init__.py          # Package exports
│   ├── main.py              # CLI entry point
│   ├── output.py            # Output parsing module
│   ├── aws/                 # AWS integration
│   ├── cli/                 # Command-line interface
│   ├── config/              # Configuration management
│   ├── models/              # Data models
│   └── utils/               # Utility functions
├── examples/                # Usage examples
├── pyproject.toml          # Package configuration
├── requirements.txt        # Dependencies
└── README.md              # This file
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

MIT License