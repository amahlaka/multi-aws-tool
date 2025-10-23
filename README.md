# MultiAWSTool

A command-line tool for managing multiple AWS accounts through AWS SSO.

## Features

- Multi-account AWS operations through SSO authentication
- Automated profile generation and management
- Parallel and sequential command execution
- Configurable output formatting and error handling
- Safe command validation with destructive operation protection

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd MultiAWSTool
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Quick Start

1. Configure the tool:
```bash
python main.py configure
```

2. Initialize SSO and discover accounts:
```bash
python main.py init --sso-session default
```

3. Fetch roles for accounts:
```bash
python main.py roles --accounts 123456789012,987654321098
```

4. Generate AWS profiles:
```bash
python main.py profiles --accounts 123456789012 --role PowerUserAccess
```

5. Run commands across accounts:
```bash
python main.py run 'sts get-caller-identity' --accounts 123456789012,987654321098
```

## Commands

- `configure`: Set up tool configuration
- `init`: Initialize SSO and discover accounts
- `roles`: Fetch available roles for accounts
- `profiles`: Generate AWS CLI profiles
- `run`: Execute AWS CLI commands across accounts
- `cleanup`: Remove tool-generated profiles

## Configuration

The tool creates a configuration file at `~/.multi-aws/config.ini` with settings for:
- SSO session configuration
- Output formatting and patterns
- Execution modes (parallel/sequential)
- Security settings
- Error handling preferences

## License

MIT License