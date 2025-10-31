# CSV Module for MAT Parse
"""
This tool takes in a MultiAWSTool execution summary JSON file, and for each entry, it checks if the output is a json string that has the "Content" key, containing Base64-encoded CSV data. It decodes this data and writes it to a CSV file named after the account ID in the specified directory.
"""

import os
import json
import base64
import csv
from pathlib import Path
from typing import Optional
def extract_csv_from_execution_summary(execution_summary_path: Path, output_directory: Path) -> None:
    """Extract CSV data from MultiAWSTool execution summary JSON file.
    
    Args:
        execution_summary_path (Path): Path to the execution summary JSON file.
        output_directory (Path): Directory to save the extracted CSV files.
    """
    # Ensure output directory exists
    output_directory.mkdir(parents=True, exist_ok=True)
    
    # Load execution summary JSON
    with execution_summary_path.open('r') as f:
        summary_data = json.load(f)
    
    # Process each command result
    for result in summary_data:
        account_id = result.get('account_id')
        team = result.get('team', 'None')
        output_data = result.get('output')
        
        if not account_id or not output_data:
            continue
        
        try:
            output_json = json.loads(output_data)
            csv_base64 = output_json.get('Content')
            
            if not csv_base64:
                print(f"No 'Content' key found for account {account_id}. Skipping.")
                continue
            
            # Decode Base64 CSV data
            csv_bytes = base64.b64decode(csv_base64)
            csv_text = csv_bytes.decode('utf-8')
            
            # Write to CSV file
            csv_file_path = output_directory / f"{account_id}.csv"
            with csv_file_path.open('w', newline='') as csv_file:
                csv_file.write(csv_text)
            
            print(f"Extracted CSV for account {account_id} to {csv_file_path}")
        
        except (json.JSONDecodeError, base64.binascii.Error) as e:
            print(f"Error processing account {account_id}: {e}")
