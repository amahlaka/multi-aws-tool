"""
High-level multi-aws operations shared by the CLI, TUI and MCP server.

Every operation returns plain, JSON-friendly data instead of printing, so the
same logic backs ``multi-aws <command>``, the TUI and the MCP tools.

Example::

    from multi_aws_tool.services import MultiAWS

    ops = MultiAWS()
    print(ops.setup_status()["next_step"])
    ops.discover_accounts()
    ops.fetch_roles(ops.select_accounts(["all"]))
    ops.generate_profiles(ops.select_accounts(team="core"), role="ReadOnlyAccess")
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from .aws import profile_config
from .aws.account_manager import AccountManager, AccountManagerError
from .config.manager import ConfigManager, ConfigurationError
from .config.schema import DEFAULT_CONFIG, is_destructive_command
from .config.template_manager import TemplateError, get_template_manager
from .execution import _account_manager_from_config, _load_config, execute
from .models.account import Account, AccountCollection, Role
from .models.config import MultiAWSConfig
from .models.template import CommandTemplate
from .output import MultiAWSExecutionSummary
from .utils.validators import parse_account_list, sanitize_profile_name_component

logger = logging.getLogger(__name__)

# Serialises read-modify-write of the account data file across threads
# (MCP tools run in worker threads).
_data_lock = threading.RLock()

#: Config keys that change the safety posture; only the interactive CLI may set them.
PROTECTED_CONFIG_KEYS = {"security.allow-destructive-commands"}

#: Config keys that can be set in addition to the documented defaults.
EXTRA_CONFIG_KEYS = {"general.templates-file"}


class OperationError(Exception):
    """An operation could not be carried out (bad input or missing prerequisite)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_tags(tags: Union[None, Dict[str, str], Iterable[str]]) -> Dict[str, str]:
    """Accept a dict or ``KEY=VALUE`` strings."""
    if not tags:
        return {}
    if isinstance(tags, dict):
        return {str(k).strip(): str(v).strip() for k, v in tags.items()}
    result = {}
    for item in tags:
        if "=" not in item:
            raise OperationError(f"Invalid tag '{item}': use KEY=VALUE")
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def split_accounts(value: str) -> List[str]:
    """Comma-separated account IDs/names, or a .txt/.json file of account IDs."""
    value = value.strip()
    if value.endswith((".txt", ".json")):
        return parse_account_list(value)
    return [a.strip() for a in value.split(",") if a.strip()]


def account_to_dict(account: Account) -> Dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "status": account.status.value,
        "team": account.product_team,
        "tags": dict(account.tags),
        "roles": [role.name for role in account.roles],
        "profile": account.profile_name,
    }


def template_to_dict(tmpl: CommandTemplate) -> Dict[str, Any]:
    data = tmpl.to_dict()
    return {k: v for k, v in data.items() if v not in ("", None, [], 0) or k in ("name", "command")}


