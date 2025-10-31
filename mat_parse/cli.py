#!/usr/bin/env python3
"""
MAT Parse CLI - Command-line interface for MultiAWSTool parsers

This provides a unified CLI for various MultiAWSTool output parsers.
"""

import click
import sys
from pathlib import Path

@click.group()
@click.version_option()
def cli():
    """MAT Parse - MultiAWSTool Output Parser CLI
    
    A collection of parsers and analyzers for MultiAWSTool output files.
    """
    pass

@cli.command()
@click.argument('directory', default='./iam', type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option('--days', default=90, type=int, help='Number of days to consider a user inactive (default: 90)')
@click.option('--json', type=click.Path(), help='Export results to JSON file')
@click.option('--quiet', is_flag=True, help='Only output summary statistics')
@click.option('--accounts-file', type=click.Path(exists=True), help='Path to accounts.json file for account name resolution')
@click.option('--execution-summary', type=click.Path(exists=True), help='Path to execution summary JSON file to process')
def iam(directory, days, json, quiet, accounts_file, execution_summary):
    """Analyze AWS IAM credential reports to find inactive users with valid credentials.
    
    DIRECTORY: Directory containing IAM report CSV files (default: ./iam)
    """
    from mat_parse.iam import IAMReportParser
    
    # Initialize parser and load reports
    parser_instance = IAMReportParser(directory, accounts_file, execution_summary)
    parser_instance.load_reports()
    
    if not parser_instance.users:
        click.echo("No users loaded from reports", err=True)
        sys.exit(1)
    
    # Generate and display report
    if not quiet:
        parser_instance.print_human_readable_report(days)
    else:
        report = parser_instance.generate_summary_report(days)
        click.echo(f"Total Users: {report['total_users']}")
        click.echo(f"Users with Credentials: {report['users_with_credentials']}")
        click.echo(f"Inactive Users with Credentials: {report['inactive_users_with_credentials']}")
    
    # Export JSON if requested
    if json:
        parser_instance.export_json_report(str(json), days)
        click.echo(f"Results exported to: {json}")

@cli.command()
@click.argument('directory', default='./iam', type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option('--execution-summary', type=click.Path(exists=True), help='Path to execution summary JSON file to process')
def to_csv(directory, execution_summary):
    """Convert IAM report execution summary JSON outputs to CSV format.
    
    DIRECTORY: Directory to save the CSV report (default: ./iam)
    """
    from mat_parse.csv.csv import extract_csv_from_execution_summary
    
    output_dir = Path(directory)
    
    if not execution_summary:
        click.echo("Execution summary JSON file path is required", err=True)
        sys.exit(1)
    
    extract_csv_from_execution_summary(Path(execution_summary), output_dir)
    click.echo(f"CSV files extracted to: {directory}")


def main():
    """Entry point for mat-parse CLI"""
    cli()

if __name__ == "__main__":
    main()