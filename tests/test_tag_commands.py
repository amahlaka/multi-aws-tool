"""
Tests for list-tags, set-tag, and remove-tag CLI commands
"""

import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from multi_aws_tool.models.account import Account, AccountCollection, AccountStatus
from multi_aws_tool.cli.commands import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account(account_id: str, name: str = "TestAccount", tags: dict = None,
                  profile_name: str = None) -> Account:
    return Account(
        id=account_id,
        name=name,
        status=AccountStatus.ACTIVE,
        tags=tags or {},
        profile_name=profile_name,
    )


def _make_collection(*accounts: Account) -> AccountCollection:
    col = AccountCollection()
    for acc in accounts:
        col.add_account(acc)
    return col


def _mock_account_manager(collection: AccountCollection) -> MagicMock:
    """Return a minimal AccountManager mock backed by the given collection."""
    manager = MagicMock()
    manager.data_manager.load_accounts.return_value = collection
    manager.data_manager.file_path = "/fake/accounts.json"
    manager.data_manager.save_accounts = MagicMock()

    def _get_account(aid):
        return collection.get_account(aid)

    def _get_by_team(team):
        return collection.get_accounts_by_product_team(team)

    manager.get_account.side_effect = _get_account
    manager.get_accounts_by_team.side_effect = _get_by_team
    return manager


def _run(args, manager):
    """Run CLI args with a patched account manager and AppContext."""
    runner = CliRunner()
    with patch('multi_aws_tool.cli.commands.get_account_manager', return_value=manager), \
         patch('os.get_terminal_size', return_value=(120, 40)):
        return runner.invoke(cli, args, catch_exceptions=False,
                             obj=MagicMock(config_manager=None))


# ---------------------------------------------------------------------------
# list-tags
# ---------------------------------------------------------------------------

class TestListTagsCommand:
    def test_lists_all_accounts_when_no_filter(self):
        col = _make_collection(
            _make_account("000000000001", "Acc1", {"env": "prod"}),
            _make_account("000000000002", "Acc2", {"env": "dev"}),
        )
        result = _run(['list-tags'], _mock_account_manager(col))
        assert result.exit_code == 0
        assert "Acc1" in result.output
        assert "env = prod" in result.output
        assert "Acc2" in result.output
        assert "env = dev" in result.output

    def test_filters_by_accounts(self):
        col = _make_collection(
            _make_account("000000000001", "Acc1", {"env": "prod"}),
            _make_account("000000000002", "Acc2", {"env": "dev"}),
        )
        result = _run(['list-tags', '--accounts', '000000000001'],
                      _mock_account_manager(col))
        assert result.exit_code == 0
        assert "Acc1" in result.output
        assert "Acc2" not in result.output

    def test_filters_by_team(self):
        acc1 = _make_account("000000000001", "Acc1", {"env": "prod"})
        acc1.product_team = "alpha"
        acc2 = _make_account("000000000002", "Acc2", {"env": "dev"})
        acc2.product_team = "beta"
        col = _make_collection(acc1, acc2)
        result = _run(['list-tags', '--team', 'alpha'], _mock_account_manager(col))
        assert result.exit_code == 0
        assert "Acc1" in result.output
        assert "Acc2" not in result.output

    def test_shows_no_tags_message_for_untagged_accounts(self):
        col = _make_collection(_make_account("000000000001", "Acc1"))
        result = _run(['list-tags'], _mock_account_manager(col))
        assert result.exit_code == 0
        assert "no tags" in result.output

    def test_no_accounts_found(self):
        col = AccountCollection()
        result = _run(['list-tags'], _mock_account_manager(col))
        assert result.exit_code == 0
        assert "No matching accounts" in result.output


# ---------------------------------------------------------------------------
# set-tag
# ---------------------------------------------------------------------------

