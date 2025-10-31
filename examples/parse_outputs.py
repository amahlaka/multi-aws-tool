#!/usr/bin/env python3
"""
Example: Using MultiAWSTool Output Parser

This example shows how to use the MultiAWSTool output parsing module
to analyze command execution results in other tools.
"""

import json
from pathlib import Path
from multi_aws_tool.output import (
    OutputParser,
    OutputAnalyzer, 
    parse_execution_summary,
    analyze_execution_summary
)

def main():
    """Example usage of MultiAWSTool output parsing"""
    
    # Example 1: Quick parsing of execution summary
    print("📊 Example 1: Quick Execution Summary Parsing")
    print("=" * 50)
    
    # Assuming you have an execution summary file
    output_dir = Path("./outputs")  # Adjust to your output directory
    
    try:
        # Find the latest execution summary
        parser = OutputParser(output_dir)
        summary_files = parser.find_execution_summaries()
        
        if summary_files:
            latest_summary = max(summary_files, key=lambda p: p.stat().st_mtime)
            print(f"📄 Parsing: {latest_summary.name}")
            
            # Parse using convenience function
            summary = parse_execution_summary(latest_summary)
            
            print(f"✅ Command: {summary.command}")
            print(f"📅 Executed: {summary.timestamp}")
            print(f"🏢 Total Accounts: {summary.total_accounts}")
            print(f"✅ Successful: {summary.successful_accounts}")
            print(f"❌ Failed: {summary.failed_accounts}")
            print(f"⏰ Timeouts: {summary.timeout_accounts}")
            print(f"📈 Success Rate: {summary.success_rate:.1f}%")
            print(f"⏱️  Total Time: {summary.total_execution_time:.2f}s")
            
            # Show failed accounts
            failed_results = summary.get_failed_results()
            if failed_results:
                print(f"\n❌ Failed Accounts:")
                for result in failed_results:
                    print(f"  • {result.account_name or result.account_id}: {result.error}")
        else:
            print("ℹ️  No execution summary files found")
    
    except Exception as e:
        print(f"⚠️  Could not parse execution summary: {e}")
    
    # Example 2: Detailed analysis
    print(f"\n📈 Example 2: Detailed Analysis")
    print("=" * 50)
    
    try:
        if summary_files:
            # Analyze using convenience function
            analysis = analyze_execution_summary(latest_summary)
            
            print(f"📊 Performance Analysis:")
            print(f"  • Average time per account: {analysis['overview']['avg_time_per_account']:.2f}s")
            print(f"  • Fastest account: {analysis['performance']['fastest_account']['account_id']} ({analysis['performance']['fastest_account']['time']:.2f}s)")
            print(f"  • Slowest account: {analysis['performance']['slowest_account']['account_id']} ({analysis['performance']['slowest_account']['time']:.2f}s)")
            
            if analysis['errors']['error_patterns']:
                print(f"\n🚨 Error Patterns:")
                for error_type, count in analysis['errors']['error_patterns'].items():
                    print(f"  • {error_type}: {count} occurrences")
            
            if analysis['recommendations']:
                print(f"\n💡 Recommendations:")
                for rec in analysis['recommendations']:
                    print(f"  • {rec}")
    
    except Exception as e:
        print(f"⚠️  Could not analyze execution: {e}")
    
    # Example 3: Working with individual account outputs
    print(f"\n📁 Example 3: Individual Account Outputs")
    print("=" * 50)
    
    try:
        if output_dir.exists():
            # Find account-specific output files
            account_files = parser.find_account_outputs()
            non_summary_files = [f for f in account_files if not f.name.startswith('execution_summary_')]
            
            if non_summary_files:
                print(f"Found {len(non_summary_files)} account output files:")
                
                for file_path in non_summary_files[:3]:  # Show first 3
                    print(f"\n📄 {file_path.name}")
                    
                    try:
                        output_data = parser.parse_account_output(file_path)
                        
                        if isinstance(output_data, dict):
                            if 'content' in output_data:
                                # Text file
                                content = output_data['content'][:200]  # First 200 chars
                                print(f"  Content preview: {content}...")
                            else:
                                # JSON file
                                print(f"  Keys: {list(output_data.keys())}")
                                if 'ResponseMetadata' in output_data:
                                    print(f"  AWS Response: {output_data.get('ResponseMetadata', {}).get('HTTPStatusCode', 'Unknown')}")
                    except Exception as e:
                        print(f"  ⚠️  Could not parse: {e}")
            else:
                print("ℹ️  No individual account output files found")
    
    except Exception as e:
        print(f"⚠️  Could not process account outputs: {e}")
    
    # Example 4: Creating custom reports
    print(f"\n📋 Example 4: Custom Report Generation")
    print("=" * 50)
    
    try:
        if summary_files:
            # Generate a custom report
            custom_report = {
                'report_generated': '2025-10-31T12:00:00',
                'summary': {
                    'total_executions': len(summary_files),
                    'latest_execution': {
                        'file': latest_summary.name,
                        'success_rate': summary.success_rate,
                        'total_accounts': summary.total_accounts
                    }
                },
                'account_performance': []
            }
            
            # Add account performance data
            for result in summary.results[:5]:  # Top 5 accounts
                custom_report['account_performance'].append({
                    'account_id': result.account_id,
                    'account_name': result.account_name,
                    'status': result.status,
                    'execution_time': result.execution_time
                })
            
            print("📊 Custom Report Generated:")
            print(json.dumps(custom_report, indent=2))
    
    except Exception as e:
        print(f"⚠️  Could not generate custom report: {e}")
    
    # Example 5: Filtering and querying results
    print(f"\n🔍 Example 5: Filtering and Querying")
    print("=" * 50)
    
    try:
        if summary_files:
            # Filter results by criteria
            slow_accounts = [r for r in summary.results if r.execution_time > 10.0]
            if slow_accounts:
                print(f"🐌 Slow accounts (>10s):")
                for result in slow_accounts:
                    print(f"  • {result.account_name or result.account_id}: {result.execution_time:.2f}s")
            
            # Find accounts with specific errors
            access_denied_accounts = [r for r in summary.results if r.error and 'AccessDenied' in r.error]
            if access_denied_accounts:
                print(f"\n🚫 Accounts with AccessDenied errors:")
                for result in access_denied_accounts:
                    print(f"  • {result.account_name or result.account_id}")
            
            # Success rate by account name pattern (if account names follow patterns)
            prod_accounts = [r for r in summary.results if r.account_name and 'prod' in r.account_name.lower()]
            if prod_accounts:
                prod_success_rate = (sum(1 for r in prod_accounts if r.is_success()) / len(prod_accounts)) * 100
                print(f"\n🏭 Production accounts success rate: {prod_success_rate:.1f}%")
    
    except Exception as e:
        print(f"⚠️  Could not filter results: {e}")


if __name__ == "__main__":
    main()