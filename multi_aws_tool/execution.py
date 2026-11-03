"""
Library API for running AWS CLI commands across multiple accounts and regions.

This is the programmatic counterpart of ``multi-aws run``: instead of printing
progress and writing files, :func:`execute` returns a
:class:`~multi_aws_tool.output.MultiAWSExecutionSummary` you can inspect directly.

Example::

    from multi_aws_tool import execute

    summary = execute(
        "sts get-caller-identity",
        accounts=["123456789012", "987654321098"],
        regions=["eu-west-1", "us-east-1"],
        parallel=True,
    )
    for result in summary.get_successful_results():
        print(result.account_id, result.region, result.output_json())

    summary.save("~/.multi-aws/outputs/")  # optional
"""

import logging
import shlex
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, Iterable, List, Optional, Sequence, Union

from .aws.account_manager import AccountManager, AccountManagerError
from .config.manager import ConfigManager
from .config.schema import is_destructive_command
from .models.account import Account
from .output import AccountResult, MultiAWSExecutionSummary

logger = logging.getLogger(__name__)

ALL_REGIONS = "all"


class ExecutionError(Exception):
    """Raised when an execution cannot be started (e.g. a blocked destructive command)."""


def _load_config() -> ConfigManager:
    """Load the user's config if present, without creating files as a side effect."""
    config_manager = ConfigManager()
    if config_manager.config_exists():
        config_manager.load_config()
    return config_manager


def _account_manager_from_config(config_manager: ConfigManager) -> AccountManager:
    return AccountManager(
        sso_session_name=config_manager.get('general', 'sso-session', 'default'),
        region=config_manager.get('general', 'region', 'us-east-1'),
        account_file_path=config_manager.get('general', 'account-file', '~/.multi-aws/accounts.json'),
        profile_prefix=config_manager.get('general', 'prefix', 'multi-aws'),
    )


def _list_enabled_regions(account_manager: AccountManager, account_id: str,
                          role: Optional[str], default_region: str) -> List[str]:
    """Regions enabled for an account (opted-in or not requiring opt-in)."""
    session = account_manager.get_session(account_id, role=role, region=default_region)
    response = session.client('ec2').describe_regions(
        Filters=[{'Name': 'opt-in-status', 'Values': ['opt-in-not-required', 'opted-in']}]
    )
    return sorted(r['RegionName'] for r in response['Regions'])


