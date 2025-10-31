# MultiAWSTool - AI Coding Agent Instructions

## Project Overview
MultiAWSTool is a CLI application for managing AWS operations across multiple accounts via AWS SSO. It provides safe, configurable multi-account command execution with built-in security controls and parallel/sequential processing modes.

## Architecture & Core Components

### Entry Point & CLI Structure  
- **Entry**: `main.py` → `src/cli/commands.py` (Click-based CLI)
- **Key Commands**: `configure`, `init`, `roles`, `profiles`, `run`, `cleanup`
- **Context Pattern**: All commands use `AppContext` class for shared config/account manager state

### Data Flow & State Management
1. **Configuration**: `~/.multi-aws/config.ini` (managed by `src/config/manager.py`)
2. **Account Data**: `~/.multi-aws/accounts.json` (via `src/utils/account_data.py`)  
3. **SSO Cache**: `~/.multi-aws/sso-cache/` (token management in `src/aws/sso_client.py`)
4. **Output Files**: Uses configurable patterns like `!A-!c-!d` (AccountName-command-date)

### Core Models (`src/models/`)
- **Account**: `id`, `name`, `status`, `roles[]`, `profile_name`, `last_updated`
- **Role**: `name`, `arn`, `description`  
- **AccountCollection**: Manages multiple accounts with discovery timestamps
- **CommandResult**: Execution results with account, command, output, errors

## Critical Developer Workflows

### Setup & Configuration
```bash
python main.py configure          # Interactive config setup
python main.py init --sso-session default  # SSO auth + account discovery
python main.py roles --accounts 123456789012  # Fetch available roles
python main.py profiles --accounts 123456789012 --role PowerUserAccess
```

### Command Execution
```bash
# Sequential (safe default)
python main.py run 'sts get-caller-identity' --accounts file.txt

# Parallel execution
python main.py run 'ec2 describe-instances' --accounts 123,456 --parallel

# Dry run for validation
python main.py run 'iam list-users' --accounts all --dry-run
```

## Security & Safety Patterns

### Destructive Command Protection
- **Default**: Only read-only commands (`describe`, `list`, `get`) allowed
- **Override**: Set `allow-destructive-commands=true` in config for `create`, `delete`, `modify` operations
- **Validation**: `src/config/schema.py` contains `DESTRUCTIVE_COMMANDS` set for filtering

### Account Validation
- Commands **require** pre-configured AWS profiles (generated via `profiles` command)
- SSO token auto-refresh prevents authentication failures
- Account status tracking (`ACTIVE`/`DISABLED`) excludes inaccessible accounts

## Data Persistence Conventions

### Configuration Structure (`~/.multi-aws/config.ini`)
```ini
[general]
prefix = multi-aws
sso-session = default
region = us-east-1

[output]  
pattern = !A-!c-!d    # !A=account-name, !c=command, !d=date
format = json
path = ~/.multi-aws/outputs/

[security]
allow-destructive-commands = false
```

### Account Data Format
- **File**: `~/.multi-aws/accounts.json`
- **Schema**: AccountCollection with discovery timestamp + Account array
- **Auto-updates**: Account discovery refreshes every hour, role fetching per-account

## Integration & External Dependencies

### AWS Integration
- **SSO**: Uses boto3 SSO client for authentication and account discovery
- **Profiles**: Generates standard AWS CLI profiles in `~/.aws/config`
- **Commands**: Executes via subprocess calls to `aws` CLI (not direct boto3)

### Execution Patterns
- **Parallel**: Uses ThreadPoolExecutor for concurrent account operations
- **Error Handling**: Configurable error thresholds (`stop-on-errors` setting)
- **Output**: JSON files per account-command combination with timestamp

## Development & Testing

### Project Structure
- **Source**: `src/` with modules: `aws/`, `cli/`, `config/`, `models/`, `utils/`
- **Path Setup**: `main.py` adds `src/` to Python path for imports
- **Dependencies**: boto3, click, configparser, pyyaml, colorama, tabulate

### Key Extension Points
- **Command Validators**: Add patterns to `src/utils/validators.py`
- **Output Formats**: Extend filename pattern placeholders in `src/config/schema.py`
- **New Commands**: Follow existing Click command pattern in `src/cli/commands.py`

### Testing Commands
```bash
# Validate without execution
python main.py run 'sts get-caller-identity' --accounts test --dry-run

# Check configuration
python main.py configure  # Shows current settings interactively
```

## Common Patterns & Gotchas
- **Path Handling**: Always use `Path.expanduser()` for `~` paths
- **Error Context**: Include account ID in error messages for multi-account debugging  
- **Profile Naming**: Tool-generated profiles use configured prefix (default: `multi-aws`)
- **Command Quoting**: AWS CLI commands must be quoted: `'sts get-caller-identity'`
- **Account Input**: Supports comma-separated IDs or file paths with one ID per line