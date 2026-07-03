"""
AWS Organizations client for MultiAWSTool
Handles fetching account tags from AWS Organizations with graceful fallback
"""

import boto3
import logging
from typing import Dict, List, Optional
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Error codes that indicate Organizations is not accessible (not a hard failure)
_UNAVAILABLE_ERRORS = frozenset({
    'AccessDenied',
    'AccessDeniedException',
    'AWSOrganizationsNotInUseException',
    'AccountNotFoundException',
    'InvalidInputException',
    'ServiceException',
    'TooManyRequestsException',
})


class OrganizationsAccessError(Exception):
    """Raised when Organizations API is unexpectedly inaccessible"""


class OrganizationsClient:
    """Client for fetching account metadata from AWS Organizations"""

    def __init__(self, profile_name: Optional[str] = None, region: str = "us-east-1"):
        """
        Initialize Organizations client.

        Args:
            profile_name: AWS profile name with Organizations access.
                          If None, uses the default credential chain.
            region:       AWS region for the Organizations API endpoint.
        """
        self.profile_name = profile_name
        self.region = region
        self._client = None

    def _get_client(self):
        """Lazily create and return the boto3 Organizations client."""
        if self._client is None:
            session = (
                boto3.Session(profile_name=self.profile_name)
                if self.profile_name
                else boto3.Session()
            )
            self._client = session.client('organizations', region_name=self.region)
        return self._client

    def get_tags_for_account(self, account_id: str) -> Dict[str, str]:
        """
        Fetch tags for a single AWS account from Organizations.

        Returns an empty dict if Organizations access is unavailable, so
        callers can treat no-tags the same as an unfetched state.

        Args:
            account_id: 12-digit AWS account ID

        Returns:
            Dict mapping tag key to tag value (may be empty)
        """
        try:
            client = self._get_client()
            tags: Dict[str, str] = {}

            paginator = client.get_paginator('list_tags_for_resource')
            for page in paginator.paginate(ResourceId=account_id):
                for tag in page.get('Tags', []):
                    tags[tag['Key']] = tag['Value']

            logger.debug(
                f"Fetched {len(tags)} tag(s) for account {account_id}"
            )
            return tags

        except ClientError as exc:
            error_code = exc.response['Error']['Code']
            if error_code in _UNAVAILABLE_ERRORS:
                logger.warning(
                    f"Organizations access unavailable for account {account_id} "
                    f"(error: {error_code}); skipping tags"
                )
                return {}
            raise OrganizationsAccessError(
                f"Failed to fetch tags for account {account_id}: {exc}"
            ) from exc

        except Exception as exc:  # pragma: no cover – unexpected SDK errors
            logger.warning(
                f"Unexpected error fetching Organizations tags for account "
                f"{account_id}: {exc}"
            )
            return {}

    def get_tags_for_accounts(
        self, account_ids: List[str]
    ) -> Dict[str, Dict[str, str]]:
        """
        Fetch tags for multiple AWS accounts.

        Falls back cleanly per-account when Organizations access is unavailable.

        Args:
            account_ids: List of 12-digit AWS account IDs

        Returns:
            Dict mapping account_id -> tag dict
        """
        results: Dict[str, Dict[str, str]] = {}
        for account_id in account_ids:
            results[account_id] = self.get_tags_for_account(account_id)
        return results
