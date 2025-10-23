# MultiAWSTool

# Plan for Multi-AWS Account Management Tool

## How it works
- User runs the tool with `python ./main.py configure`
    - the tool creates ~/.multi-aws/config.ini for storing the following paramets that it will ask from the user:
    - prefix
    - sso-session
    - account-file (a json file path for storing accounts and roles)
    - region
    - output
        - pattern (!a for accountid, !A for account name, !c for commandname, !d for date, !t for time, !s for timestamp. for example "!A-!c-!d" results in accountName-sts_get-caller-identity-23.10.2025)
        - format (output file format, default: json, used as the file format for the saved file)
        - path (path to save the files in, default ~/.multi-aws/outputs/)
    - execution
        - mode (parallel or sequential, default: parallel)
        - stop-on-errors (number of errors before stopping execution, 0 for never stop, default: 5)
    - security
        - allow-destructive-commands (boolean, default: false - only allows read-only commands like describe, list, get)
- User runs the tool with `python ./main.py init --sso-session default`
    - The tool uses the provided sso-session to perform aws sso login, and saves the resulting access token and expiration time in a local cache file (~/.multi-aws/sso-cache/), if the specified sso-session does not exist in the user's aws config, an error is shown.
    - The tool uses aws python sdk to perform aws sso login, then uses the resulting access token to perform sso list-accounts feature to get list of the accounts that the user is able to access, and save the account id and name in account-file, also in account-file, the tool saves the timestamp of when the accounts were last fetched.
    - The tool automatically refreshes SSO tokens as needed during operation
    - If an account that was previously saved is no longer returned by list-accounts, it is marked as disabled in the account-file and excluded from future operations
- User runs the command `python ./main.py roles --accounts (comma seperated account id's or file that has the account id's)`
    - The tool takes each of the account id's from the input, sees if that account id is in the list of saved accounts from previous command, and if so, fetches the available roles for that account using sso list-roles feature, and saves the roles for that account in account-file.
- User runs command `python ./main.py profiles --accounts (account ids or file name) --role (role name to use) --output (optional, path to file to save the profiles)`
    - The tool checks if the provided role name is saved for the account by the previous command, and if so, generates the profile for that account, either in the `.aws/config` file or the defined output file, using the defined prefix from the tools config.ini file, and saves the name of the profile in the account file 
    - If profiles already exist in .aws/config that match the prefix but are not found in the account-file, the tool prompts the user to choose: rename, remove, or link the existing profiles 
- User runs command `python ./main.py run '(AWS CLI COMMAND)' --accounts (id's or file) --output (path to save output files)`
    - The tool checks that the specified accounts are configured as profiles, and authenticates to them, If the account is not configured, give an error.
    - By default, only read-only commands (describe, list, get, etc.) are allowed unless allow-destructive-commands is enabled in config
    - The tool runs the specified aws cli command (for example 'sts get-caller-identity') for each of the defined accounts using the execution mode (parallel/sequential) from config
    - Output is saved to files using the path, pattern, and format defined in config.ini
    - Errors are logged to console and saved to an errors folder within the output path, with timestamp in the filename
    - Execution stops when the configured error threshold is reached (unless set to 0 for unlimited)

## Additional Commands

- User runs command `python ./main.py cleanup --profiles`
    - Removes all profiles from .aws/config that match the tool's prefix and are tracked in the account-file
    - Prompts for confirmation before deletion

## Error Handling

- All errors are output to console with timestamps
- Errors are also saved to files in `{output-path}/errors/error-{timestamp}.log`
- SSO token refresh is handled automatically when tokens expire
- Accounts that become inaccessible are marked as disabled in account-file
- Command validation prevents destructive operations unless explicitly enabled
- Configurable error thresholds allow stopping execution or continuing regardless of errors

# Implementation Plan

