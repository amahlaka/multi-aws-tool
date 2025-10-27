# standalone script to parse IAM reports and output information on which users have valid credentials but have been inactive for a specified period.
# reads csv files from a given directory and outputs a summary report in human-readable format, the files are already decoded from base64 to csv format.

import csv
import json
import base64
from datetime import datetime, timedelta
import os
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional


class IAMUser:
    """Represents an IAM user with their credential information."""
    
    def __init__(self, row: Dict[str, str], account_id: str):
        self.account_id = account_id
        self.user = row['user']
        self.arn = row['arn']
        self.user_creation_time = self._parse_date(row['user_creation_time'])
        self.password_enabled = row['password_enabled'].lower() == 'true'
        self.password_last_used = self._parse_date(row['password_last_used'])
        self.password_last_changed = self._parse_date(row['password_last_changed'])
        self.mfa_active = row['mfa_active'].lower() == 'true'
        self.access_key_1_active = row['access_key_1_active'].lower() == 'true'
        self.access_key_1_last_used = self._parse_date(row['access_key_1_last_used_date'])
        self.access_key_1_last_rotated = self._parse_date(row['access_key_1_last_rotated'])
        self.access_key_2_active = row['access_key_2_active'].lower() == 'true'
        self.access_key_2_last_used = self._parse_date(row['access_key_2_last_used_date'])
        self.access_key_2_last_rotated = self._parse_date(row['access_key_2_last_rotated'])
        
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse ISO date string to datetime object."""
        if not date_str or date_str in ['N/A', 'no_information']:
            return None
        try:
            # Parse and convert to naive datetime (remove timezone info for consistent comparison)
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.replace(tzinfo=None)
        except ValueError:
            return None
    
    def has_valid_credentials(self) -> bool:
        """Check if user has any valid/active credentials."""
        return (self.password_enabled or 
                self.access_key_1_active or 
                self.access_key_2_active)
    
    def get_last_activity_date(self) -> Optional[datetime]:
        """Get the most recent activity date across all credential types."""
        dates = [
            self.password_last_used,
            self.access_key_1_last_used,
            self.access_key_2_last_used
        ]
        valid_dates = [d for d in dates if d is not None]
        return max(valid_dates) if valid_dates else None
    
    def is_inactive_for_days(self, days: int) -> bool:
        """Check if user has been inactive for specified number of days."""
        last_activity = self.get_last_activity_date()
        if last_activity is None:
            # If no activity recorded, consider as inactive since creation
            if self.user_creation_time:
                return (datetime.now() - self.user_creation_time).days >= days
            return True
        
        return (datetime.now() - last_activity).days >= days
    
    def get_credential_summary(self) -> Dict[str, str]:
        """Get a summary of the user's credentials."""
        return {
            'password_enabled': 'Yes' if self.password_enabled else 'No',
            'password_last_used': self.password_last_used.strftime('%Y-%m-%d') if self.password_last_used else 'Never',
            'mfa_active': 'Yes' if self.mfa_active else 'No',
            'access_key_1_active': 'Yes' if self.access_key_1_active else 'No',
            'access_key_1_last_used': self.access_key_1_last_used.strftime('%Y-%m-%d') if self.access_key_1_last_used else 'Never',
            'access_key_2_active': 'Yes' if self.access_key_2_active else 'No',
            'access_key_2_last_used': self.access_key_2_last_used.strftime('%Y-%m-%d') if self.access_key_2_last_used else 'Never',
        }


