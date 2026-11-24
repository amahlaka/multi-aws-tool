"""
Reading and editing the AWS CLI config file (``~/.aws/config``).

Edits are section-aware and preserve everything they don't touch (comments,
ordering, unrelated profiles). Every write keeps a timestamped backup next to
the file. ``AWS_CONFIG_FILE`` is honoured, like the AWS CLI does.
"""

import os
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def aws_config_path() -> Path:
    """Path of the AWS CLI config file."""
    return Path(os.environ.get("AWS_CONFIG_FILE", "~/.aws/config")).expanduser()


@dataclass
class Section:
    """One ``[header]`` section of the config file."""
    header: str                     # e.g. "profile foo", "sso-session bar", "default"
    lines: List[str]                # raw lines, header line included
    values: Dict[str, str] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        if self.header == "default":
            return "profile"
        return self.header.split(" ", 1)[0]

    @property
    def name(self) -> str:
        if self.header == "default":
            return "default"
        parts = self.header.split(" ", 1)
        return parts[1].strip() if len(parts) > 1 else parts[0]


def _header_of(line: str) -> Optional[str]:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return " ".join(stripped[1:-1].split())
    return None


def parse(text: str) -> Tuple[List[str], List[Section]]:
    """Split config text into preamble lines and sections (in file order)."""
    preamble: List[str] = []
    sections: List[Section] = []
    for line in text.splitlines():
        header = _header_of(line)
        if header is not None:
            sections.append(Section(header=header, lines=[line]))
            continue
        if not sections:
            preamble.append(line)
            continue
        current = sections[-1]
        current.lines.append(line)
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith(("#", ";")) and not line[:1].isspace():
            key, value = stripped.split("=", 1)
            current.values[key.strip()] = value.strip()
    return preamble, sections


def _split_trailer(lines: List[str]) -> Tuple[List[str], List[str]]:
    """Split a section's lines into its body and trailing blank/comment lines.

    Trailing comments usually describe the *next* section, so edits keep them.
    """
    end = len(lines)
    while end > 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith(("#", ";"))):
        end -= 1
    return lines[:end], lines[end:]


def _render(preamble: List[str], sections: Iterable[Section]) -> str:
    lines = list(preamble)
    for section in sections:
        lines.extend(section.lines)
    text = "\n".join(lines).rstrip("\n")
    return text + "\n" if text else ""


def section_lines(header: str, values: Dict[str, str]) -> List[str]:
    """Lines of a ``[header]`` section with ``key = value`` entries."""
    return [f"[{header}]"] + [f"{k} = {v}" for k, v in values.items()]


def read_config(path: Optional[Path] = None) -> str:
    path = path or aws_config_path()
    return path.read_text() if path.exists() else ""


def write_config(text: str, path: Optional[Path] = None) -> Optional[Path]:
    """Write the config file, keeping a timestamped backup. Returns the backup path."""
    path = path or aws_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_name(f"{path.name}.backup.{int(time.time())}")
        shutil.copy2(path, backup)
    path.write_text(text)
    return backup


def upsert_sections(
    text: str,
    sections: Dict[str, Dict[str, str]],
    comment: Optional[str] = None,
) -> Tuple[str, List[str], List[str]]:
    """
    Create or replace sections, keyed by header (e.g. ``"profile foo"``).

    Existing sections are rewritten in place (all copies, if duplicated);
    new ones are appended, preceded by ``comment`` if given.

    Returns:
        (new_text, created_headers, updated_headers)
    """
    preamble, existing = parse(text)
    updated: List[str] = []
    for section in existing:
        if section.header in sections:
            _, trailer = _split_trailer(section.lines)
            values = sections[section.header]
            section.lines = section_lines(section.header, values) + trailer
            section.values = dict(values)
            if section.header not in updated:
                updated.append(section.header)

    created = [h for h in sections if h not in updated]
    if created:
        new_lines: List[str] = [""]
        if comment:
            new_lines += [f"# {line}" for line in comment.splitlines()]
        for header in created:
            new_lines += section_lines(header, sections[header]) + [""]
        body = _render(preamble, existing).rstrip("\n")
        if not body:
            new_lines = new_lines[1:]
        text = (body + "\n" if body else "") + "\n".join(new_lines).rstrip("\n") + "\n"
    else:
        text = _render(preamble, existing)
    return text, created, updated


def remove_sections(text: str, indexes: Iterable[int]) -> str:
    """Remove sections by their position in :func:`parse` output."""
    preamble, sections = parse(text)
    drop = set(indexes)
    kept: List[Section] = []
    for i, section in enumerate(sections):
        if i in drop:
            _, trailer = _split_trailer(section.lines)
            if kept:
                kept[-1].lines.extend(trailer)
            else:
                preamble.extend(trailer)
        else:
            kept.append(section)
    return _render(preamble, kept)


# ---------------------------------------------------------------------------
# Profiles and SSO sessions
# ---------------------------------------------------------------------------

def profile_values(sso_session: str, account_id: str, role: str, region: str) -> Dict[str, str]:
    return {
        "sso_session": sso_session,
        "sso_account_id": account_id,
        "sso_role_name": role,
        "region": region,
    }


def list_profiles(text: str) -> Dict[str, Dict[str, str]]:
    """Profile name -> settings (the last definition wins, like the AWS CLI)."""
    _, sections = parse(text)
    return {s.name: s.values for s in sections if s.kind == "profile"}


def list_sso_sessions(text: str) -> Dict[str, Dict[str, str]]:
    """SSO session name -> settings."""
    _, sections = parse(text)
    return {s.name: s.values for s in sections if s.kind == "sso-session"}


def sso_session_values(start_url: str, sso_region: str,
                       scopes: str = "sso:account:access") -> Dict[str, str]:
    return {
        "sso_start_url": start_url,
        "sso_region": sso_region,
        "sso_registration_scopes": scopes,
    }


@dataclass
class DuplicateGroup:
    account_id: str
    role_name: str
    sso_session: str
    keep: str
    remove: List[str]
    remove_indexes: List[int]


def find_duplicate_profiles(text: str, prefix: str = "", prefix_only: bool = False) -> List[DuplicateGroup]:
    """
    Profiles pointing at the same (account, role, SSO session).

    In each group the profile starting with ``<prefix>-`` is kept (then the
    alphabetically first). With ``prefix_only``, only prefixed profiles are
    considered. Repeated sections with the same name count as duplicates too.
    """
    _, sections = parse(text)
    groups: Dict[Tuple[str, str, str], List[Tuple[int, Section]]] = defaultdict(list)
    for i, section in enumerate(sections):
        if section.kind != "profile":
            continue
        if prefix_only and not section.name.startswith(prefix + "-"):
            continue
        account_id = section.values.get("sso_account_id", "")
        role = section.values.get("sso_role_name", "")
        if account_id and role:
            groups[(account_id, role, section.values.get("sso_session", ""))].append((i, section))

    result = []
    for (account_id, role, session), members in groups.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda m: (
            not (prefix and m[1].name.startswith(prefix + "-")), m[1].name, m[0]))
        keep_index, keep = ordered[0]
        rest = ordered[1:]
        result.append(DuplicateGroup(
            account_id=account_id, role_name=role, sso_session=session, keep=keep.name,
            remove=[s.name for _, s in rest], remove_indexes=[i for i, _ in rest],
        ))
    return result


def all_remove_indexes(groups: Sequence[DuplicateGroup]) -> List[int]:
    return [i for g in groups for i in g.remove_indexes]