def summarize_execution(summary: MultiAWSExecutionSummary, max_output_chars: int) -> Dict[str, Any]:
    """
    Turn an execution summary into a compact, JSON-friendly result.

    Outputs are parsed as JSON when possible. The total output is capped at
    ``max_output_chars``, split evenly across results; truncated outputs are
    returned as raw text with ``output_truncated`` set.
    """
    results = summary.results
    budget = max(500, max_output_chars // max(1, len(results)))
    truncated = False
    items = []
    for r in results:
        item: Dict[str, Any] = {
            "account_id": r.account_id,
            "account_name": r.account_name,
            "region": r.region,
            "status": r.status,
        }
        output = (r.output or "").strip()
        if output:
            if len(output) > budget:
                item["output"] = output[:budget]
                item["output_truncated"] = True
                item["output_total_chars"] = len(output)
                truncated = True
            else:
                try:
                    item["output"] = json.loads(output)
                except ValueError:
                    item["output"] = output
        error = (r.error or "").strip()
        if error:
            item["error"] = error[:2000]
        if r.exit_code not in (None, 0):
            item["exit_code"] = r.exit_code
        items.append(item)

    return {
        "command": summary.command,
        "regions": summary.config_used.get("regions"),
        "role": summary.config_used.get("role"),
        "total": summary.total_accounts,
        "successful": summary.successful_accounts,
        "failed": summary.failed_accounts,
        "timed_out": summary.timeout_accounts,
        "execution_time_seconds": round(summary.total_execution_time, 2),
        "truncated": truncated,
        "results": items,
    }


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

class MultiAWS:
    """
    multi-aws operations bound to a config and account store.

    Args:
        config_manager: Config to use; the user's ``~/.multi-aws/config.ini`` if omitted.
        account_manager: Account manager; built from the config if omitted.
    """

    def __init__(self, config_manager: Optional[ConfigManager] = None,
                 account_manager: Optional[AccountManager] = None):
        self.config = config_manager or _load_config()
        self.accounts = account_manager or _account_manager_from_config(self.config)

    # -- basics -------------------------------------------------------------

    @property
    def prefix(self) -> str:
        return self.accounts.profile_prefix

    @property
    def sso_session(self) -> str:
        return self.accounts.sso_client.sso_session_name

    @property
    def region(self) -> str:
        return self.config.get("general", "region", "us-east-1")

    def _load(self) -> AccountCollection:
        return self.accounts.data_manager.load_accounts()

    def _save(self, collection: AccountCollection) -> None:
        self.accounts.data_manager.save_accounts(collection)

    def _require_login(self) -> None:
        if not self.accounts.is_authenticated():
            raise OperationError(
                f"SSO session '{self.sso_session}' is not logged in or has expired. "
                "Log in first (sso_login / 'aws sso login')."
            )

    def _resolve(self, collection: AccountCollection, account_ids: Sequence[str]):
        found, missing = [], []
        for account_id in account_ids:
            account = collection.get_account(str(account_id))
            (found if account else missing).append(account or str(account_id))
        return found, missing

    # -- account selection ----------------------------------------------------

    def select_accounts(
        self,
        accounts: Union[None, str, Sequence[str]] = None,
        team: Optional[str] = None,
        tags: Union[None, Dict[str, str], Iterable[str]] = None,
        include_inactive: bool = False,
    ) -> List[str]:
        """
        Resolve account selectors to account IDs (same rules as ``multi-aws run``).

        ``accounts`` takes IDs or exact account names (or a comma-separated
        string / ``file:`` path); ``"all"`` means every account. ``team`` may be
        comma-separated. ``tags`` narrows the selection, and on its own selects
        from all accounts. Inactive accounts are dropped unless
        ``include_inactive`` is set or they were named explicitly.
        """
        tags = parse_tags(tags)
        if isinstance(accounts, str):
            accounts = split_accounts(accounts)
        if not accounts and not team and not tags:
            raise OperationError("Specify accounts, team and/or tags to select accounts")

        all_accounts = self.accounts.get_accounts()
        by_id = {acc.id: acc for acc in all_accounts}
        selected: List[str] = []
        explicit: set = set()

        def add(account_id: str) -> None:
            if account_id not in selected:
                selected.append(account_id)

        for item in accounts or []:
            item = str(item).strip()
            if not item:
                continue
            if item.lower() == "all":
                for acc in all_accounts:
                    add(acc.id)
                continue
            if item in by_id or item.isdigit():
                add(item)  # unknown IDs are kept so callers can report them
                explicit.add(item)
                continue
            matches = [acc for acc in all_accounts if acc.name.lower() == item.lower()]
            if not matches:
                raise OperationError(f"No account with ID or name '{item}'")
            for acc in matches:
                add(acc.id)
                explicit.add(acc.id)

        if team:
            for team_name in (t.strip() for t in team.split(",")):
                if not team_name:
                    continue
                team_accounts = [a for a in all_accounts if a.product_team == team_name]
                if not team_accounts:
                    raise OperationError(f"No accounts in team '{team_name}'")
                for acc in team_accounts:
                    add(acc.id)

        if tags:
            tagged = {a.id for a in all_accounts if all(a.tags.get(k) == v for k, v in tags.items())}
            if not accounts and not team:
                selected = [acc.id for acc in all_accounts if acc.id in tagged]
            else:
                selected = [aid for aid in selected if aid in tagged]

        if not include_inactive:
            selected = [aid for aid in selected
                        if aid in explicit or aid not in by_id or by_id[aid].is_active()]

        if not selected:
            raise OperationError("The selection matched no accounts")
        return selected

    def list_accounts(
        self,
        team: Optional[str] = None,
        tags: Union[None, Dict[str, str], Iterable[str]] = None,
        role: Optional[str] = None,
        name_contains: Optional[str] = None,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        tags = parse_tags(tags)
        accounts = self.accounts.get_accounts()
        if team:
            teams = {t.strip() for t in team.split(",") if t.strip()}
            accounts = [a for a in accounts if a.product_team in teams]
        if tags:
            accounts = [a for a in accounts if all(a.tags.get(k) == v for k, v in tags.items())]
        if role:
            accounts = [a for a in accounts if a.has_role(role)]
        if name_contains:
            accounts = [a for a in accounts if name_contains.lower() in a.name.lower()]
        if not include_inactive:
            accounts = [a for a in accounts if a.is_active()]
        return [account_to_dict(a) for a in sorted(accounts, key=lambda a: a.name.lower())]

    # -- status / onboarding ---------------------------------------------------

    def setup_status(self) -> Dict[str, Any]:
        """
        Where the user is in the onboarding flow, with the next thing to do.

        Steps: AWS CLI installed -> multi-aws config -> SSO session in
        ~/.aws/config -> SSO login -> account discovery -> roles -> profiles.
        Teams and tags are optional extras.
        """
        aws_cli = shutil.which("aws")
        config_exists = self.config.config_exists()
        aws_text = profile_config.read_config()
        sessions = profile_config.list_sso_sessions(aws_text)
        session_ok = self.sso_session in sessions
        logged_in = session_ok and self.accounts.is_authenticated()
        try:
            accounts = self.accounts.get_accounts()
        except Exception:  # unreadable account file
            accounts = []
        active = [a for a in accounts if a.is_active()]
        with_roles = [a for a in active if a.roles]
        existing_profiles = set(profile_config.list_profiles(aws_text))
        with_profiles = [a for a in active if a.profile_name and a.profile_name in existing_profiles]
        role_counts = Counter(r.name for a in active for r in a.roles)

        steps = [
            {"step": "aws_cli", "done": bool(aws_cli),
             "detail": aws_cli or "AWS CLI v2 not found on PATH",
             "action": "Install AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"},
            {"step": "config", "done": config_exists,
             "detail": str(self.config.paths.config_file),
             "action": "Create the multi-aws config (update_config / 'multi-aws configure'); "
                       "choose a profile prefix and default region"},
            {"step": "sso_session", "done": session_ok,
             "detail": (f"Using SSO session '{self.sso_session}'" if session_ok else
                        f"SSO session '{self.sso_session}' not in {profile_config.aws_config_path()}; "
                        f"available: {sorted(sessions) or 'none'}"),
             "action": "Add your SSO session (add_sso_session) with your AWS access portal start URL "
                       "(https://<something>.awsapps.com/start) and its region, or pick an existing one"},
            {"step": "sso_login", "done": logged_in,
             "detail": "Logged in" if logged_in else "Not logged in or token expired",
             "action": "Log in (sso_login / 'aws sso login --sso-session <name>'); approve in the browser"},
            {"step": "accounts", "done": bool(active),
             "detail": f"{len(active)} active of {len(accounts)} known accounts",
             "action": "Discover accounts (discover_accounts / 'multi-aws init')"},
            {"step": "roles", "done": bool(with_roles),
             "detail": f"Roles fetched for {len(with_roles)}/{len(active)} active accounts",
             "action": "Fetch roles (fetch_roles / 'multi-aws roles')"},
            {"step": "profiles", "done": bool(with_profiles),
             "detail": f"{len(with_profiles)}/{len(active)} active accounts have a working AWS CLI profile",
             "action": "Generate profiles for a role (generate_profiles / 'multi-aws profiles'), "
                       "or sync existing ones (sync_profiles / 'multi-aws sync')"},
        ]
        next_step = next((s for s in steps if not s["done"]), None)
        return {
            "ready": next_step is None,
            "next_step": next_step,
            "steps": steps,
            "sso_session": self.sso_session,
            "profile_prefix": self.prefix,
            "default_region": self.region,
            "allow_destructive_commands": self.config.get_bool(
                "security", "allow-destructive-commands", False),
            "teams": sorted({a.product_team for a in accounts if a.product_team}),
            "tagged_accounts": sum(1 for a in accounts if a.tags),
            "common_roles": dict(role_counts.most_common(10)),
            "config_file": str(self.config.paths.config_file),
            "aws_config_file": str(profile_config.aws_config_path()),
            "account_file": str(self.accounts.data_manager.file_path),
        }

    # -- config ----------------------------------------------------------------

    def get_config(self) -> Dict[str, Any]:
        return {
            "config_file": str(self.config.paths.config_file),
            "exists": self.config.config_exists(),
            "settings": self.config.to_dict(),
        }

    def update_config(self, changes: Dict[str, Any], allow_protected: bool = False) -> Dict[str, Any]:
        """
        Update settings, given as ``{"section.key": value}`` (e.g. ``"general.region"``).

        Creates the config file if needed. ``security.*`` keys need
        ``allow_protected`` (the MCP server never passes it).
        """
        allowed = {f"{s}.{k}" for s, keys in DEFAULT_CONFIG.items() for k in keys} | EXTRA_CONFIG_KEYS
        parsed = {}
        for dotted, value in changes.items():
            dotted = dotted.strip()
            if dotted not in allowed:
                raise OperationError(f"Unknown setting '{dotted}'. Valid: {', '.join(sorted(allowed))}")
            if dotted in PROTECTED_CONFIG_KEYS and not allow_protected:
                raise OperationError(
                    f"'{dotted}' can only be changed by you directly ('multi-aws configure' "
                    "or editing the config file)")
            if isinstance(value, bool):
                value = "true" if value else "false"
            section, key = dotted.split(".", 1)
            parsed[(section, key)] = str(value).strip()

        old = {k: self.config.get(*k, "") for k in parsed}
        for (section, key), value in parsed.items():
            self.config.set(section, key, value)
        errors = MultiAWSConfig.from_config_manager(self.config).validate()
        if errors:
            for (section, key), value in old.items():
                self.config.set(section, key, value)
            raise OperationError("Invalid configuration: " + "; ".join(errors))
        self.config.save_config()
        # Prefix / SSO session / account file may have changed
        self.accounts = _account_manager_from_config(self.config)
        return {
            "updated": {f"{s}.{k}": v for (s, k), v in parsed.items()},
            "previous": {f"{s}.{k}": v for (s, k), v in old.items()},
            "config_file": str(self.config.paths.config_file),
        }

    # -- SSO -------------------------------------------------------------------

    def list_sso_sessions(self) -> Dict[str, Any]:
        sessions = profile_config.list_sso_sessions(profile_config.read_config())
        return {
            "configured_session": self.sso_session,
            "sessions": {name: {"start_url": v.get("sso_start_url"), "region": v.get("sso_region")}
                         for name, v in sessions.items()},
            "aws_config_file": str(profile_config.aws_config_path()),
        }

    def add_sso_session(self, name: str, start_url: str, sso_region: str,
                        overwrite: bool = False, make_default: bool = True) -> Dict[str, Any]:
        """Add an ``[sso-session]`` to ~/.aws/config and optionally make it the multi-aws default."""
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise OperationError("Session name may only contain letters, digits, '-', '_' and '.'")
        start_url = start_url.strip()
        if not re.match(r"^https://\S+$", start_url):
            raise OperationError("start_url must be your AWS access portal URL, "
                                 "e.g. https://my-org.awsapps.com/start")
        if not re.fullmatch(r"[a-z]{2}(-[a-z]+)+-\d", sso_region.strip()):
            raise OperationError(f"'{sso_region}' doesn't look like an AWS region (e.g. eu-west-1)")

        text = profile_config.read_config()
        header = f"sso-session {name}"
        if name in profile_config.list_sso_sessions(text) and not overwrite:
            raise OperationError(f"SSO session '{name}' already exists (pass overwrite to replace it)")
        text, created, _ = profile_config.upsert_sections(
            text, {header: profile_config.sso_session_values(start_url, sso_region.strip())},
            comment="SSO session added by multi-aws")
        backup = profile_config.write_config(text)
        result = {"session": name, "created": bool(created),
                  "aws_config_file": str(profile_config.aws_config_path()),
                  "backup": str(backup) if backup else None}
        if make_default and name != self.sso_session:
            self.update_config({"general.sso-session": name})
            result["now_default"] = True
        return result

    def sso_login(self, timeout: int = 300, interactive: bool = False) -> Dict[str, Any]:
        """
        Run ``aws sso login`` for the configured session (opens the browser).

        With ``interactive`` the AWS CLI's output (verification URL and code)
        goes straight to the terminal instead of being captured.
        """
        if self.accounts.is_authenticated():
            return {"authenticated": True, "message": "Already logged in", "session": self.sso_session}
        if self.sso_session not in profile_config.list_sso_sessions(profile_config.read_config()):
            raise OperationError(f"SSO session '{self.sso_session}' is not configured; add it first")
        try:
            proc = subprocess.run(
                ["aws", "sso", "login", "--sso-session", self.sso_session],
                capture_output=not interactive, text=True, timeout=timeout,
                stdin=None if interactive else subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise OperationError("AWS CLI (aws) not found on PATH")
        except subprocess.TimeoutExpired:
            return {"authenticated": False, "error": "Timed out waiting for browser approval"}
        ok = proc.returncode == 0 and self.accounts.is_authenticated()
        result: Dict[str, Any] = {"authenticated": ok, "session": self.sso_session}
        if not ok:
            result["error"] = (proc.stderr or proc.stdout or "aws sso login failed").strip()[-2000:]
        return result

    # -- discovery, roles, profiles -------------------------------------------

    def discover_accounts(self, sanitize_names: bool = True) -> Dict[str, Any]:
        """Discover accounts via SSO (like ``multi-aws init``)."""
        self._require_login()
        with _data_lock:
            before = {a.id for a in self.accounts.get_accounts()}
            collection = self.accounts.discover_accounts(force_refresh=True)
            sanitized = []
            if sanitize_names:
                for account in collection.accounts:
                    clean = sanitize_profile_name_component(account.name)
                    if clean != account.name:
                        sanitized.append({"id": account.id, "from": account.name, "to": clean})
                        account.name = clean
                if sanitized:
                    self._save(collection)
        active = collection.get_active_accounts()
        return {
            "active": len(active),
            "disabled": len(collection.get_disabled_accounts()),
            "new_accounts": [{"id": a.id, "name": a.name} for a in active if a.id not in before],
            "sanitized_names": sanitized,
            "account_file": str(self.accounts.data_manager.file_path),
        }

    def fetch_roles(self, account_ids: Sequence[str], max_workers: int = 8) -> Dict[str, Any]:
        """Fetch the SSO roles available in each account (in parallel) and store them."""
        self._require_login()
        collection = self._load()
        accounts, missing = self._resolve(collection, account_ids)
        accounts = [a for a in accounts if a.is_active()]

        def fetch(account: Account):
            try:
                return account.id, self.accounts.discover_roles_for_account(account.id), None
            except AccountManagerError as e:
                return account.id, None, str(e)

        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(accounts) or 1))) as pool:
            fetched = list(pool.map(fetch, accounts))

        failed = {aid: err for aid, _, err in fetched if err}
        with _data_lock:
            collection = self._load()
            for account_id, roles, err in fetched:
                account = collection.get_account(account_id)
                if account and roles is not None:
                    account.roles = list(roles)
                    account.last_updated = datetime.now()
            self._save(collection)

        role_counts = Counter(r.name for _, roles, _ in fetched if roles for r in roles)
        return {
            "updated": len(fetched) - len(failed),
            "failed": failed,
            "not_found": missing,
            "roles": dict(role_counts.most_common()),
        }

    def generate_profiles(self, account_ids: Sequence[str], role: str,
                          region: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        """
        Create/update ``<prefix>-<account>-<role>`` SSO profiles in ~/.aws/config.

        Existing profiles with the same name are updated in place. The profile
        name is stored on each account so ``run`` picks it up.
        """
        role = role.strip()
        region = (region or self.region).strip()
        with _data_lock:
            collection = self._load()
            accounts, missing = self._resolve(collection, account_ids)
            skipped = [{"id": m, "reason": "account not found"} for m in missing]
            sections: Dict[str, Dict[str, str]] = {}
            chosen: Dict[str, str] = {}
            generated: List[Dict[str, Any]] = []
            for account in accounts:
                if not account.roles:
                    skipped.append({"id": account.id, "name": account.name,
                                    "reason": "roles not fetched yet (fetch_roles)"})
                    continue
                if not account.has_role(role):
                    skipped.append({"id": account.id, "name": account.name,
                                    "reason": f"role not available; has {[r.name for r in account.roles]}"})
                    continue
                name = f"{self.prefix}-{sanitize_profile_name_component(account.name)}-{role}"
                sections[f"profile {name}"] = profile_config.profile_values(
                    self.sso_session, account.id, role, region)
                chosen[account.id] = name
                generated.append({"profile": name, "account_id": account.id,
                                  "account_name": account.name,
                                  "settings": sections[f"profile {name}"]})

            if not sections:
                return {"created": [], "updated": [], "skipped": skipped, "profiles": [],
                        "dry_run": dry_run}

            text = profile_config.read_config()
            text, created, updated = profile_config.upsert_sections(
                text, sections,
                comment=f"Generated by MultiAWSTool - {role} profiles\n"
                        f"Generated on: {datetime.now():%Y-%m-%d %H:%M:%S}")
            backup = None
            if not dry_run:
                backup = profile_config.write_config(text)
                for account_id, name in chosen.items():
                    collection.get_account(account_id).set_profile_name(name)
                self._save(collection)

        strip = len("profile ")
        return {
            "created": [h[strip:] for h in created],
            "updated": [h[strip:] for h in updated],
            "skipped": skipped,
            "profiles": generated,
            "dry_run": dry_run,
            "aws_config_file": str(profile_config.aws_config_path()),
            "backup": str(backup) if backup else None,
        }

    def sync_profiles(self, dry_run: bool = False) -> Dict[str, Any]:
        """Link existing ``<prefix>-*`` profiles in ~/.aws/config to their accounts."""
        profiles = profile_config.list_profiles(profile_config.read_config())
        found = {v["sso_account_id"]: name for name, v in profiles.items()
                 if name.startswith(self.prefix + "-") and v.get("sso_account_id")}
        with _data_lock:
            collection = self._load()
            changes, unknown = [], []
            for account_id, name in found.items():
                account = collection.get_account(account_id)
                if not account:
                    unknown.append({"id": account_id, "profile": name})
                elif account.profile_name != name:
                    changes.append({"id": account_id, "name": account.name,
                                    "from": account.profile_name, "to": name})
                    if not dry_run:
                        account.set_profile_name(name)
            if changes and not dry_run:
                self._save(collection)
        return {"profiles_found": len(found), "changes": changes,
                "unknown_accounts": unknown, "dry_run": dry_run}

    def sanitize_names(self, dry_run: bool = False) -> Dict[str, Any]:
        """Make stored account names safe for profile names."""
        with _data_lock:
            collection = self._load()
            changes = []
            for account in collection.accounts:
                clean = sanitize_profile_name_component(account.name)
                if clean != account.name:
                    changes.append({"id": account.id, "from": account.name, "to": clean})
                    if not dry_run:
                        account.name = clean
            if changes and not dry_run:
                self._save(collection)
        return {"checked": len(collection.accounts), "changes": changes, "dry_run": dry_run}

    def clean_duplicate_profiles(self, prefix_only: bool = False, dry_run: bool = True) -> Dict[str, Any]:
        """Remove profiles pointing at the same account/role/session (keeps the prefixed one)."""
        text = profile_config.read_config()
        groups = profile_config.find_duplicate_profiles(text, self.prefix, prefix_only)
        backup = None
        if groups and not dry_run:
            backup = profile_config.write_config(
                profile_config.remove_sections(text, profile_config.all_remove_indexes(groups)))
        return {
            "duplicates": [{"account_id": g.account_id, "role": g.role_name, "keep": g.keep,
                            "remove": g.remove} for g in groups],
            "removed": 0 if dry_run else sum(len(g.remove) for g in groups),
            "dry_run": dry_run,
            "backup": str(backup) if backup else None,
        }

    # -- teams -------------------------------------------------------------------

    def list_teams(self) -> Dict[str, int]:
        counts = Counter(a.product_team for a in self.accounts.get_accounts() if a.product_team)
        return dict(sorted(counts.items()))

    def assign_team(self, account_ids: Sequence[str], team: Optional[str],
                    overwrite: bool = False) -> Dict[str, Any]:
        """Set (or with ``team=None`` clear) the product team of accounts."""
        team = team.strip() if team else None
        with _data_lock:
            collection = self._load()
            accounts, missing = self._resolve(collection, account_ids)
            updated, skipped = [], []
            for account in accounts:
                if account.product_team == team:
                    continue
                if account.product_team and team and not overwrite:
                    skipped.append({"id": account.id, "name": account.name, "team": account.product_team})
                    continue
                updated.append({"id": account.id, "name": account.name,
                                "from": account.product_team, "to": team})
                account.product_team = team
                account.last_updated = datetime.now()
            if updated:
                self._save(collection)
        return {"updated": updated, "skipped_existing_team": skipped, "not_found": missing}

    # -- tags ---------------------------------------------------------------------

    def set_tags(self, account_ids: Sequence[str], tags: Union[Dict[str, str], Iterable[str]],
                 overwrite: bool = False) -> Dict[str, Any]:
        tags = parse_tags(tags)
        if not tags:
            raise OperationError("No tags given")
        with _data_lock:
            collection = self._load()
            accounts, missing = self._resolve(collection, account_ids)
            changes, skipped = [], []
            for account in accounts:
                changed = False
                for key, value in tags.items():
                    existing = account.tags.get(key)
                    if existing == value:
                        continue
                    if existing is not None and not overwrite:
                        skipped.append({"id": account.id, "key": key, "existing": existing})
                        continue
                    account.tags[key] = value
                    changes.append({"id": account.id, "name": account.name, "key": key,
                                    "from": existing, "to": value})
                    changed = True
                if changed:
                    account.last_updated = datetime.now()
            if changes:
                self._save(collection)
        return {"changes": changes, "skipped_existing": skipped, "not_found": missing}

    def remove_tags(self, account_ids: Sequence[str], keys: Iterable[str]) -> Dict[str, Any]:
        keys = [k.strip() for k in keys if k.strip()]
        with _data_lock:
            collection = self._load()
            accounts, missing = self._resolve(collection, account_ids)
            removed = []
            for account in accounts:
                for key in keys:
                    if key in account.tags:
                        removed.append({"id": account.id, "name": account.name,
                                        "key": key, "value": account.tags.pop(key)})
                        account.last_updated = datetime.now()
            if removed:
                self._save(collection)
        return {"removed": removed, "not_found": missing}

    def sync_tags(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Pull account tags from AWS Organizations.

        ``account_id`` is a management or delegated-admin account whose profile
        is used; without it the default credential chain is used.
        """
        profile_name = None
        if account_id:
            account = self.accounts.get_account(account_id)
            if not account:
                raise OperationError(f"Account {account_id} not found")
            profile_name = self.accounts.get_profile_name(account)
            if not profile_name:
                raise OperationError(f"Account {account_id} ({account.name}) has no working profile; "
                                     "generate one first")
        with _data_lock:
            counts = self.accounts.sync_account_tags(profile_name=profile_name)
        counts["profile_used"] = profile_name
        return counts

    # -- templates ------------------------------------------------------------------

    def _templates(self):
        return get_template_manager(self.config)

    def list_templates(self) -> List[Dict[str, Any]]:
        return [template_to_dict(t) for t in self._templates().list_templates()]

    def get_template(self, name: str) -> CommandTemplate:
        tmpl = self._templates().get_template(name.lstrip("@"))
        if not tmpl:
            raise OperationError(f"Template '{name}' not found")
        return tmpl

    def save_template(self, name: str, command: str, description: str = "",
                      accounts: Union[None, str, Sequence[str]] = None, team: str = "",
                      tags: Union[None, Dict[str, str], Iterable[str]] = None,
                      region: str = "", output_format: str = "", parallel: Optional[bool] = None,
                      timeout: int = 0, save: Optional[bool] = None,
                      overwrite: bool = False) -> Dict[str, Any]:
        name = name.strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise OperationError("Template names may only contain letters, digits, '-', '_' and '.'")
        command = command.strip()
        if command.startswith("aws "):
            command = command[4:]
        if is_destructive_command(command) and not self.config.get_bool(
                "security", "allow-destructive-commands", False):
            raise OperationError(f"'{command}' is considered destructive; destructive templates need "
                                 "allow-destructive-commands enabled in config")
        mgr = self._templates()
        existing = mgr.get_template(name)
        if existing and not overwrite:
            raise OperationError(f"Template '{name}' already exists (pass overwrite to replace it)")
        if isinstance(accounts, (list, tuple)):
            accounts = ",".join(accounts)
        tmpl = CommandTemplate(
            name=name, command=command, description=description, region=region or "",
            output_format=output_format or "", parallel=parallel, timeout=timeout or 0,
            accounts=accounts or "", team=team or "",
            tags=[f"{k}={v}" for k, v in parse_tags(tags).items()], save=save,
        )
        if existing:
            tmpl.created_at = existing.created_at
        mgr.add_template(tmpl)
        mgr.save_templates()
        return {"saved": template_to_dict(tmpl), "replaced": bool(existing)}

    def delete_template(self, name: str) -> Dict[str, Any]:
        mgr = self._templates()
        name = name.lstrip("@")
        if not mgr.delete_template(name):
            raise OperationError(f"Template '{name}' not found")
        mgr.save_templates()
        return {"deleted": name}

    # -- running commands --------------------------------------------------------------

    def run(
        self,
        command: str,
        accounts: Union[None, str, Sequence[str]] = None,
        team: Optional[str] = None,
        tags: Union[None, Dict[str, str], Iterable[str]] = None,
        regions: Union[None, str, Sequence[str]] = None,
        role: Optional[str] = None,
        include_inactive: bool = False,
        timeout: int = 300,
        parallel: bool = True,
        output_format: Optional[str] = None,
    ) -> MultiAWSExecutionSummary:
        """Select accounts and run an AWS CLI command (raises on bad input or no login)."""
        account_ids = self.select_accounts(accounts, team, tags, include_inactive)
        self._require_login()
        if isinstance(regions, (list, tuple)) and len(regions) == 1 and regions[0].lower() == "all":
            regions = "all"
        return execute(
            command, accounts=account_ids, regions=regions or None, parallel=parallel,
            role=role, timeout=timeout, output_format=output_format,
            account_manager=self.accounts, config_manager=self.config,
        )

    def template_run_kwargs(self, name: str, **overrides) -> Dict[str, Any]:
        """
        Arguments for :meth:`run` from a template; non-empty ``overrides`` win.

        Account selectors (accounts/team/tags) are replaced as a group: if any
        is overridden, the template's own selectors are ignored.
        """
        tmpl = self.get_template(name)
        kwargs: Dict[str, Any] = {
            "command": tmpl.command,
            "accounts": split_accounts(tmpl.accounts) if tmpl.accounts else None,
            "team": tmpl.team or None,
            "tags": tmpl.tags or None,
            "regions": [tmpl.region] if tmpl.region else None,
            "output_format": tmpl.output_format or None,
        }
        if tmpl.timeout:
            kwargs["timeout"] = tmpl.timeout
        if tmpl.parallel is not None:
            kwargs["parallel"] = tmpl.parallel
        overrides = {k: v for k, v in overrides.items() if v not in (None, "", [], {})}
        if overrides.keys() & {"accounts", "team", "tags"}:
            kwargs.update(accounts=None, team=None, tags=None)
        kwargs.update(overrides)
        return kwargs

    # -- cleanup -----------------------------------------------------------------------

    def cleanup(self, profiles: bool = False, tokens: bool = False,
                account_data: bool = False) -> Dict[str, Any]:
        """
        Remove tool-generated state.

        profiles: ``<prefix>-*`` SSO profiles from ~/.aws/config (backup kept).
        tokens: cached SSO/CLI tokens in ~/.aws/sso/cache and ~/.aws/cli/cache.
        account_data: the local account file (backup kept next to it).
        """
        result: Dict[str, Any] = {}
        if profiles:
            text = profile_config.read_config()
            _, sections = profile_config.parse(text)
            indexes = [i for i, s in enumerate(sections)
                       if s.kind == "profile" and s.name.startswith(self.prefix + "-")
                       and s.values.get("sso_account_id")]
            backup = None
            if indexes:
                backup = profile_config.write_config(profile_config.remove_sections(text, indexes))
            result["profiles_removed"] = [sections[i].name for i in indexes]
            result["aws_config_backup"] = str(backup) if backup else None
        if tokens:
            removed = 0
            for cache_dir in (Path("~/.aws/sso/cache").expanduser(), Path("~/.aws/cli/cache").expanduser()):
                if cache_dir.is_dir():
                    for f in cache_dir.glob("*.json"):
                        try:
                            f.unlink()
                            removed += 1
                        except OSError as e:
                            logger.warning(f"Could not remove {f}: {e}")
            result["token_files_removed"] = removed
        if account_data:
            path = Path(self.accounts.data_manager.file_path)
            with _data_lock:
                if path.exists():
                    backup = path.with_suffix(".json.backup")
                    shutil.copy2(path, backup)
                    path.unlink()
                    result["account_file_removed"] = str(path)
                    result["account_file_backup"] = str(backup)
                else:
                    result["account_file_removed"] = None
        return result
