"""
Tests for the TUI module and the `tui` CLI command.
"""

import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from multi_aws_tool.cli.commands import cli
from multi_aws_tool.models.account import Account, AccountCollection, AccountStatus, Role
from multi_aws_tool.models.template import CommandTemplate
from multi_aws_tool.tui.app import TUIApp, _truncate


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_account(acc_id, name="Test", team=None, profile=None, roles=None):
    return Account(
        id=acc_id,
        name=name,
        status=AccountStatus.ACTIVE,
        product_team=team,
        profile_name=profile,
        roles=roles or [],
    )


def _make_collection(*accounts):
    col = AccountCollection()
    for a in accounts:
        col.add_account(a)
    return col


def _mock_account_manager(collection):
    mgr = MagicMock()
    mgr.data_manager.load_accounts.return_value = collection
    mgr.data_manager.save_accounts.return_value = None
    return mgr


def _run_cli(args, manager):
    """Invoke CLI with a patched account manager."""
    runner = CliRunner()
    with patch("multi_aws_tool.cli.commands.get_account_manager", return_value=manager), \
         patch("os.get_terminal_size", return_value=(120, 40)):
        return runner.invoke(cli, args, catch_exceptions=False,
                             obj=MagicMock(config_manager=None))


# ─── Unit tests for TUIApp helpers ───────────────────────────────────────────

class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_exact_length_unchanged(self):
        assert _truncate("hello", 5) == "hello"

    def test_truncated_with_ellipsis(self):
        result = _truncate("hello world", 8)
        assert len(result) == 8
        assert result.endswith("…")

    def test_zero_max_len(self):
        assert _truncate("hello", 0) == ""

    def test_negative_max_len(self):
        assert _truncate("hello", -1) == ""


class TestTUIAppInit:
    def test_init_stores_managers(self):
        am = MagicMock()
        cm = MagicMock()
        app = TUIApp(am, cm)
        assert app.account_manager is am
        assert app.config_manager is cm
        assert app._collection is None

    def test_get_collection_loads_from_manager(self):
        col = _make_collection(_make_account("123456789012"))
        am  = _mock_account_manager(col)
        app = TUIApp(am, None)
        result = app._get_collection()
        assert result is col
        am.data_manager.load_accounts.assert_called_once()

    def test_get_collection_cached(self):
        col = _make_collection(_make_account("123456789012"))
        am  = _mock_account_manager(col)
        app = TUIApp(am, None)
        app._get_collection()
        app._get_collection()
        # Should only load once
        am.data_manager.load_accounts.assert_called_once()

    def test_reload_collection_clears_cache(self):
        col = _make_collection(_make_account("123456789012"))
        am  = _mock_account_manager(col)
        app = TUIApp(am, None)
        app._get_collection()
        app._reload_collection()
        assert am.data_manager.load_accounts.call_count == 2

    def test_get_collection_returns_none_on_error(self):
        am = MagicMock()
        am.data_manager.load_accounts.side_effect = RuntimeError("no file")
        app = TUIApp(am, None)
        result = app._get_collection()
        assert result is None

    def test_save_collection_calls_manager(self):
        col = _make_collection(_make_account("123456789012"))
        am  = _mock_account_manager(col)
        app = TUIApp(am, None)
        app._get_collection()
        assert app._save_collection() is True
        am.data_manager.save_accounts.assert_called_once_with(col)

    def test_save_collection_returns_false_on_error(self):
        col = _make_collection(_make_account("123456789012"))
        am  = _mock_account_manager(col)
        am.data_manager.save_accounts.side_effect = OSError("disk full")
        app = TUIApp(am, None)
        app._collection = col
        assert app._save_collection() is False


class TestNavHelper:
    def test_nav_up(self):
        sel, scr = TUIApp._nav(ord('\x1b') - 1, 5, 0, 10, 5)  # dummy key
        # No change for arbitrary key
        assert sel == 5

    def test_nav_down_increments(self):
        import curses
        sel, scr = TUIApp._nav(curses.KEY_DOWN, 0, 0, 5, 3)
        assert sel == 1

    def test_nav_up_decrements(self):
        import curses
        sel, scr = TUIApp._nav(curses.KEY_UP, 3, 0, 5, 3)
        assert sel == 2

    def test_nav_down_at_end_does_not_overflow(self):
        import curses
        sel, scr = TUIApp._nav(curses.KEY_DOWN, 4, 0, 5, 3)
        assert sel == 4  # already at last item

    def test_nav_up_at_start_does_not_underflow(self):
        import curses
        sel, scr = TUIApp._nav(curses.KEY_UP, 0, 0, 5, 3)
        assert sel == 0

    def test_nav_scrolls_down(self):
        import curses
        sel, scr = TUIApp._nav(curses.KEY_DOWN, 2, 0, 10, 3)
        assert sel == 3
        assert scr == 1  # scroll adjusted

    def test_nav_home(self):
        import curses
        sel, scr = TUIApp._nav(curses.KEY_HOME, 7, 4, 10, 3)
        assert sel == 0
        assert scr == 0

    def test_nav_end(self):
        import curses
        sel, scr = TUIApp._nav(curses.KEY_END, 0, 0, 10, 3)
        assert sel == 9

    def test_nav_page_up(self):
        import curses
        sel, scr = TUIApp._nav(curses.KEY_PPAGE, 8, 5, 10, 3)
        assert sel == 5

    def test_nav_page_down(self):
        import curses
        sel, scr = TUIApp._nav(curses.KEY_NPAGE, 1, 0, 10, 3)
        assert sel == 4


