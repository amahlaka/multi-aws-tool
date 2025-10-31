# Using MultiAWSTool as a Library

MultiAWSTool can be used as a Python library in other projects to manage AWS accounts and SSO authentication programmatically.

## Installation

### From Source (Development)
```bash
# Clone the repository
git clone <repository-url>
cd MultiAWSTool

# Install in development mode
pip install -e .
```

### From PyPI (when published)
```bash
pip install multi-aws-tool
```

## Quick Start

```python
from multi_aws_tool import AccountManager, ConfigManager

# Initialize with default configuration
config_manager = ConfigManager()
config = config_manager.load_config()

# Create account manager
account_manager = AccountManager(
    sso_session_name=config.sso_session,
    region=config.region
)

# Discover accounts
accounts = account_manager.discover_accounts()

# Access account data
for account in accounts.accounts:
    print(f"Account: {account.name} ({account.id})")
    print(f"Status: {account.status.value}")
    print(f"Roles: {[role.name for role in account.roles]}")
```

## Key Classes

### AccountManager
Main class for managing AWS accounts and SSO authentication.

```python
from multi_aws_tool import AccountManager

# Initialize
manager = AccountManager(
    sso_session_name="my-sso-session",
    region="us-east-1"
)

# Discover accounts
accounts = manager.discover_accounts(force_refresh=True)

# Get roles for specific accounts
roles = manager.get_account_roles(["123456789012"])

# Create AWS profiles
manager.create_aws_profiles(
    account_ids=["123456789012"], 
    role_names=["PowerUserAccess"]
)
```

### ConfigManager
Handles configuration file management.

```python
from multi_aws_tool import ConfigManager

# Initialize with custom config path
config_manager = ConfigManager("/path/to/custom/config.ini")

# Load configuration
config = config_manager.load_config()

# Update configuration
config_manager.update_setting("general", "region", "eu-west-1")
config_manager.save_config()
```

### SSOClient
Direct access to AWS SSO operations.

```python
from multi_aws_tool import SSOClient

# Initialize SSO client
sso = SSOClient("my-sso-session", "us-east-1")

# Authenticate
sso.authenticate()

# Get access token
token = sso.get_access_token()

# List accounts
accounts = sso.list_accounts()
```

## Data Models

### Account
```python
from multi_aws_tool import Account, AccountStatus

# Account object properties
account.id          # Account ID (string)
account.name        # Account name (string)  
account.status      # AccountStatus enum (ACTIVE, DISABLED, etc.)
account.roles       # List of Role objects
account.profile_name # AWS CLI profile name
account.last_updated # datetime
```

### AccountCollection
```python
from multi_aws_tool import AccountCollection

# Collection properties
collection.accounts            # List of Account objects
collection.discovery_timestamp # datetime of last discovery
collection.total_accounts      # Total number of accounts

# Collection methods
collection.get_account_by_id("123456789012")
collection.get_accounts_by_status(AccountStatus.ACTIVE)
collection.filter_accounts(lambda acc: "prod" in acc.name.lower())
```

### Role
```python
from multi_aws_tool import Role

# Role object properties
role.name        # Role name (string)
role.arn         # Full ARN (string)
role.description # Role description (string)
```

## Configuration

MultiAWSTool uses a configuration file located at `~/.multi-aws/config.ini` by default.

### Configuration Structure
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

[logging]
level = INFO
file = ~/.multi-aws/logs/multi-aws.log
```

### Programmatic Configuration
```python
from multi_aws_tool import ConfigManager

config_manager = ConfigManager()

# Update settings
config_manager.update_setting("general", "region", "eu-west-1")
config_manager.update_setting("security", "allow-destructive-commands", "true")

# Save changes
config_manager.save_config()
```

## Error Handling

```python
from multi_aws_tool import (
    AccountManagerError,
    SSOAuthenticationError,
    ConfigurationError,
    AccountDataError
)

try:
    accounts = account_manager.discover_accounts()
except SSOAuthenticationError:
    print("SSO authentication failed - run 'multi-aws init' to re-authenticate")
except AccountManagerError as e:
    print(f"Account management error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## Advanced Usage

### Custom Account Filtering
```python
# Filter accounts by name pattern
prod_accounts = [
    acc for acc in accounts.accounts 
    if "prod" in acc.name.lower() and acc.status.value == "ACTIVE"
]

# Filter by available roles
power_user_accounts = [
    acc for acc in accounts.accounts
    if any(role.name == "PowerUserAccess" for role in acc.roles)
]
```

### Working with AWS Profiles
```python
# Create profiles for specific accounts and roles
account_manager.create_aws_profiles(
    account_ids=["123456789012", "987654321098"],
    role_names=["PowerUserAccess", "ReadOnlyAccess"]
)

# Use generated profile names
for account in accounts.accounts:
    profile_name = account.profile_name
    print(f"Use: aws --profile {profile_name} sts get-caller-identity")
```

### Parallel Operations
```python
import concurrent.futures
from multi_aws_tool import AccountManager

def process_account(account):
    """Process a single account"""
    # Your account processing logic here
    return f"Processed {account.name}"

# Process accounts in parallel
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = [
        executor.submit(process_account, account) 
        for account in accounts.accounts
    ]
    
    results = [future.result() for future in futures]
```

## Integration Examples

### Django Integration
```python
# settings.py
from multi_aws_tool import ConfigManager

config_manager = ConfigManager()
AWS_CONFIG = config_manager.load_config()

# views.py
from multi_aws_tool import AccountManager
from django.http import JsonResponse

def get_aws_accounts(request):
    manager = AccountManager()
    accounts = manager.discover_accounts()
    
    account_data = [
        {
            "id": acc.id,
            "name": acc.name,
            "status": acc.status.value,
            "roles": [role.name for role in acc.roles]
        }
        for acc in accounts.accounts
    ]
    
    return JsonResponse({"accounts": account_data})
```

### Flask Integration
```python
from flask import Flask, jsonify
from multi_aws_tool import AccountManager

app = Flask(__name__)
account_manager = AccountManager()

@app.route('/api/accounts')
def get_accounts():
    try:
        accounts = account_manager.discover_accounts()
        return jsonify({
            "accounts": [
                {
                    "id": acc.id,
                    "name": acc.name,
                    "status": acc.status.value
                }
                for acc in accounts.accounts
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

## Best Practices

1. **Initialize once**: Create AccountManager and ConfigManager instances once and reuse them
2. **Handle authentication**: Always handle SSOAuthenticationError and prompt users to re-authenticate
3. **Cache management**: Use `force_refresh=False` (default) to leverage cached account data
4. **Error handling**: Wrap operations in try-catch blocks for robust error handling
5. **Configuration**: Use environment-specific configuration files for different deployments
6. **Logging**: Enable appropriate logging levels for debugging and monitoring

## Troubleshooting

### Common Issues

1. **SSO Authentication Failed**
   ```python
   # Solution: Re-authenticate
   sso_client.authenticate()
   ```

2. **Configuration Not Found**
   ```python
   # Solution: Create default configuration
   config_manager = ConfigManager()
   config_manager.create_default_config()
   ```

3. **Import Errors**
   ```bash
   # Solution: Install in development mode
   pip install -e .
   ```

For more examples, see `example_usage.py` in the project root.