class ExecutionSummaryProcessor:
    """Processes execution summary JSON files to extract and decode IAM credential reports."""
    
    def __init__(self, execution_summary_file: str, output_directory: str = None):
        """Initialize the execution summary processor."""
        self.execution_summary_file = Path(execution_summary_file)
        self.output_directory = Path(output_directory) if output_directory else self.execution_summary_file.parent
        self.processed_files = []
    
    def process_execution_summary(self) -> List[str]:
        """
        Process execution summary JSON and create CSV files.
        
        Returns:
            List of created CSV file paths
        """
        try:
            with open(self.execution_summary_file, 'r') as f:
                execution_data = json.load(f)
            
            print(f"Processing execution summary: {self.execution_summary_file.name}")
            
            for entry in execution_data:
                if (entry.get('status') == 'success' and 
                    entry.get('command') == 'iam get-credential-report' and
                    entry.get('output')):
                    
                    self._process_iam_report_entry(entry)
            
            print(f"Created {len(self.processed_files)} CSV files from execution summary")
            return self.processed_files
            
        except Exception as e:
            print(f"Error processing execution summary {self.execution_summary_file}: {e}")
            return []
    
    def _process_iam_report_entry(self, entry: Dict) -> None:
        """Process a single IAM report entry from execution summary."""
        try:
            account_id = entry['account_id']
            output_data = json.loads(entry['output'])
            
            # Decode base64 content
            if 'Content' in output_data:
                csv_content = base64.b64decode(output_data['Content']).decode('utf-8')
                
                # Create CSV file
                csv_filename = f"iam_report_{account_id}.csv"
                csv_filepath = self.output_directory / csv_filename
                
                with open(csv_filepath, 'w', newline='', encoding='utf-8') as f:
                    f.write(csv_content)
                
                self.processed_files.append(str(csv_filepath))
                print(f"  Created: {csv_filename}")
                
        except Exception as e:
            print(f"Error processing entry for account {entry.get('account_id', 'unknown')}: {e}")


class AccountNameResolver:
    """Resolves AWS account IDs to friendly names from accounts.json file."""
    
    def __init__(self, accounts_file_path: str = None):
        """Initialize the account name resolver."""
        if accounts_file_path:
            self.accounts_file = Path(accounts_file_path)
        else:
            self.accounts_file = Path.home() / '.multi-aws' / 'accounts.json'
        
        self.account_names = {}
        self._load_account_names()
    
    def _load_account_names(self) -> None:
        """Load account names from the JSON file."""
        try:
            if self.accounts_file.exists():
                with open(self.accounts_file, 'r') as f:
                    data = json.load(f)
                    
                # Handle the specific accounts.json structure
                if isinstance(data, dict) and 'accounts' in data:
                    # Structure: {"accounts": [{"id": "123", "name": "account-name", "status": "active", ...}, ...]}
                    for account in data['accounts']:
                        if isinstance(account, dict) and 'id' in account and 'name' in account:
                            self.account_names[account['id']] = account['name']
                            
                print(f"Loaded {len(self.account_names)} account names from {self.accounts_file}")
            else:
                print(f"Account names file not found at {self.accounts_file}")
        except Exception as e:
            print(f"Warning: Could not load account names from {self.accounts_file}: {e}")
    
    def get_account_name(self, account_id: str) -> str:
        """Get the friendly name for an account ID, or return the ID if name not found."""
        return self.account_names.get(account_id, account_id)
    
    def get_account_display_name(self, account_id: str) -> str:
        """Get display name in format 'name (id)' or just 'id' if name not found."""
        name = self.account_names.get(account_id)
        if name and name != account_id:
            return f"{name} ({account_id})"
        return account_id


