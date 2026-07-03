"""
Command template data model for MultiAWSTool
Provides type-safe representation of saved command presets
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class CommandTemplate:
    """A named, reusable AWS CLI command preset"""
    name: str
    command: str
    description: str = ""
    # Optional overrides – empty string / None means "use configured default"
    region: str = ""
    output_format: str = ""
    parallel: Optional[bool] = None  # None = use execution.mode from config
    timeout: int = 0  # 0 = use default timeout
    # Account filter defaults – applied when the user does not supply them on
    # the CLI.  Empty string / empty list means "no default set".
    accounts: str = ""  # comma-separated account IDs or file path
    team: str = ""      # team name(s) to select accounts from
    tags: List[str] = field(default_factory=list)  # KEY=VALUE strings
    save: Optional[bool] = None  # None = use CLI flag; True/False overrides it
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Convert to a JSON-serialisable dictionary"""
        return {
            "name": self.name,
            "command": self.command,
            "description": self.description,
            "region": self.region,
            "output_format": self.output_format,
            "parallel": self.parallel,
            "timeout": self.timeout,
            "accounts": self.accounts,
            "team": self.team,
            "tags": list(self.tags),
            "save": self.save,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CommandTemplate":
        """Create a CommandTemplate from a dictionary (e.g. loaded from JSON)"""
        now = datetime.now().isoformat()
        return cls(
            name=data["name"],
            command=data["command"],
            description=data.get("description", ""),
            region=data.get("region", ""),
            output_format=data.get("output_format", ""),
            parallel=data.get("parallel"),
            timeout=int(data.get("timeout", 0)),
            accounts=data.get("accounts", ""),
            team=data.get("team", ""),
            tags=list(data.get("tags", [])),
            save=data.get("save"),
            created_at=datetime.fromisoformat(data.get("created_at", now)),
            updated_at=datetime.fromisoformat(data.get("updated_at", now)),
        )
