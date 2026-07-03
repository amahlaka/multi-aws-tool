"""
Template manager for MultiAWSTool
Handles persistence and retrieval of command templates / presets
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..models.template import CommandTemplate

logger = logging.getLogger(__name__)


class TemplateError(Exception):
    """Raised when template operations fail"""


class TemplateManager:
    """Manages saved command templates"""

    DEFAULT_FILE = Path.home() / ".multi-aws" / "templates.json"

    def __init__(self, templates_file: Optional[str] = None):
        if templates_file:
            self.templates_file = Path(templates_file).expanduser()
        else:
            self.templates_file = self.DEFAULT_FILE

        self._templates: Dict[str, CommandTemplate] = {}

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def load_templates(self) -> None:
        """Load templates from disk; no-op if the file does not exist yet"""
        if not self.templates_file.exists():
            logger.debug("Templates file not found, starting with empty template set")
            return

        try:
            with open(self.templates_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            self._templates = {
                name: CommandTemplate.from_dict(tmpl)
                for name, tmpl in data.get("templates", {}).items()
            }
            logger.debug("Loaded %d template(s) from %s", len(self._templates), self.templates_file)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise TemplateError(f"Failed to parse templates file: {exc}") from exc
        except OSError as exc:
            raise TemplateError(f"Failed to read templates file: {exc}") from exc

    def save_templates(self) -> None:
        """Persist the current set of templates to disk"""
        try:
            self.templates_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "templates": {
                    name: tmpl.to_dict() for name, tmpl in self._templates.items()
                }
            }
            with open(self.templates_file, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.chmod(self.templates_file, 0o600)
            logger.debug("Saved %d template(s) to %s", len(self._templates), self.templates_file)
        except OSError as exc:
            raise TemplateError(f"Failed to save templates: {exc}") from exc

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def get_template(self, name: str) -> Optional[CommandTemplate]:
        """Return the template with the given name, or None if not found"""
        return self._templates.get(name)

    def add_template(self, template: CommandTemplate) -> None:
        """Add or overwrite a template (does NOT auto-save)"""
        self._templates[template.name] = template

    def update_template(self, template: CommandTemplate) -> None:
        """Update an existing template (does NOT auto-save)"""
        if template.name not in self._templates:
            raise TemplateError(f"Template '{template.name}' not found")
        template.updated_at = datetime.now()
        self._templates[template.name] = template

    def delete_template(self, name: str) -> bool:
        """Remove a template by name; returns True if it existed"""
        if name in self._templates:
            del self._templates[name]
            return True
        return False

    def list_templates(self) -> List[CommandTemplate]:
        """Return all templates, sorted alphabetically by name"""
        return sorted(self._templates.values(), key=lambda t: t.name)

    def template_exists(self, name: str) -> bool:
        """Return True if a template with the given name exists"""
        return name in self._templates


def get_template_manager(config_manager=None) -> TemplateManager:
    """Create a TemplateManager, optionally using a config-provided path"""
    if config_manager is not None:
        try:
            templates_file = config_manager.get(
                "general", "templates-file", fallback=None
            )
            if templates_file:
                return TemplateManager(templates_file)
        except Exception:
            pass
    manager = TemplateManager()
    manager.load_templates()
    return manager