class IAMReportParser:
    """Main class for parsing IAM credential reports."""
    
    def __init__(self, reports_directory: str, accounts_file: str = None, execution_summary_file: str = None):
        self.reports_directory = Path(reports_directory)
        self.users: List[IAMUser] = []
        self.account_resolver = AccountNameResolver(accounts_file)
        self.execution_summary_file = execution_summary_file
        
    def load_reports(self) -> None:
        """Load all CSV reports from the directory."""
        # First, process execution summary if provided
        if self.execution_summary_file:
            self._process_execution_summary()
        
        csv_files = list(self.reports_directory.glob("iam_report_*.csv"))
        
        if not csv_files:
            print(f"No IAM report CSV files found in {self.reports_directory}")
            return
            
        print(f"Found {len(csv_files)} IAM report files")
        
        for csv_file in csv_files:
            account_id = self._extract_account_id(csv_file.name)
            self._load_csv_file(csv_file, account_id)
    
    def _process_execution_summary(self) -> None:
        """Process execution summary file to create CSV files."""
        if not self.execution_summary_file:
            return
            
        execution_summary_path = Path(self.execution_summary_file)
        if not execution_summary_path.exists():
            print(f"Execution summary file not found: {self.execution_summary_file}")
            return
        
        processor = ExecutionSummaryProcessor(
            self.execution_summary_file, 
            str(self.reports_directory)
        )
        created_files = processor.process_execution_summary()
        
        if created_files:
            print(f"Processed execution summary and created {len(created_files)} CSV files")
    
    def _extract_account_id(self, filename: str) -> str:
        """Extract AWS account ID from filename."""
        # Filename format: iam_report_<account_id>.csv
        return filename.replace('iam_report_', '').replace('.csv', '')
    
    def _load_csv_file(self, csv_file: Path, account_id: str) -> None:
        """Load users from a single CSV file."""
        try:
            with open(csv_file, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    user = IAMUser(row, account_id)
                    self.users.append(user)
            print(f"Loaded {csv_file.name} - Account: {account_id}")
        except Exception as e:
            print(f"Error loading {csv_file}: {e}")
    
    def find_inactive_users_with_credentials(self, inactive_days: int = 90) -> List[IAMUser]:
        """Find users with valid credentials who have been inactive for specified days."""
        inactive_users = []
        
        for user in self.users:
            if (user.has_valid_credentials() and 
                user.is_inactive_for_days(inactive_days) and
                user.user != '<root_account>'):  # Exclude root account
                inactive_users.append(user)
        
        return inactive_users
    
    def generate_summary_report(self, inactive_days: int = 90) -> Dict:
        """Generate a comprehensive summary report."""
        inactive_users = self.find_inactive_users_with_credentials(inactive_days)
        
        # Group by account
        accounts = {}
        for user in inactive_users:
            if user.account_id not in accounts:
                accounts[user.account_id] = []
            accounts[user.account_id].append(user)
        
        # Calculate statistics
        total_users = len([u for u in self.users if u.user != '<root_account>'])
        users_with_credentials = len([u for u in self.users if u.has_valid_credentials() and u.user != '<root_account>'])
        
        return {
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'inactive_threshold_days': inactive_days,
            'total_accounts': len(set(u.account_id for u in self.users)),
            'total_users': total_users,
            'users_with_credentials': users_with_credentials,
            'inactive_users_with_credentials': len(inactive_users),
            'accounts': accounts
        }
    
    def print_human_readable_report(self, inactive_days: int = 90) -> None:
        """Print a human-readable report to console."""
        report = self.generate_summary_report(inactive_days)
        
        print("\n" + "="*80)
        print("AWS IAM CREDENTIAL ANALYSIS REPORT")
        print("="*80)
        print(f"Analysis Date: {report['analysis_date']}")
        print(f"Inactive Threshold: {report['inactive_threshold_days']} days")
        print(f"Total AWS Accounts: {report['total_accounts']}")
        print(f"Total Users (excluding root): {report['total_users']}")
        print(f"Users with Active Credentials: {report['users_with_credentials']}")
        print(f"Inactive Users with Credentials: {report['inactive_users_with_credentials']}")
        
        if report['inactive_users_with_credentials'] == 0:
            print("\n✅ No inactive users with valid credentials found!")
            return
        
        print(f"\n⚠️  Found {report['inactive_users_with_credentials']} inactive users with valid credentials:")
        print("-"*80)
        
        for account_id, users in report['accounts'].items():
            account_display = self.account_resolver.get_account_display_name(account_id)
            print(f"\nAccount: {account_display} ({len(users)} users)")
            print("-" * 50)
            
            for user in users:
                last_activity = user.get_last_activity_date()
                days_inactive = (datetime.now() - last_activity).days if last_activity else "Unknown"
                
                print(f"  👤 User: {user.user}")
                print(f"     ARN: {user.arn}")
                print(f"     Created: {user.user_creation_time.strftime('%Y-%m-%d') if user.user_creation_time else 'Unknown'}")
                print(f"     Last Activity: {last_activity.strftime('%Y-%m-%d') if last_activity else 'Never'}")
                print(f"     Days Inactive: {days_inactive}")
                
                creds = user.get_credential_summary()
                print(f"     Password: {creds['password_enabled']} (Last used: {creds['password_last_used']})")
                print(f"     MFA: {creds['mfa_active']}")
                print(f"     Access Key 1: {creds['access_key_1_active']} (Last used: {creds['access_key_1_last_used']})")
                print(f"     Access Key 2: {creds['access_key_2_active']} (Last used: {creds['access_key_2_last_used']})")
                print()
    
    def export_json_report(self, output_file: str, inactive_days: int = 90) -> None:
        """Export report as JSON file."""
        report = self.generate_summary_report(inactive_days)
        
        # Convert IAMUser objects to dictionaries for JSON serialization
        json_report = {
            'analysis_date': report['analysis_date'],
            'inactive_threshold_days': report['inactive_threshold_days'],
            'total_accounts': report['total_accounts'],
            'total_users': report['total_users'],
            'users_with_credentials': report['users_with_credentials'],
            'inactive_users_with_credentials': report['inactive_users_with_credentials'],
            'accounts': {}
        }
        
        for account_id, users in report['accounts'].items():
            account_info = {
                'account_id': account_id,
                'account_name': self.account_resolver.get_account_name(account_id),
                'users': []
            }
            for user in users:
                user_data = {
                    'user': user.user,
                    'arn': user.arn,
                    'account_id': user.account_id,
                    'user_creation_time': user.user_creation_time.isoformat() if user.user_creation_time else None,
                    'last_activity_date': user.get_last_activity_date().isoformat() if user.get_last_activity_date() else None,
                    'days_inactive': (datetime.now() - user.get_last_activity_date()).days if user.get_last_activity_date() else None,
                    'credentials': user.get_credential_summary()
                }
                account_info['users'].append(user_data)
            
            json_report['accounts'][account_id] = account_info
        
        with open(output_file, 'w') as f:
            json.dump(json_report, f, indent=2)
        
        print(f"JSON report exported to: {output_file}")


def main():
    """Main function with command line argument parsing."""
    parser = argparse.ArgumentParser(
        description='Analyze AWS IAM credential reports to find inactive users with valid credentials'
    )
    
    parser.add_argument(
        'directory',
        nargs='?',
        default='./iam',
        help='Directory containing IAM report CSV files (default: ./iam)'
    )
    
    parser.add_argument(
        '--days',
        type=int,
        default=90,
        help='Number of days to consider a user inactive (default: 90)'
    )
    
    parser.add_argument(
        '--json',
        type=str,
        help='Export results to JSON file'
    )
    
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Only output summary statistics'
    )
    
    parser.add_argument(
        '--accounts-file',
        type=str,
        help='Path to accounts.json file for account name resolution (default: ~/.multi-aws/accounts.json)'
    )
    
    parser.add_argument(
        '--execution-summary',
        type=str,
        help='Path to execution summary JSON file to process and extract CSV reports from'
    )
    
    args = parser.parse_args()
    
    # Check if directory exists
    if not os.path.exists(args.directory):
        print(f"Error: Directory '{args.directory}' does not exist")
        sys.exit(1)
    
    # Initialize parser and load reports
    parser_instance = IAMReportParser(args.directory, args.accounts_file, args.execution_summary)
    parser_instance.load_reports()
    
    if not parser_instance.users:
        print("No users loaded from reports")
        sys.exit(1)
    
    # Generate and display report
    if not args.quiet:
        parser_instance.print_human_readable_report(args.days)
    else:
        report = parser_instance.generate_summary_report(args.days)
        print(f"Total Users: {report['total_users']}")
        print(f"Users with Credentials: {report['users_with_credentials']}")
        print(f"Inactive Users with Credentials: {report['inactive_users_with_credentials']}")
    
    # Export JSON if requested
    if args.json:
        parser_instance.export_json_report(args.json, args.days)


if __name__ == "__main__":
    main()