## Project Structure
```
MultiAWSTool/
├── main.py                     # CLI entry point
├── requirements.txt            # Python dependencies
├── README.md                   # Project documentation
├── src/
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── commands.py         # CLI command definitions
│   │   └── validators.py       # Input validation
│   ├── config/
│   │   ├── __init__.py
│   │   ├── manager.py          # Configuration management
│   │   └── schema.py           # Configuration schema
│   ├── aws/
│   │   ├── __init__.py
│   │   ├── sso_client.py       # SSO authentication
│   │   ├── account_manager.py  # Account operations
│   │   ├── profile_manager.py  # AWS profile management
│   │   └── command_executor.py # AWS CLI command execution
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── file_utils.py       # File operations
│   │   ├── output_formatter.py # Output pattern handling
│   │   ├── error_handler.py    # Error logging
│   │   └── validators.py       # Command validation
│   └── models/
│       ├── __init__.py
│       ├── account.py          # Account data model
│       ├── config.py           # Configuration data model
│       └── result.py           # Command result model
└── tests/
    ├── __init__.py
    ├── test_config/
    ├── test_aws/
    ├── test_utils/
    └── fixtures/
```

## Implementation Phases

### Phase 1: Core Infrastructure
1. **Project Setup**
   - Initialize Python project with virtual environment
   - Setup requirements.txt with boto3, click, configparser
   - Create basic project structure
   - Setup logging configuration

2. **Configuration Management**
   - Implement `config/manager.py` for reading/writing config.ini
   - Create configuration schema validation
   - Implement default configuration creation

3. **Data Models**
   - Define Account model with status tracking
   - Create Configuration model
   - Implement Result model for command outputs

### Phase 2: AWS Integration
1. **SSO Authentication**
   - Implement SSO login flow using boto3
   - Create token caching mechanism
   - Add automatic token refresh logic
   - Handle SSO session validation

2. **Account Management**
   - Implement account discovery via SSO list-accounts
   - Add account status tracking (active/disabled)
   - Create role enumeration for accounts
   - Implement account-file JSON management

### Phase 3: CLI Commands
1. **Basic Commands**
   - Implement `configure` command with interactive prompts
   - Create `init` command for SSO setup and account discovery
   - Add `roles` command for role enumeration
   - Implement `profiles` command for AWS profile generation

2. **Profile Management**
   - AWS config file parsing and manipulation
   - Profile conflict detection and resolution
   - Profile cleanup functionality

### Phase 4: Command Execution
1. **Command Executor**
   - Implement AWS CLI command execution
   - Add parallel and sequential execution modes
   - Create command validation (read-only vs destructive)
   - Implement error handling and threshold management

2. **Output Management**
   - Create output pattern substitution
   - Implement file format handling (JSON, YAML, etc.)
   - Add output directory management
   - Create error file logging

### Phase 5: Advanced Features
1. **Error Handling & Logging**
   - Comprehensive error logging system
   - Error file generation with timestamps
   - Console output formatting
   - Error threshold implementation

2. **Cleanup & Maintenance**
   - Profile cleanup command
   - Cache management
   - Configuration validation
   - Account status updates

## Key Dependencies
```python
# requirements.txt
boto3>=1.26.0
click>=8.0.0
configparser>=5.0.0
pyyaml>=6.0
colorama>=0.4.0
tabulate>=0.9.0
concurrent.futures  # Built-in
```

## Development Priorities

### Critical Components (Must Have)
1. Configuration management system
2. SSO authentication and token handling
3. Account discovery and management
4. Basic CLI command structure
5. AWS profile generation

### Important Components (Should Have)
1. Parallel command execution
2. Error handling and logging
3. Command validation system
4. Output formatting and patterns
5. Profile conflict resolution

### Nice to Have Components (Could Have)
1. Advanced caching mechanisms
2. Interactive mode improvements
3. Detailed progress reporting
4. Command history tracking

## Testing Strategy
- Unit tests for each module
- Integration tests for AWS operations
- CLI command testing with mock data
- Error scenario testing
- Performance testing for parallel execution

## Security Considerations
- Secure token storage
- Configuration file permissions
- Command validation to prevent destructive operations
- Audit logging for command execution
- SSO session management