def execute(
    command: Union[str, Sequence[str]],
    accounts: Iterable[Union[str, Account]],
    regions: Union[None, str, Sequence[str]] = None,
    parallel: bool = True,
    *,
    role: Optional[str] = None,
    timeout: int = 300,
    output_format: Optional[str] = None,
    max_workers: int = 10,
    allow_destructive: Optional[bool] = None,
    dry_run: bool = False,
    account_manager: Optional[AccountManager] = None,
    config_manager: Optional[ConfigManager] = None,
    on_result: Optional[Callable[[AccountResult], None]] = None,
) -> MultiAWSExecutionSummary:
    """
    Run an AWS CLI command across accounts and regions and return the results.

    Each (account, region) pair is one execution; ``summary.results`` holds one
    :class:`AccountResult` per pair and the summary counters count pairs.
    Accounts that are unknown or have no usable profile produce an ``ERROR``
    result instead of being silently skipped.

    Args:
        command: AWS CLI command without the leading ``aws``, either as a
            string (``"ec2 describe-instances --max-items 5"``, split with
            shell rules) or a list of arguments.
        accounts: Account IDs or :class:`Account` objects.
        regions: A region, a list of regions, ``"all"`` for every region
            enabled in the first account, or None for the configured default.
        parallel: Run pairs concurrently (up to ``max_workers`` threads).
        role: SSO role whose profile to use (see
            :meth:`AccountManager.get_profile_name`). Defaults to each
            account's stored profile.
        timeout: Per-execution timeout in seconds.
        output_format: AWS CLI ``--output`` value; defaults to the configured format.
        max_workers: Maximum concurrent executions when ``parallel`` is True.
        allow_destructive: Override the ``security.allow-destructive-commands``
            config setting.
        dry_run: Resolve accounts/profiles but don't run anything.
        account_manager: Account manager to use; built from config if omitted.
        config_manager: Config to use; the user's config file if omitted.
        on_result: Optional callback invoked with each result as it completes
            (called from worker threads when ``parallel`` is True).

    Returns:
        MultiAWSExecutionSummary with per-account results.

    Raises:
        ExecutionError: If the command is empty or destructive and not allowed.
        AccountManagerError: If ``regions="all"`` and regions can't be listed.
    """
    config_manager = config_manager or _load_config()
    account_manager = account_manager or _account_manager_from_config(config_manager)

    args = shlex.split(command) if isinstance(command, str) else list(command)
    if args and args[0] == 'aws':
        args = args[1:]
    if not args:
        raise ExecutionError("No command given")
    command_str = shlex.join(args)

    if allow_destructive is None:
        allow_destructive = config_manager.get_bool('security', 'allow-destructive-commands', False)
    if is_destructive_command(command_str) and not allow_destructive:
        raise ExecutionError(
            f"Command '{command_str}' is considered destructive. "
            "Pass allow_destructive=True or enable allow-destructive-commands in config."
        )

    default_region = config_manager.get('general', 'region', 'us-east-1')
    output_format = output_format or config_manager.get('output', 'format', 'json')

    resolved: List[Account] = []
    unknown_ids: List[str] = []
    for item in accounts:
        if isinstance(item, Account):
            resolved.append(item)
            continue
        account = account_manager.get_account(str(item))
        if account:
            resolved.append(account)
        else:
            unknown_ids.append(str(item))

    if regions is None:
        region_list = [default_region]
    elif isinstance(regions, str):
        if regions == ALL_REGIONS:
            region_list = (
                _list_enabled_regions(account_manager, resolved[0].id, role, default_region)
                if resolved else [default_region]
            )
        else:
            region_list = [regions]
    else:
        region_list = list(regions) or [default_region]

    # Resolve profiles once per account rather than once per (account, region)
    profiles = {
        acc.id: acc.profile_name if role is None else account_manager.get_profile_name(acc, role)
        for acc in resolved
    }

    def run_one(account: Account, region: str) -> AccountResult:
        profile_name = profiles[account.id]
        result = AccountResult(
            account_id=account.id,
            account_name=account.name,
            profile_name=profile_name,
            command=command_str,
            status='ERROR',
            region=region,
        )
        if not profile_name:
            result.error = (
                f"No AWS profile configured for role '{role}'" if role
                else "No AWS profile configured for this account"
            )
            return result

        aws_cmd = ['aws', '--profile', profile_name, '--region', region,
                   '--output', output_format, *args]
        if dry_run:
            result.status = 'SUCCESS'
            result.error = f"Dry run - not executed: {shlex.join(aws_cmd)}"
            return result

        start = time.monotonic()
        try:
            proc = subprocess.run(aws_cmd, capture_output=True, text=True, timeout=timeout)
            result.status = 'SUCCESS' if proc.returncode == 0 else 'ERROR'
            result.output = proc.stdout
            result.error = proc.stderr
            result.exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            result.status = 'TIMEOUT'
            result.error = f"Command timed out after {timeout} seconds"
        except Exception as e:  # e.g. aws CLI not installed
            logger.exception(f"Execution error for account {account.name} ({account.id})")
            result.error = str(e)
        result.execution_time = time.monotonic() - start
        return result

    def finish(result: AccountResult) -> AccountResult:
        if on_result:
            on_result(result)
        return result

    started_at = datetime.now()
    start = time.monotonic()
    pairs = [(acc, rgn) for acc in resolved for rgn in region_list]

    results: List[AccountResult] = [
        finish(AccountResult(
            account_id=account_id, account_name=None, profile_name=None,
            command=command_str, status='ERROR', region=rgn,
            error="Account not found in local account data",
        ))
        for account_id in unknown_ids for rgn in region_list
    ]

    if parallel and len(pairs) > 1:
        with ThreadPoolExecutor(max_workers=max(1, min(len(pairs), max_workers))) as pool:
            futures = [pool.submit(lambda p: finish(run_one(*p)), pair) for pair in pairs]
            results.extend(f.result() for f in futures)  # keeps input order
    else:
        results.extend(finish(run_one(acc, rgn)) for acc, rgn in pairs)

    return MultiAWSExecutionSummary(
        execution_id=f"{started_at.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
        command=command_str,
        timestamp=started_at.isoformat(),
        total_accounts=len(results),
        successful_accounts=sum(1 for r in results if r.status == 'SUCCESS'),
        failed_accounts=sum(1 for r in results if r.status == 'ERROR'),
        timeout_accounts=sum(1 for r in results if r.status == 'TIMEOUT'),
        execution_mode='parallel' if parallel else 'sequential',
        total_execution_time=time.monotonic() - start,
        results=results,
        config_used={
            'regions': region_list,
            'role': role,
            'output_format': output_format,
            'timeout': timeout,
            'dry_run': dry_run,
        },
    )
