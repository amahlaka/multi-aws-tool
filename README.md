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
- **MCP Server**: Use your accounts and profiles from Claude Desktop / Claude Code via a local MCP server

## Installation

**Requirements**
- Python 3.11 or newer
- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- Access to your organization's AWS IAM Identity Center (SSO) portal

### Recommended: install as a tool with uv (or pipx)

[uv](https://docs.astral.sh/uv/) installs `multi-aws` into its own isolated environment and puts
the commands (`multi-aws`, `multi-aws-mcp`, `mat-parse`) on your PATH:

```bash
# Install uv if you don't have it (or: curl -LsSf https://astral.sh/uv/install.sh | sh)
brew install uv

uv tool install --python 3.12 multi-aws-tool
```

Keep the `--python 3.12` (any version from 3.11 up works). Without it, uv uses the Python it finds
first, such as an active conda environment or an older system Python. On Python 3.10 or older,
it then silently installs an old 0.1.x release that lacks `setup` and the MCP server. uv
downloads Python 3.12 itself if you don't have it.

[pipx](https://pipx.pypa.io/) works the same way: `pipx install --python python3.12 multi-aws-tool`.

Then run the guided setup:

```bash
multi-aws setup
```

Upgrade or remove later with:

```bash
uv tool upgrade multi-aws-tool
uv tool uninstall multi-aws-tool   # your config, account data and AWS profiles are kept
```

> **Why not `pip install multi-aws-tool`?** Homebrew's Python and most current Linux
> distributions block `pip install` into the system Python and fail with
> `error: externally-managed-environment` ([PEP 668](https://peps.python.org/pep-0668/)).
> Use `uv tool` / `pipx` as above, or install into a virtual environment.

### Alternative: install into a virtual environment with pip

```bash
python3.12 -m venv ~/.venvs/multi-aws
source ~/.venvs/multi-aws/bin/activate
pip install multi-aws-tool
multi-aws --help
```

The commands are only available while the environment is active. To use them anywhere,
link them onto your PATH, e.g. `ln -s ~/.venvs/multi-aws/bin/multi-aws ~/.local/bin/`.

### Claude Desktop / Claude Code

After installing, connect the MCP server (see [Using from Claude](#using-from-claude-mcp-server)):

```bash
multi-aws-mcp --install-claude-desktop   # then restart Claude Desktop
claude mcp add multi-aws -- multi-aws-mcp
```

The Claude Desktop entry points at the Python environment the tool is installed in, so run
`--install-claude-desktop` again if you reinstall it somewhere else.

### From source

To run the latest code from GitHub, or to contribute, see [Development](#development).

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

The fastest way to get going is the guided setup. It checks the AWS CLI, adds your SSO session,
logs you in, discovers your accounts, fetches roles, creates profiles, verifies access and
optionally connects Claude Desktop. It's safe to re-run, because finished steps are skipped:

```bash
multi-aws setup
```

Or step by step:

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

**Commands with their own options** (quote the whole command, or put it after `--`):
```bash
multi-aws run "ec2 describe-instances --query 'Reservations[].Instances[].InstanceId'" --accounts 123456789012
multi-aws run --accounts 123456789012 -- ec2 describe-instances --query 'Reservations[].Instances[].InstanceId'
```

**Dry run to see what would be executed**:
```bash
multi-aws run 'ec2 terminate-instances --instance-ids i-1234567890abcdef0' --accounts 123456789012 --dry-run
```

## Commands

### Core Commands
- **`setup`**: Guided first-time setup (SSO session, login, accounts, roles, profiles, Claude)
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
- Filename pattern with placeholders (see [Filename Pattern Placeholders](#filename-pattern-placeholders))
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

## Using from Claude (MCP server)

`multi-aws-mcp` is a local [MCP](https://modelcontextprotocol.io) server (stdio) that gives
Claude Desktop, Claude Code and other MCP clients the whole tool: onboarding, SSO, account
discovery, roles, profiles, teams, tags, templates and running commands. It uses the same
config, account data, SSO session and AWS CLI profiles as the `multi-aws` CLI, and runs on your
machine, so credentials never leave it.

```bash
multi-aws-mcp --install-claude-desktop # adds it to claude_desktop_config.json (keeps a .bak)
```

Restart Claude Desktop afterwards. For Claude Code:

```bash
claude mcp add multi-aws -- multi-aws-mcp
```

`multi-aws-mcp --print-config` prints the JSON entry if you'd rather edit the config yourself.

**New users:** pick the **"Set up multi-aws"** prompt (`getting_started`) in Claude, or just ask
"help me set up multi-aws". Claude checks what's missing and walks you through adding your SSO
session, logging in, discovering accounts, fetching roles and creating profiles.

| Area | Tools |
|------|-------|
| Setup & status | `get_status` (setup checklist + next step), `get_config`, `update_config`, `list_sso_sessions`, `add_sso_session`, `sso_login` |
| Accounts & roles | `discover_accounts`, `list_accounts`, `fetch_roles` |
| Profiles | `generate_profiles`, `sync_profiles`, `sanitize_account_names`, `clean_duplicate_profiles` |
| Teams & tags | `list_teams`, `assign_team`, `set_tags`, `remove_tags`, `sync_tags` |
| Templates | `list_templates`, `save_template`, `delete_template`, `run_template` |
| Running | `run_aws_command` |
| Cleanup | `cleanup` (needs explicit confirmation) |

Safety:
- Destructive AWS commands follow `security.allow-destructive-commands` in your config. Claude can
  neither override nor change that setting.
- Every edit to `~/.aws/config` keeps a timestamped backup next to it, and existing profiles are
  updated in place rather than duplicated. Bulk operations support `dry_run`.
- Large command outputs are truncated in the response, and the full results are saved under
  `<output path>/mcp/`.

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

### Filename Pattern Placeholders

The `pattern` setting in `[output]` controls how individual output files are named. Combine placeholders freely; slashes (`/`) create subdirectories.

| Placeholder | Description | Example value |
|-------------|-------------|---------------|
| `!a` | AWS account ID | `123456789012` |
| `!A` | Account name (spaces and `/` replaced with `_`) | `production_account` |
| `!c` | AWS service + operation joined with `-` | `ec2-describe-instances` |
| `!S` | AWS service only | `ec2` |
| `!C` | AWS operation only | `describe-instances` |
| `!r` | IAM role (last segment of the profile name) | `PowerUserAccess` |
| `!p` | Product team (spaces and `/` replaced with `_`) | `backend_team` |
| `!R` | AWS region the command ran in | `eu-west-1` |
| `!d` | Date (`YYYYMMDD`) | `20251031` |
| `!t` | Time (`HHMMSS`) | `143022` |
| `!s` | Full timestamp (`YYYYMMDD_HHMMSS`) | `20251031_143022` |

**Examples**:

```ini
# Default: account name, command, date
pattern = !A-!c-!d

# Include region — useful with --all-regions
pattern = !A/!R/!c-!d

# Role-based subdirectories
pattern = !r/!A-!c-!d

# Fully qualified with timestamp
pattern = !A-!R-!c-!s
```

> **Tip**: Use `/` in the pattern to create subdirectories under the output path, e.g. `!A/!R/!c-!d` produces `<output-dir>/my-account/eu-west-1/ec2-describe-instances-20251031.json`.

## Troubleshooting

### Common Issues

**Command not found after installation**:
```bash
# uv / pipx put commands in ~/.local/bin; add it to your PATH
uv tool update-shell        # or: pipx ensurepath
# then open a new terminal
```

**`multi-aws --version` shows 0.1.x / `multi-aws setup` doesn't exist**: the tool was installed
with a Python older than 3.11 (often an active conda environment), so an old release was picked.
`uv tool upgrade` won't fix this. Reinstall with a newer Python instead:
```bash
uv tool install --force --python 3.12 multi-aws-tool
```

**`error: externally-managed-environment` from pip**: install with `uv tool install --python 3.12 multi-aws-tool`
or `pipx install --python python3.12 multi-aws-tool`, or into a virtual environment (see [Installation](#installation)).

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
git clone https://github.com/amahlaka/multi-aws-tool.git
cd multi-aws-tool

# Create a virtual environment (Python 3.11+) and install in editable mode with test deps
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run the tests
python -m pytest
```

To use your checkout as your everyday `multi-aws` command (changes apply without reinstalling):

```bash
uv tool install --python 3.12 --editable .
```

### Project Structure

```
multi-aws-tool/
├── multi_aws_tool/           # Main package
│   ├── __init__.py           # Package exports
│   ├── main.py               # CLI entry point (multi-aws)
│   ├── services.py           # Shared operations used by the CLI, TUI and MCP server
│   ├── mcp_server.py         # MCP server (multi-aws-mcp)
│   ├── execution.py          # Library execute() API
│   ├── output.py             # Output parsing module
│   ├── aws/                  # AWS SSO, accounts, ~/.aws/config editing
│   ├── cli/                  # Command-line interface and setup wizard
│   ├── config/               # Configuration and templates
│   ├── models/               # Data models
│   ├── tui/                  # Terminal UI
│   └── utils/                # Utility functions
├── mat_parse/                # mat-parse output parser
├── examples/                 # Usage examples
├── tests/                    # Test suite
├── pyproject.toml            # Package configuration and dependencies
└── README.md                 # This file
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

MIT License