class TestSetTagCommand:
    def test_requires_accounts_or_team(self):
        col = _make_collection(_make_account("000000000001"))
        result = _run(['set-tag', '--tag', 'env=prod'], _mock_account_manager(col))
        assert result.exit_code == 0
        assert "Specify --accounts or --team" in result.output

    def test_rejects_invalid_tag_format(self):
        col = _make_collection(_make_account("000000000001"))
        result = _run(['set-tag', '--accounts', '000000000001', '--tag', 'bad-format'],
                      _mock_account_manager(col))
        assert result.exit_code == 0
        assert "Invalid tag format" in result.output

    def test_sets_new_tag(self):
        account = _make_account("000000000001", "Acc1")
        col = _make_collection(account)
        manager = _mock_account_manager(col)
        result = _run(['set-tag', '--accounts', '000000000001', '--tag', 'env=prod'],
                      manager)
        assert result.exit_code == 0
        assert account.tags.get("env") == "prod"
        manager.data_manager.save_accounts.assert_called_once()

    def test_does_not_overwrite_existing_tag_without_flag(self):
        account = _make_account("000000000001", "Acc1", {"env": "dev"})
        col = _make_collection(account)
        manager = _mock_account_manager(col)
        result = _run(['set-tag', '--accounts', '000000000001', '--tag', 'env=prod'],
                      manager)
        assert result.exit_code == 0
        assert account.tags["env"] == "dev"  # unchanged
        manager.data_manager.save_accounts.assert_not_called()

    def test_overwrites_with_flag(self):
        account = _make_account("000000000001", "Acc1", {"env": "dev"})
        col = _make_collection(account)
        manager = _mock_account_manager(col)
        result = _run(['set-tag', '--accounts', '000000000001', '--tag', 'env=prod', '--overwrite'],
                      manager)
        assert result.exit_code == 0
        assert account.tags["env"] == "prod"
        manager.data_manager.save_accounts.assert_called_once()

    def test_sets_multiple_tags_at_once(self):
        account = _make_account("000000000001", "Acc1")
        col = _make_collection(account)
        result = _run(
            ['set-tag', '--accounts', '000000000001',
             '--tag', 'env=prod', '--tag', 'owner=team-a'],
            _mock_account_manager(col),
        )
        assert result.exit_code == 0
        assert account.tags == {"env": "prod", "owner": "team-a"}

    def test_no_matching_accounts(self):
        col = AccountCollection()
        result = _run(['set-tag', '--accounts', '000000000001', '--tag', 'env=prod'],
                      _mock_account_manager(col))
        assert result.exit_code == 0
        assert "No matching accounts" in result.output


# ---------------------------------------------------------------------------
# remove-tag
# ---------------------------------------------------------------------------

class TestRemoveTagCommand:
    def test_requires_accounts_or_team(self):
        col = _make_collection(_make_account("000000000001"))
        result = _run(['remove-tag', '--key', 'env'], _mock_account_manager(col))
        assert result.exit_code == 0
        assert "Specify --accounts or --team" in result.output

    def test_removes_existing_tag(self):
        account = _make_account("000000000001", "Acc1", {"env": "prod", "owner": "team-a"})
        col = _make_collection(account)
        manager = _mock_account_manager(col)
        result = _run(['remove-tag', '--accounts', '000000000001', '--key', 'env'],
                      manager)
        assert result.exit_code == 0
        assert "env" not in account.tags
        assert account.tags.get("owner") == "team-a"
        manager.data_manager.save_accounts.assert_called_once()

    def test_skips_missing_key_gracefully(self):
        account = _make_account("000000000001", "Acc1", {"owner": "team-a"})
        col = _make_collection(account)
        manager = _mock_account_manager(col)
        result = _run(['remove-tag', '--accounts', '000000000001', '--key', 'env'],
                      manager)
        assert result.exit_code == 0
        assert "not present" in result.output
        manager.data_manager.save_accounts.assert_not_called()

    def test_removes_multiple_keys(self):
        account = _make_account("000000000001", "Acc1",
                                {"env": "prod", "owner": "team-a", "cost": "cc-1"})
        col = _make_collection(account)
        result = _run(
            ['remove-tag', '--accounts', '000000000001',
             '--key', 'env', '--key', 'owner'],
            _mock_account_manager(col),
        )
        assert result.exit_code == 0
        assert "env" not in account.tags
        assert "owner" not in account.tags
        assert account.tags.get("cost") == "cc-1"

    def test_no_matching_accounts(self):
        col = AccountCollection()
        result = _run(['remove-tag', '--accounts', '000000000001', '--key', 'env'],
                      _mock_account_manager(col))
        assert result.exit_code == 0
        assert "No matching accounts" in result.output
