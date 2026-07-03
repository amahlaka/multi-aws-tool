"""
Tests for account tag filtering and AWS Organizations tag sync features
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, call
from botocore.exceptions import ClientError

from multi_aws_tool.models.account import Account, AccountCollection, AccountStatus, Role
from multi_aws_tool.aws.organizations_client import (
    OrganizationsClient,
    OrganizationsAccessError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account(account_id: str, name: str = "TestAccount", tags: dict = None) -> Account:
    return Account(
        id=account_id,
        name=name,
        status=AccountStatus.ACTIVE,
        tags=tags or {},
    )


def _client_error(code: str) -> ClientError:
    return ClientError(
        error_response={'Error': {'Code': code, 'Message': 'Test error'}},
        operation_name='ListTagsForResource',
    )


# ---------------------------------------------------------------------------
# Account model: to_dict / from_dict round-trip for tags
# ---------------------------------------------------------------------------

class TestAccountTagsSerialization:
    def test_to_dict_includes_tags(self):
        account = _make_account("123456789012", tags={"env": "prod", "owner": "team-a"})
        d = account.to_dict()
        assert d['tags'] == {"env": "prod", "owner": "team-a"}

    def test_to_dict_empty_tags(self):
        account = _make_account("123456789012")
        d = account.to_dict()
        assert d['tags'] == {}

    def test_from_dict_restores_tags(self):
        data = {
            'id': '123456789012',
            'name': 'Test',
            'status': 'active',
            'roles': [],
            'profile_name': None,
            'last_updated': datetime.now().isoformat(),
            'product_team': None,
            'tags': {'env': 'staging', 'cost-center': 'cc-42'},
        }
        account = Account.from_dict(data)
        assert account.tags == {'env': 'staging', 'cost-center': 'cc-42'}

    def test_from_dict_missing_tags_defaults_to_empty(self):
        data = {
            'id': '123456789012',
            'name': 'Test',
            'status': 'active',
            'roles': [],
            'profile_name': None,
            'last_updated': datetime.now().isoformat(),
            'product_team': None,
            # 'tags' key absent – legacy data
        }
        account = Account.from_dict(data)
        assert account.tags == {}

    def test_round_trip(self):
        original = _make_account("123456789012", tags={"a": "1", "b": "2"})
        restored = Account.from_dict(original.to_dict())
        assert restored.tags == original.tags


# ---------------------------------------------------------------------------
# AccountCollection: get_accounts_by_tags
# ---------------------------------------------------------------------------

class TestAccountCollectionTagFiltering:
    def _make_collection(self) -> AccountCollection:
        col = AccountCollection()
        col.add_account(_make_account("000000000001", tags={"env": "prod", "owner": "alpha"}))
        col.add_account(_make_account("000000000002", tags={"env": "staging", "owner": "alpha"}))
        col.add_account(_make_account("000000000003", tags={"env": "prod", "owner": "beta"}))
        col.add_account(_make_account("000000000004", tags={}))
        return col

    def test_single_tag_match(self):
        col = self._make_collection()
        results = col.get_accounts_by_tags({"env": "prod"})
        ids = {a.id for a in results}
        assert ids == {"000000000001", "000000000003"}

    def test_multiple_tags_all_must_match(self):
        col = self._make_collection()
        results = col.get_accounts_by_tags({"env": "prod", "owner": "alpha"})
        ids = {a.id for a in results}
        assert ids == {"000000000001"}

    def test_no_match(self):
        col = self._make_collection()
        results = col.get_accounts_by_tags({"env": "dev"})
        assert results == []

    def test_empty_filter_returns_all(self):
        col = self._make_collection()
        results = col.get_accounts_by_tags({})
        assert len(results) == 4

    def test_account_with_no_tags_does_not_match(self):
        col = self._make_collection()
        results = col.get_accounts_by_tags({"env": "prod"})
        ids = {a.id for a in results}
        assert "000000000004" not in ids


# ---------------------------------------------------------------------------
# OrganizationsClient
# ---------------------------------------------------------------------------

class TestOrganizationsClient:
    def _mock_paginator(self, pages):
        """Return a paginator mock that yields the supplied pages."""
        paginator = MagicMock()
        paginator.paginate.return_value = pages
        return paginator

    def test_get_tags_returns_dict(self):
        pages = [{'Tags': [{'Key': 'env', 'Value': 'prod'}, {'Key': 'owner', 'Value': 'team-a'}]}]
        client = OrganizationsClient()
        mock_boto = MagicMock()
        mock_boto.get_paginator.return_value = self._mock_paginator(pages)
        client._client = mock_boto

        tags = client.get_tags_for_account("123456789012")
        assert tags == {'env': 'prod', 'owner': 'team-a'}

    def test_get_tags_empty(self):
        pages = [{'Tags': []}]
        client = OrganizationsClient()
        mock_boto = MagicMock()
        mock_boto.get_paginator.return_value = self._mock_paginator(pages)
        client._client = mock_boto

        tags = client.get_tags_for_account("123456789012")
        assert tags == {}

    def test_get_tags_multiple_pages(self):
        pages = [
            {'Tags': [{'Key': 'env', 'Value': 'prod'}]},
            {'Tags': [{'Key': 'owner', 'Value': 'team-b'}]},
        ]
        client = OrganizationsClient()
        mock_boto = MagicMock()
        mock_boto.get_paginator.return_value = self._mock_paginator(pages)
        client._client = mock_boto

        tags = client.get_tags_for_account("123456789012")
        assert tags == {'env': 'prod', 'owner': 'team-b'}

    @pytest.mark.parametrize("error_code", [
        'AccessDenied',
        'AccessDeniedException',
        'AWSOrganizationsNotInUseException',
        'AccountNotFoundException',
    ])
    def test_get_tags_unavailable_errors_return_empty(self, error_code):
        client = OrganizationsClient()
        mock_boto = MagicMock()
        mock_boto.get_paginator.side_effect = _client_error(error_code)
        client._client = mock_boto

        # Should not raise – returns empty dict
        tags = client.get_tags_for_account("123456789012")
        assert tags == {}

    def test_get_tags_unexpected_client_error_raises(self):
        client = OrganizationsClient()
        mock_boto = MagicMock()
        mock_boto.get_paginator.side_effect = _client_error("SomeUnexpectedError")
        client._client = mock_boto

        with pytest.raises(OrganizationsAccessError):
            client.get_tags_for_account("123456789012")

    def test_get_tags_for_accounts_multiple(self):
        def side_effect(account_id):
            return {'env': 'prod'} if account_id == '000000000001' else {}

        client = OrganizationsClient()
        client.get_tags_for_account = MagicMock(side_effect=side_effect)

        result = client.get_tags_for_accounts(['000000000001', '000000000002'])
        assert result == {'000000000001': {'env': 'prod'}, '000000000002': {}}


# ---------------------------------------------------------------------------
# AccountManager: sync_account_tags
# ---------------------------------------------------------------------------

class TestAccountManagerSyncTags:
    def _make_manager(self, accounts):
        """Return an AccountManager with mocked data_manager."""
        from multi_aws_tool.aws.account_manager import AccountManager

        manager = AccountManager.__new__(AccountManager)

        col = AccountCollection()
        for acc in accounts:
            col.add_account(acc)

        data_manager = MagicMock()
        data_manager.load_accounts.return_value = col
        data_manager.save_accounts = MagicMock()

        manager.data_manager = data_manager
        manager.sso_client = MagicMock()
        return manager, col

    def test_sync_tags_updates_accounts(self):
        account = _make_account("000000000001")
        manager, col = self._make_manager([account])

        org_client_mock = MagicMock()
        org_client_mock.get_tags_for_account.return_value = {'env': 'prod'}

        with patch(
            'multi_aws_tool.aws.account_manager.OrganizationsClient',
            return_value=org_client_mock,
        ):
            counts = manager.sync_account_tags()

        assert counts['synced'] == 1
        assert counts['skipped'] == 0
        assert counts['failed'] == 0
        assert col.get_account("000000000001").tags == {'env': 'prod'}
        manager.data_manager.save_accounts.assert_called_once()

    def test_sync_tags_skips_no_tags(self):
        account = _make_account("000000000001")
        manager, col = self._make_manager([account])

        org_client_mock = MagicMock()
        org_client_mock.get_tags_for_account.return_value = {}

        with patch(
            'multi_aws_tool.aws.account_manager.OrganizationsClient',
            return_value=org_client_mock,
        ):
            counts = manager.sync_account_tags()

        assert counts['synced'] == 0
        assert counts['skipped'] == 1
        # No save when nothing changed
        manager.data_manager.save_accounts.assert_not_called()

    def test_sync_tags_handles_access_error_gracefully(self):
        account = _make_account("000000000001")
        manager, _ = self._make_manager([account])

        org_client_mock = MagicMock()
        org_client_mock.get_tags_for_account.side_effect = OrganizationsAccessError(
            "Access denied"
        )

        with patch(
            'multi_aws_tool.aws.account_manager.OrganizationsClient',
            return_value=org_client_mock,
        ):
            counts = manager.sync_account_tags()

        assert counts['failed'] == 1
        assert counts['synced'] == 0

    def test_sync_tags_empty_accounts_returns_zeros(self):
        manager, _ = self._make_manager([])

        counts = manager.sync_account_tags()
        assert counts == {'synced': 0, 'skipped': 0, 'failed': 0}

    def test_sync_tags_passes_profile_to_client(self):
        account = _make_account("000000000001")
        manager, _ = self._make_manager([account])

        org_client_mock = MagicMock()
        org_client_mock.get_tags_for_account.return_value = {'k': 'v'}

        with patch(
            'multi_aws_tool.aws.account_manager.OrganizationsClient',
        ) as MockOrg:
            MockOrg.return_value = org_client_mock
            manager.sync_account_tags(profile_name='mgmt-profile')

        MockOrg.assert_called_once_with(profile_name='mgmt-profile')


# ---------------------------------------------------------------------------
# AccountManager: get_accounts_by_tags
# ---------------------------------------------------------------------------

class TestAccountManagerGetAccountsByTags:
    def test_filter_accounts_by_tag(self):
        from multi_aws_tool.aws.account_manager import AccountManager

        manager = AccountManager.__new__(AccountManager)
        col = AccountCollection()
        col.add_account(_make_account("000000000001", tags={"env": "prod"}))
        col.add_account(_make_account("000000000002", tags={"env": "dev"}))

        data_manager = MagicMock()
        data_manager.load_accounts.return_value = col
        manager.data_manager = data_manager
        manager.sso_client = MagicMock()

        results = manager.get_accounts_by_tags({"env": "prod"})
        assert len(results) == 1
        assert results[0].id == "000000000001"
