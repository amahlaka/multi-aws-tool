"""
Tests for the Command Templates / Presets feature:
  - CommandTemplate model (serialisation round-trip)
  - TemplateManager (load / save / CRUD)
  - CLI: template add / list / show / delete
  - CLI: run @template-name resolution
  - Security: destructive-command gate applied to templates
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from click.testing import CliRunner

from multi_aws_tool.models.template import CommandTemplate
from multi_aws_tool.config.template_manager import TemplateManager, TemplateError
from multi_aws_tool.models.account import Account, AccountCollection, AccountStatus
from multi_aws_tool.cli.commands import cli


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _make_account(account_id: str, name: str = "TestAccount",
                  profile_name: str = "test-profile") -> Account:
    return Account(
        id=account_id,
        name=name,
        status=AccountStatus.ACTIVE,
        profile_name=profile_name,
    )


def _make_collection(*accounts: Account) -> AccountCollection:
    col = AccountCollection()
    for acc in accounts:
        col.add_account(acc)
    return col


def _mock_account_manager(collection: AccountCollection) -> MagicMock:
    manager = MagicMock()
    manager.data_manager.load_accounts.return_value = collection
    manager.data_manager.file_path = "/fake/accounts.json"
    manager.data_manager.save_accounts = MagicMock()
    manager.get_account.side_effect = lambda aid: collection.get_account(aid)
    manager.get_accounts_by_team.return_value = []
    manager.get_accounts.return_value = list(collection.accounts)
    manager.is_authenticated.return_value = True
    return manager


def _run_cli(args, account_manager=None, config_overrides: dict = None):
    """Invoke CLI with standard patches."""
    runner = CliRunner()
    obj_mock = MagicMock()
    obj_mock.config_manager = None
    obj_mock.account_manager = account_manager
    obj_mock.ensure_authenticated = MagicMock()

    with patch('multi_aws_tool.cli.commands.get_account_manager',
               return_value=account_manager or MagicMock()), \
         patch('os.get_terminal_size', return_value=(120, 40)):
        return runner.invoke(cli, args, catch_exceptions=False, obj=obj_mock)


# ===========================================================================
# CommandTemplate model
# ===========================================================================

class TestCommandTemplateModel:
    def test_defaults(self):
        tmpl = CommandTemplate(name="my-tmpl", command="sts get-caller-identity")
        assert tmpl.name == "my-tmpl"
        assert tmpl.command == "sts get-caller-identity"
        assert tmpl.description == ""
        assert tmpl.region == ""
        assert tmpl.output_format == ""
        assert tmpl.parallel is None
        assert tmpl.timeout == 0
        assert tmpl.accounts == ""
        assert tmpl.team == ""
        assert tmpl.tags == []
        assert tmpl.save is None

    def test_round_trip(self):
        tmpl = CommandTemplate(
            name="check-id",
            command="sts get-caller-identity",
            description="Identity check",
            region="eu-west-1",
            output_format="json",
            parallel=True,
            timeout=60,
        )
        data = tmpl.to_dict()
        restored = CommandTemplate.from_dict(data)
        assert restored.name == tmpl.name
        assert restored.command == tmpl.command
        assert restored.description == tmpl.description
        assert restored.region == tmpl.region
        assert restored.output_format == tmpl.output_format
        assert restored.parallel == tmpl.parallel
        assert restored.timeout == tmpl.timeout

    def test_round_trip_with_filters(self):
        """New fields survive a serialise/deserialise round-trip."""
        tmpl = CommandTemplate(
            name="filtered",
            command="sts get-caller-identity",
            accounts="111111111111,222222222222",
            team="platform",
            tags=["env=prod", "owner=ops"],
            save=True,
        )
        data = tmpl.to_dict()
        restored = CommandTemplate.from_dict(data)
        assert restored.accounts == tmpl.accounts
        assert restored.team == tmpl.team
        assert restored.tags == tmpl.tags
        assert restored.save == tmpl.save

    def test_from_dict_minimal(self):
        """from_dict should work with only required keys."""
        tmpl = CommandTemplate.from_dict({"name": "x", "command": "ec2 describe-instances"})
        assert tmpl.name == "x"
        assert tmpl.parallel is None
        assert tmpl.timeout == 0
        assert tmpl.accounts == ""
        assert tmpl.team == ""
        assert tmpl.tags == []
        assert tmpl.save is None


# ===========================================================================
# TemplateManager
# ===========================================================================

class TestTemplateManager:
    def test_empty_on_missing_file(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.load_templates()
        assert mgr.list_templates() == []

    def test_add_and_retrieve(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.load_templates()
        tmpl = CommandTemplate(name="t1", command="sts get-caller-identity")
        mgr.add_template(tmpl)
        assert mgr.template_exists("t1")
        assert mgr.get_template("t1").command == "sts get-caller-identity"
        assert not mgr.template_exists("unknown")

    def test_save_and_reload(self, tmp_path):
        path = tmp_path / "templates.json"
        mgr = TemplateManager(str(path))
        mgr.load_templates()
        mgr.add_template(CommandTemplate(name="t2", command="ec2 describe-instances",
                                         description="List instances"))
        mgr.save_templates()

        mgr2 = TemplateManager(str(path))
        mgr2.load_templates()
        tmpl = mgr2.get_template("t2")
        assert tmpl is not None
        assert tmpl.description == "List instances"

    def test_delete(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.load_templates()
        mgr.add_template(CommandTemplate(name="del-me", command="sts get-caller-identity"))
        assert mgr.delete_template("del-me") is True
        assert mgr.delete_template("del-me") is False  # idempotent

    def test_list_sorted(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.load_templates()
        for name in ["zzz", "aaa", "mmm"]:
            mgr.add_template(CommandTemplate(name=name, command="sts get-caller-identity"))
        names = [t.name for t in mgr.list_templates()]
        assert names == sorted(names)

    def test_update_raises_on_missing(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.load_templates()
        with pytest.raises(TemplateError):
            mgr.update_template(CommandTemplate(name="ghost", command="ec2 describe"))

    def test_corrupt_file_raises(self, tmp_path):
        path = tmp_path / "templates.json"
        path.write_text("NOT JSON")
        mgr = TemplateManager(str(path))
        with pytest.raises(TemplateError):
            mgr.load_templates()


# ===========================================================================
# CLI: template add
# ===========================================================================

class TestTemplateAddCommand:
    def _run(self, args, tmp_templates_path):
        """Run CLI with a real TemplateManager backed by tmp storage."""
        runner = CliRunner()
        obj_mock = MagicMock()
        obj_mock.config_manager = None

        config_mock = MagicMock()
        config_mock.get.side_effect = lambda s, k, fallback=None: fallback
        config_mock.get_bool.side_effect = lambda s, k, fallback=False: fallback

        with patch('multi_aws_tool.cli.commands.load_or_create_config',
                   return_value=config_mock), \
             patch('multi_aws_tool.config.template_manager.TemplateManager.DEFAULT_FILE',
                   tmp_templates_path), \
             patch('os.get_terminal_size', return_value=(120, 40)):
            return runner.invoke(cli, args, catch_exceptions=False, obj=obj_mock)

    def test_add_simple(self, tmp_path):
        result = self._run(
            ['template', 'add', 'my-check',
             '--command', 'sts get-caller-identity'],
            tmp_path / "templates.json",
        )
        assert result.exit_code == 0
        assert "my-check" in result.output
        assert "sts get-caller-identity" in result.output

    def test_add_with_options(self, tmp_path):
        result = self._run(
            ['template', 'add', 'detailed',
             '--command', 'ec2 describe-instances',
             '--description', 'List EC2',
             '--region', 'eu-west-1',
             '--output-format', 'json',
             '--parallel',
             '--timeout', '120'],
            tmp_path / "templates.json",
        )
        assert result.exit_code == 0
        assert "detailed" in result.output

    def test_add_duplicate_rejected_without_overwrite(self, tmp_path):
        tp = tmp_path / "templates.json"
        # First add
        self._run(['template', 'add', 'dup', '--command', 'sts get-caller-identity'], tp)
        # Second add should fail
        result = self._run(['template', 'add', 'dup', '--command', 'sts get-caller-identity'], tp)
        assert result.exit_code == 0
        assert "already exists" in result.output

    def test_add_duplicate_allowed_with_overwrite(self, tmp_path):
        tp = tmp_path / "templates.json"
        self._run(['template', 'add', 'dup', '--command', 'sts get-caller-identity'], tp)
        result = self._run(
            ['template', 'add', 'dup', '--command', 'sts get-caller-identity', '--overwrite'], tp
        )
        assert result.exit_code == 0
        assert "saved" in result.output

    def test_add_destructive_blocked(self, tmp_path):
        runner = CliRunner()
        obj_mock = MagicMock()
        obj_mock.config_manager = None

        config_mock = MagicMock()
        config_mock.get.side_effect = lambda s, k, fallback=None: fallback
        # Security: destructive commands NOT allowed
        config_mock.get_bool.side_effect = lambda s, k, fallback=False: False

        with patch('multi_aws_tool.cli.commands.load_or_create_config',
                   return_value=config_mock), \
             patch('os.get_terminal_size', return_value=(120, 40)):
            result = runner.invoke(
                cli,
                ['template', 'add', 'delete-stuff',
                 '--command', 's3 delete-bucket --bucket my-bucket'],
                catch_exceptions=False,
                obj=obj_mock,
            )
        assert result.exit_code == 0
        assert "destructive" in result.output.lower() or "destructive" in (result.output + result.output).lower()

    def test_add_with_account_filters(self, tmp_path):
        """template add stores accounts, team, tags and save fields."""
        tp = tmp_path / "templates.json"
        result = self._run(
            ['template', 'add', 'filtered-cmd',
             '--command', 'sts get-caller-identity',
             '--accounts', '111111111111,222222222222',
             '--team', 'platform',
             '--tag', 'env=prod',
             '--tag', 'owner=ops',
             '--save'],
            tp,
        )
        assert result.exit_code == 0
        assert "filtered-cmd" in result.output
        assert "111111111111" in result.output
        assert "platform" in result.output
        assert "env=prod" in result.output
        assert "True" in result.output

        # Verify persisted correctly
        mgr = TemplateManager(str(tp))
        mgr.load_templates()
        tmpl = mgr.get_template("filtered-cmd")
        assert tmpl is not None
        assert tmpl.accounts == "111111111111,222222222222"
        assert tmpl.team == "platform"
        assert tmpl.tags == ["env=prod", "owner=ops"]
        assert tmpl.save is True


# ===========================================================================
# CLI: template list / show / delete
# ===========================================================================

class TestTemplateListShowDelete:
    def _make_mgr(self, tmp_path, templates=None):
        mgr = TemplateManager(str(tmp_path / "t.json"))
        mgr.load_templates()
        for t in (templates or []):
            mgr.add_template(t)
        mgr.save_templates()
        return str(tmp_path / "t.json")

    def _run(self, args, templates_path):
        runner = CliRunner()
        obj_mock = MagicMock()
        obj_mock.config_manager = None

        config_mock = MagicMock()
        config_mock.get.side_effect = lambda s, k, fallback=None: fallback
        config_mock.get_bool.return_value = False

        with patch('multi_aws_tool.cli.commands.load_or_create_config',
                   return_value=config_mock), \
             patch('multi_aws_tool.config.template_manager.TemplateManager',
                   lambda *a, **kw: _patched_mgr(templates_path)), \
             patch('os.get_terminal_size', return_value=(120, 40)):
            return runner.invoke(cli, args, catch_exceptions=False, obj=obj_mock)

    def test_list_empty(self, tmp_path):
        tp = self._make_mgr(tmp_path)
        result = self._run(['template', 'list'], tp)
        assert result.exit_code == 0
        assert "No templates" in result.output

    def test_list_shows_templates(self, tmp_path):
        tp = self._make_mgr(tmp_path, [
            CommandTemplate(name="a", command="sts get-caller-identity", description="ID check"),
            CommandTemplate(name="b", command="ec2 describe-instances"),
        ])
        result = self._run(['template', 'list'], tp)
        assert result.exit_code == 0
        assert "@a" in result.output
        assert "@b" in result.output

    def test_show_existing(self, tmp_path):
        tp = self._make_mgr(tmp_path, [
            CommandTemplate(name="show-me", command="sts get-caller-identity",
                            description="My template", region="us-east-1"),
        ])
        result = self._run(['template', 'show', 'show-me'], tp)
        assert result.exit_code == 0
        assert "show-me" in result.output
        assert "sts get-caller-identity" in result.output
        assert "My template" in result.output

    def test_show_displays_filter_fields(self, tmp_path):
        """template show renders accounts, team, tags and save when set."""
        tp = self._make_mgr(tmp_path, [
            CommandTemplate(
                name="full",
                command="sts get-caller-identity",
                accounts="111111111111",
                team="platform",
                tags=["env=prod", "owner=ops"],
                save=True,
            ),
        ])
        result = self._run(['template', 'show', 'full'], tp)
        assert result.exit_code == 0
        assert "111111111111" in result.output
        assert "platform" in result.output
        assert "env=prod" in result.output
        assert "True" in result.output

    def test_list_shows_filter_extras(self, tmp_path):
        """template list includes accounts/team/tags/save in extras line."""
        tp = self._make_mgr(tmp_path, [
            CommandTemplate(
                name="with-filters",
                command="sts get-caller-identity",
                accounts="123456789012",
                team="sre",
                tags=["env=staging"],
                save=False,
            ),
        ])
        result = self._run(['template', 'list'], tp)
        assert result.exit_code == 0
        assert "accounts=123456789012" in result.output
        assert "team=sre" in result.output
        assert "env=staging" in result.output
        assert "save=False" in result.output

    def test_show_missing(self, tmp_path):
        tp = self._make_mgr(tmp_path)
        result = self._run(['template', 'show', 'ghost'], tp)
        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_delete_with_confirm_flag(self, tmp_path):
        tp = self._make_mgr(tmp_path, [
            CommandTemplate(name="del-me", command="sts get-caller-identity"),
        ])
        result = self._run(['template', 'delete', 'del-me', '--confirm'], tp)
        assert result.exit_code == 0
        assert "deleted" in result.output.lower()

    def test_delete_missing(self, tmp_path):
        tp = self._make_mgr(tmp_path)
        result = self._run(['template', 'delete', 'nope', '--confirm'], tp)
        assert result.exit_code == 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# Helper so we can inject a TemplateManager backed by a real file
# ---------------------------------------------------------------------------

def _patched_mgr(path: str) -> TemplateManager:
    mgr = TemplateManager(path)
    mgr.load_templates()
    return mgr


# ===========================================================================
# CLI: run @template-name resolution
# ===========================================================================

class TestRunWithTemplate:
    """Test that 'run @name' resolves the template and executes correctly."""

    def _run_with_template(self, template: CommandTemplate,
                           extra_args: list = None,
                           allow_destructive: bool = False):
        """Helper that sets up a full run invocation using a named template."""
        import tempfile, os
        from multi_aws_tool.cli.commands import AppContext

        col = _make_collection(_make_account("000000000001", "Acc1", "test-profile"))
        am = _mock_account_manager(col)

        # Create a real TemplateManager with the given template
        tmp_dir = tempfile.mkdtemp()
        tmgr = TemplateManager(os.path.join(tmp_dir, "templates.json"))
        tmgr.add_template(template)
        tmgr.save_templates()
        tmpl_file = tmgr.templates_file

        runner = CliRunner()

        config_mock = MagicMock()
        config_mock.get.side_effect = lambda s, k, fallback=None: {
            ('general', 'region'): 'us-east-1',
            ('output', 'format'): 'json',
            ('output', 'pattern'): '!A-!c-!d',
        }.get((s, k), fallback)
        config_mock.get_bool.side_effect = lambda s, k, fallback=False: (
            allow_destructive if k == 'allow-destructive-commands' else fallback
        )

        args = ['run', f'@{template.name}',
                '--accounts', '000000000001',
                '--dry-run'] + (extra_args or [])

        # AppContext.ensure_object(AppContext) replaces a plain MagicMock obj,
        # so we patch the class method directly to be a no-op instead.
        with patch('multi_aws_tool.cli.commands.get_account_manager', return_value=am), \
             patch('multi_aws_tool.cli.commands.load_or_create_config',
                   return_value=config_mock), \
             patch('multi_aws_tool.config.template_manager.TemplateManager',
                   lambda *a, **kw: _patched_mgr(str(tmpl_file))), \
             patch.object(AppContext, 'ensure_authenticated', return_value=None), \
             patch('os.get_terminal_size', return_value=(120, 40)):
            return runner.invoke(cli, args, catch_exceptions=False)

    def test_unknown_template_shows_error(self):
        import tempfile, os
        from multi_aws_tool.cli.commands import AppContext

        col = _make_collection(_make_account("000000000001"))
        am = _mock_account_manager(col)

        tmp_dir = tempfile.mkdtemp()
        empty_mgr = TemplateManager(os.path.join(tmp_dir, "t.json"))
        empty_mgr.save_templates()

        runner = CliRunner()
        config_mock = MagicMock()
        config_mock.get.side_effect = lambda s, k, fallback=None: fallback
        config_mock.get_bool.return_value = False

        with patch('multi_aws_tool.cli.commands.get_account_manager', return_value=am), \
             patch('multi_aws_tool.cli.commands.load_or_create_config',
                   return_value=config_mock), \
             patch('multi_aws_tool.config.template_manager.TemplateManager',
                   lambda *a, **kw: _patched_mgr(str(empty_mgr.templates_file))), \
             patch.object(AppContext, 'ensure_authenticated', return_value=None), \
             patch('os.get_terminal_size', return_value=(120, 40)):
            result = runner.invoke(
                cli,
                ['run', '@does-not-exist', '--accounts', '000000000001', '--dry-run'],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_template_run_uses_template_command(self):
        tmpl = CommandTemplate(
            name="id-check",
            command="sts get-caller-identity",
        )
        result = self._run_with_template(tmpl)
        assert result.exit_code == 0
        assert "id-check" in result.output
        assert "sts" in result.output or "get-caller-identity" in result.output

    def test_template_region_override_applied(self):
        tmpl = CommandTemplate(
            name="eu-check",
            command="sts get-caller-identity",
            region="eu-west-1",
        )
        result = self._run_with_template(tmpl)
        assert result.exit_code == 0
        # Region override should appear in the dry-run output
        assert "eu-west-1" in result.output

    def test_destructive_template_blocked(self):
        tmpl = CommandTemplate(
            name="nuke",
            command="s3 delete-bucket --bucket my-bucket",
        )
        result = self._run_with_template(tmpl, allow_destructive=False)
        assert result.exit_code == 0
        assert "destructive" in result.output.lower()

    def test_destructive_template_allowed_when_permitted(self):
        tmpl = CommandTemplate(
            name="allowed-delete",
            command="s3 delete-object --bucket b --key k",
        )
        result = self._run_with_template(tmpl, allow_destructive=True)
        assert result.exit_code == 0
        # Should NOT print "destructive" error
        assert "destructive" not in result.output.lower()

    # ------------------------------------------------------------------
    # Account filter tests
    # ------------------------------------------------------------------

    def _run_with_template_no_cli_filters(self, template: CommandTemplate,
                                          extra_args: list = None,
                                          allow_destructive: bool = False):
        """Like _run_with_template but does NOT pass --accounts on the CLI,
        so template-level account filters are the only source."""
        import tempfile, os
        from multi_aws_tool.cli.commands import AppContext

        col = _make_collection(_make_account("000000000001", "Acc1", "test-profile"))
        am = _mock_account_manager(col)

        tmp_dir = tempfile.mkdtemp()
        tmgr = TemplateManager(os.path.join(tmp_dir, "templates.json"))
        tmgr.add_template(template)
        tmgr.save_templates()
        tmpl_file = tmgr.templates_file

        runner = CliRunner()

        config_mock = MagicMock()
        config_mock.get.side_effect = lambda s, k, fallback=None: {
            ('general', 'region'): 'us-east-1',
            ('output', 'format'): 'json',
            ('output', 'pattern'): '!A-!c-!d',
        }.get((s, k), fallback)
        config_mock.get_bool.side_effect = lambda s, k, fallback=False: (
            allow_destructive if k == 'allow-destructive-commands' else fallback
        )

        args = ['run', f'@{template.name}', '--dry-run'] + (extra_args or [])

        with patch('multi_aws_tool.cli.commands.get_account_manager', return_value=am), \
             patch('multi_aws_tool.cli.commands.load_or_create_config',
                   return_value=config_mock), \
             patch('multi_aws_tool.config.template_manager.TemplateManager',
                   lambda *a, **kw: _patched_mgr(str(tmpl_file))), \
             patch.object(AppContext, 'ensure_authenticated', return_value=None), \
             patch('os.get_terminal_size', return_value=(120, 40)):
            return runner.invoke(cli, args, catch_exceptions=False)

    def test_template_accounts_applied_when_not_on_cli(self):
        """accounts field from the template is used when --accounts not on CLI."""
        tmpl = CommandTemplate(
            name="acct-tmpl",
            command="sts get-caller-identity",
            accounts="000000000001",
        )
        result = self._run_with_template_no_cli_filters(tmpl)
        assert result.exit_code == 0
        # Should have resolved the account and printed its name / ID
        assert "Acc1" in result.output or "000000000001" in result.output

    def test_cli_accounts_override_template_accounts(self):
        """--accounts on the CLI takes precedence over template accounts."""
        tmpl = CommandTemplate(
            name="acct-override",
            command="sts get-caller-identity",
            accounts="999999999999",   # different from what will be on CLI
        )
        # Pass --accounts on the CLI pointing to the real account in the mock
        result = self._run_with_template(tmpl)
        assert result.exit_code == 0
        # CLI-specified account (000000000001) is present, not the template one
        assert "000000000001" in result.output or "Acc1" in result.output

    def test_template_save_flag_applied(self):
        """save=True in a template triggers file-save behaviour."""
        import tempfile
        import os

        tmp_out = tempfile.mkdtemp()

        tmpl = CommandTemplate(
            name="save-tmpl",
            command="sts get-caller-identity",
            accounts="000000000001",
            save=True,
        )

        col = _make_collection(_make_account("000000000001", "Acc1", "test-profile"))
        am = _mock_account_manager(col)

        tmp_dir = tempfile.mkdtemp()
        tmgr = TemplateManager(os.path.join(tmp_dir, "templates.json"))
        tmgr.add_template(tmpl)
        tmgr.save_templates()
        tmpl_file = tmgr.templates_file

        from multi_aws_tool.cli.commands import AppContext

        runner = CliRunner()

        config_mock = MagicMock()
        config_mock.get.side_effect = lambda s, k, fallback=None: {
            ('general', 'region'): 'us-east-1',
            ('output', 'format'): 'json',
            ('output', 'pattern'): '!A-!c-!d',
            ('output', 'path'): tmp_out,
        }.get((s, k), fallback)
        config_mock.get_bool.return_value = False

        args = ['run', '@save-tmpl', '--dry-run']

        with patch('multi_aws_tool.cli.commands.get_account_manager', return_value=am), \
             patch('multi_aws_tool.cli.commands.load_or_create_config',
                   return_value=config_mock), \
             patch('multi_aws_tool.config.template_manager.TemplateManager',
                   lambda *a, **kw: _patched_mgr(str(tmpl_file))), \
             patch.object(AppContext, 'ensure_authenticated', return_value=None), \
             patch('os.get_terminal_size', return_value=(120, 40)):
            result = runner.invoke(cli, args, catch_exceptions=False)

        assert result.exit_code == 0
        # The save path should be mentioned in dry-run output
        assert tmp_out in result.output or "saved" in result.output.lower()
