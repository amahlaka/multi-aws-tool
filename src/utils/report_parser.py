# Parses iam credentials reports from the json response with base64 encoded content
import base64
import json
#from models.account import Account, AccountCollection, Role
from pathlib import Path
#from models.result import CommandResult,ExecutionSummary
import os


def parse_iam_report(report_b64: str) -> dict:
    """
    Parse IAM credentials report from AWS response

    Args:
        report_response: AWS response containing base64 encoded report
    Returns:
        Parsed IAM report as a dictionary   
    """

    # Decode base64 content
    decoded_bytes = base64.b64decode(report_b64)
    decoded_str = decoded_bytes.decode('utf-8')
    #with open(os.path.join(outputpath, name), 'w') as f:
    #    f.write(decoded_str)
    # report is in CSV format, convert to JSON-like dict
    #print(decoded_str)
    #print("Parsing CSV content...")
    lines = decoded_str.splitlines()
    headers = lines[0].split(',')
    report_data = {'Users': []}
    for line in lines[1:]:
        values = line.split(',')
        user_entry = {headers[i]: values[i] for i in range(len(headers))}
        report_data['Users'].append(user_entry)
    
    return report_data


def extract_user_credentials(report_data: dict) -> dict:
    """
    Extract user credentials information from IAM report data

    Args:
        report_data: Parsed IAM report data
    Returns:
        Dictionary mapping usernames to their credential details
    """
    user_credentials = {}
    #print(report_data.get('Users'))
    for entry in report_data.get('Users', []):
        username = entry.get('user')
        if not username:
            continue
        if username == '<root_account>':
            pass
        
        credentials_info = {
            'AccessKeys': [
                {'AccessKeyId': entry.get('access_key_1_active'),
                 'Status': entry.get('access_key_1_active'),
                 'LastUsedDate': entry.get('access_key_1_last_used_date')},
                {'AccessKeyId': entry.get('access_key_2_active'),
                 'Status': entry.get('access_key_2_active'),
                 'LastUsedDate': entry.get('access_key_2_last_used_date')}
            ],
            'Password': {
                'Enabled': entry.get('password_enabled', False),
                'LastChanged': entry.get('password_last_changed'),
                'LastUsed': entry.get('password_last_used')
            },
            'MFAEnabled': entry.get('mfa_active', False),
            'UserCreationDate': entry.get('user_creation_time'), 
        }
        
        user_credentials[username] = credentials_info
    
    return user_credentials

def summarize_inactive_credentials(user_credentials: dict, days_threshold: int) -> dict:
    """
    Summarize users with inactive credentials based on a days threshold

    Args:
        user_credentials: Dictionary of user credentials
        days_threshold: Number of days to consider credentials as inactive
    Returns:
        Dictionary of users with inactive credentials
    """
    from datetime import datetime, timedelta

    inactive_users = {}
    cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)
    for username, creds in user_credentials.items():
        pw_inactive = False
        ak_inactive = False
        # Check password last used
        # Sanity checks first, check if user has password enabled
    
        pwd_last_used_str = creds['Password'].get('LastUsed')
        if pwd_last_used_str and creds['Password'].get('Enabled'):
            # Handle both 'Z' and '+00:00' timezone formats
            if pwd_last_used_str == 'N/A':
                pw_inactive = True
                continue
            try:
                pwd_last_used = datetime.strptime(pwd_last_used_str, '%Y-%m-%dT%H:%M:%S+00:00')
            except ValueError:
                pwd_last_used = datetime.strptime(pwd_last_used_str, '%Y-%m-%dT%H:%M:%SZ')
            if pwd_last_used < cutoff_date:
                pw_inactive = True
        else:
            pw_inactive = True  # Never used

        # Check access keys last used
        for ak in creds['AccessKeys']:
            ak_last_used_str = ak.get('LastUsedDate')
            if ak_last_used_str and ak.get('Status') == 'true':
                if ak_last_used_str == 'N/A':
                    ak_inactive = True
                    continue
                # Handle both 'Z' and '+00:00' timezone formats
                try:
                    ak_last_used = datetime.strptime(ak_last_used_str, '%Y-%m-%dT%H:%M:%S+00:00')
                except ValueError:
                    ak_last_used = datetime.strptime(ak_last_used_str, '%Y-%m-%dT%H:%M:%SZ')
                if ak_last_used < cutoff_date:
                    ak_inactive = True
            else:
                ak_inactive = True  # Never used

        if pw_inactive or ak_inactive:
            inactive_users[username] = {
                'PasswordInactive': pw_inactive,
                'AccessKeysInactive': ak_inactive,
            }
            print(f"User {username} inactive - Password: {pw_inactive}, Access Keys: {ak_inactive}")
    
    return inactive_users

def generate_credential_report_summary(user_credentials: dict) -> dict:
    """
    Generate a summary report of user credentials
    summary contains total users, users that have been inactive for a certain period, users that use passwords, users that use access keys, etc.
    this helps in finding which accounts have iam users that have not been used for a while but are still active

    Args:
        user_credentials: Dictionary of user credentials
    Returns:
        Summary report as a dictionary
    """



def get_from_file(file_path: str) -> dict:
    """
    Load IAM report data from a local JSON or YAML file

    Args:
        file_path: Path to the JSON or YAML file
    Returns:
        Parsed IAM report data as a dictionary
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(path, 'r') as f:
        if path.suffix in ['.json']:
            return json.load(f)
        elif path.suffix in ['.yaml', '.yml']:
            import yaml
            return yaml.safe_load(f)
        else:
            raise ValueError("Unsupported file format. Only JSON and YAML are supported.")

def process_multi(conts):
    for cont in conts:
        data = parse_iam_report(cont)
        user_creds = extract_user_credentials(data)
        print(user_creds)

def load_from_summary(file_path: str) -> dict:
    output = []
    file = open(file_path, 'r')
    file_content = file.read()
    file_data = json.loads(file_content)
    #print(file_data)
    for entry in file_data:
        if 'output' in entry:
            output_data = json.loads(entry['output'])
            report_data = parse_iam_report(output_data['Content'])
            output.append({"account_id": entry.get("account_id"), "report": report_data})
    return output