# ─── TUI command smoke test ───────────────────────────────────────────────────

class TestTuiCommand:
    def test_tui_command_available(self):
        """The 'tui' command should be registered in the CLI."""
        runner = CliRunner()
        with patch('os.get_terminal_size', return_value=(120, 40)):
            result = runner.invoke(cli, ['tui', '--help'])
        assert result.exit_code == 0
        assert 'TUI' in result.output or 'interactive' in result.output.lower()

    def test_tui_exits_cleanly_when_app_returns_none(self):
        """When TUIApp.run() returns None the command should complete quietly."""
        col = _make_collection(_make_account("123456789012", "Acme"))
        manager = _mock_account_manager(col)
        runner = CliRunner()
        with patch("multi_aws_tool.cli.commands.get_account_manager", return_value=manager), \
             patch("os.get_terminal_size", return_value=(120, 40)), \
             patch("multi_aws_tool.tui.app.TUIApp.run", return_value=None):
            result = runner.invoke(
                cli, ["tui"], catch_exceptions=False,
                obj=MagicMock(config_manager=None, verbose=False,
                              account_manager=None)
            )
        assert result.exit_code == 0

    def test_tui_dry_run_prints_commands(self):
        """When TUIApp.run() returns a dry-run action the commands should be printed."""
        acc = _make_account("123456789012", "Acme", profile="multi-aws-Acme")
        col = _make_collection(acc)
        manager = _mock_account_manager(col)
        run_result = {
            'action':   'run',
            'accounts': ['123456789012'],
            'command':  'sts get-caller-identity',
            'parallel': False,
            'region':   '',
            'dry_run':  True,
            'role':     '',
        }
        runner = CliRunner()
        with patch("multi_aws_tool.cli.commands.get_account_manager", return_value=manager), \
             patch("os.get_terminal_size", return_value=(120, 40)), \
             patch("multi_aws_tool.tui.app.TUIApp.run", return_value=run_result):
            result = runner.invoke(
                cli, ["tui"], catch_exceptions=False,
                obj=MagicMock(config_manager=None, verbose=False,
                              account_manager=None)
            )
        assert result.exit_code == 0
        assert 'sts get-caller-identity' in result.output
        assert 'Dry-run' in result.output

    def test_tui_skips_accounts_without_profile(self):
        """Accounts without a configured profile should be skipped in run mode."""
        acc = _make_account("123456789012", "Acme")  # no profile_name
        col = _make_collection(acc)
        manager = _mock_account_manager(col)
        run_result = {
            'action':   'run',
            'accounts': ['123456789012'],
            'command':  'sts get-caller-identity',
            'parallel': False,
            'region':   '',
            'dry_run':  True,
            'role':     '',
        }
        runner = CliRunner()
        with patch("multi_aws_tool.cli.commands.get_account_manager", return_value=manager), \
             patch("os.get_terminal_size", return_value=(120, 40)), \
             patch("multi_aws_tool.tui.app.TUIApp.run", return_value=run_result):
            result = runner.invoke(
                cli, ["tui"], catch_exceptions=False,
                obj=MagicMock(config_manager=None, verbose=False,
                              account_manager=None)
            )
        assert result.exit_code == 0
        assert 'No profile' in result.output or 'skipping' in result.output

    def test_tui_reports_error_when_account_manager_fails(self):
        """If the account manager cannot be initialised, an error is shown."""
        runner = CliRunner()
        with patch("multi_aws_tool.cli.commands.get_account_manager",
                   side_effect=Exception("SSO not configured")), \
             patch("os.get_terminal_size", return_value=(120, 40)):
            result = runner.invoke(
                cli, ["tui"], catch_exceptions=False,
                obj=MagicMock(config_manager=None, verbose=False,
                              account_manager=None)
            )
        assert result.exit_code == 0
        assert '❌' in result.output
