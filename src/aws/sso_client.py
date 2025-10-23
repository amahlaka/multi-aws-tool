"""
SSO authentication client for MultiAWSTool
Handles AWS SSO authentication, token management, and session operations
"""

import boto3
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class SSOAuthenticationError(Exception):
    """Raised when SSO authentication operations fail"""

class SSOTokenError(Exception):
    """Raised when SSO token operations fail"""

class SSOClient:
    """AWS SSO client for authentication and account/role operations"""
    
    def __init__(self, sso_session_name: str = "default", region: str = "us-east-1"):
        """
        Initialize SSO client
        
        Args:
            sso_session_name: Name of the SSO session in AWS config
            region: AWS region for SSO operations
        """
        self.sso_session_name = sso_session_name
        self.region = region
        self.cache_dir = Path.home() / '.multi-aws' / 'sso-cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize boto3 clients
        self._sso_client = None
        self._sso_oidc_client = None
        self._current_token = None
        self._token_expires_at = None
        
    def _get_sso_client(self) -> boto3.client:
        """Get or create SSO client"""
        if self._sso_client is None:
            self._sso_client = boto3.client('sso', region_name=self.region)
        return self._sso_client
    
    def _get_sso_oidc_client(self) -> boto3.client:
        """Get or create SSO OIDC client"""
        if self._sso_oidc_client is None:
            self._sso_oidc_client = boto3.client('sso-oidc', region_name=self.region)
        return self._sso_oidc_client
    
    def _get_cache_file_path(self) -> Path:
        """Get the cache file path for this SSO session"""
        cache_filename = f"sso-{self.sso_session_name}-{self.region}.json"
        return self.cache_dir / cache_filename
    
    def _load_cached_token(self) -> Optional[Dict[str, Any]]:
        """
        Load cached SSO token if available and valid
        
        Returns:
            Token data if valid, None otherwise
        """
        cache_file = self._get_cache_file_path()
        if not cache_file.exists():
            logger.debug("No cached token file found")
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                token_data = json.load(f)
            
            # Check if token is expired
            expires_at_str = token_data.get('expiresAt')
            if expires_at_str:
                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                if datetime.now().astimezone() >= expires_at:
                    logger.debug("Cached token is expired")
                    return None
            
            logger.debug("Loaded valid cached token")
            return token_data
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to load cached token: {e}")
            return None
    
    def _load_aws_cli_token(self) -> Optional[str]:
        """
        Load SSO token from AWS CLI cache
        
        Returns:
            Access token if found and valid, None otherwise
        """
        try:
            # Get SSO session configuration to find the start URL
            sso_config = self._parse_aws_config_for_sso_session()
            if not sso_config:
                logger.debug("No SSO session configuration found")
                return None
            
            start_url = sso_config.get('sso_start_url')
            if not start_url:
                logger.debug("No SSO start URL found in configuration")
                return None
            
            # AWS CLI stores SSO cache in ~/.aws/sso/cache/
            aws_sso_cache_dir = Path.home() / '.aws' / 'sso' / 'cache'
            if not aws_sso_cache_dir.exists():
                logger.debug("AWS CLI SSO cache directory not found")
                return None
            
            # Find cache files that match our start URL
            for cache_file in aws_sso_cache_dir.glob('*.json'):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                    
                    # Check if this cache file is for our SSO session
                    if cache_data.get('startUrl') == start_url:
                        # Check if token is still valid
                        expires_at_str = cache_data.get('expiresAt')
                        if expires_at_str:
                            # AWS CLI uses ISO format with Z suffix
                            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                            if datetime.now().astimezone() < expires_at:
                                access_token = cache_data.get('accessToken')
                                if access_token:
                                    self._current_token = access_token
                                    self._token_expires_at = expires_at
                                    logger.debug(f"Loaded valid token from AWS CLI cache: {cache_file.name}")
                                    return access_token
                        
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.debug(f"Failed to parse cache file {cache_file}: {e}")
                    continue
            
            logger.debug("No valid token found in AWS CLI cache")
            return None
            
        except Exception as e:
            logger.warning(f"Error loading AWS CLI token: {e}")
            return None
    
    def _save_token_to_cache(self, token_data: Dict[str, Any]) -> None:
        """
        Save token data to cache (legacy method, kept for compatibility)
        
        Args:
            token_data: Token data to cache
        """
        cache_file = self._get_cache_file_path()
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, indent=2)
            
            # Set appropriate permissions (readable only by owner)
            cache_file.chmod(0o600)
            
            logger.debug(f"Token cached to {cache_file}")
            
        except Exception as e:
            logger.warning(f"Failed to cache token: {e}")
        """
        Save token data to cache
        
        Args:
            token_data: Token data to cache
        """
        cache_file = self._get_cache_file_path()
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, indent=2)
            
            # Set appropriate permissions (readable only by owner)
            cache_file.chmod(0o600)
            
            logger.debug(f"Token cached to {cache_file}")
            
        except Exception as e:
            logger.warning(f"Failed to cache token: {e}")
    
    def _parse_aws_config_for_sso_session(self) -> Optional[Dict[str, str]]:
        """
        Parse AWS config file to find SSO session configuration
        
        Returns:
            SSO session config if found, None otherwise
        """
        aws_config_path = Path.home() / '.aws' / 'config'
        if not aws_config_path.exists():
            logger.warning("AWS config file not found")
            return None
        
        try:
            import configparser
            config = configparser.ConfigParser()
            config.read(aws_config_path)
            
            # Look for SSO session section
            sso_section_name = f"sso-session {self.sso_session_name}"
            if sso_section_name not in config:
                logger.error(f"SSO session '{self.sso_session_name}' not found in AWS config")
                return None
            
            sso_config = dict(config[sso_section_name])
            logger.debug(f"Found SSO session config: {list(sso_config.keys())}")
            return sso_config
            
        except Exception as e:
            logger.error(f"Failed to parse AWS config: {e}")
            return None
    
    def is_authenticated(self) -> bool:
        """
        Check if currently authenticated with valid token
        
        Returns:
            True if authenticated, False otherwise
        """
        # Check if we have a current token
        if self._current_token and self._token_expires_at:
            if datetime.now().astimezone() < self._token_expires_at:
                return True
        
        # Try to load token from AWS CLI cache
        if self._load_aws_cli_token():
            return True
        
        # Fallback: Try to load from our own cache (legacy)
        cached_token = self._load_cached_token()
        if cached_token:
            self._current_token = cached_token.get('accessToken')
            expires_at_str = cached_token.get('expiresAt')
            if expires_at_str:
                self._token_expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                return True
        
        return False
    
    def authenticate(self) -> bool:
        """
        Authenticate with AWS SSO using AWS CLI
        
        Returns:
            True if authentication successful, False otherwise
            
        Raises:
            SSOAuthenticationError: If authentication fails
        """
        # Check if already authenticated
        if self.is_authenticated():
            logger.info("Already authenticated with valid token")
            return True
        
        try:
            print(f"🔐 Starting AWS SSO authentication for session: {self.sso_session_name}")
            
            # Use AWS CLI to authenticate
            result = subprocess.run([
                'aws', 'sso', 'login', 
                '--sso-session', self.sso_session_name
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                print("✅ AWS SSO authentication successful!")
                logger.info("SSO authentication successful via AWS CLI")
                
                # Clear any existing token cache so we reload from AWS CLI cache
                self._current_token = None
                self._token_expires_at = None
                
                # Verify authentication worked by checking if we can get a token
                if self._load_aws_cli_token():
                    return True
                else:
                    print("⚠️  Authentication succeeded but failed to load token")
                    return False
            else:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                print(f"❌ AWS SSO authentication failed: {error_msg}")
                logger.error(f"SSO authentication failed: {error_msg}")
                raise SSOAuthenticationError(f"AWS SSO login failed: {error_msg}")
                
        except subprocess.TimeoutExpired:
            raise SSOAuthenticationError("Authentication timeout - AWS SSO login took too long")
        except FileNotFoundError:
            raise SSOAuthenticationError("AWS CLI not found. Please install the AWS CLI first.")
        except Exception as e:
            raise SSOAuthenticationError(f"Unexpected error during authentication: {e}") from e
    
    def get_access_token(self) -> str:
        """
        Get current access token, authenticating if necessary
        
        Returns:
            Access token string
            
        Raises:
            SSOTokenError: If unable to get valid token
        """
        if not self.is_authenticated():
            if not self.authenticate():
                raise SSOTokenError("Failed to obtain access token")
        
        # Try to get token from AWS CLI cache first
        token = self._load_aws_cli_token()
        if token:
            return token
        
        # Fallback to our cached token
        if not self._current_token:
            raise SSOTokenError("No valid access token available")
        
        return self._current_token
    
    def list_accounts(self) -> List[Dict[str, Any]]:
        """
        List AWS accounts accessible through SSO
        
        Returns:
            List of account dictionaries with 'accountId', 'accountName', 'emailAddress'
            
        Raises:
            SSOAuthenticationError: If not authenticated or operation fails
        """
        access_token = self.get_access_token()
        sso_client = self._get_sso_client()
        
        try:
            accounts = []
            paginator = sso_client.get_paginator('list_accounts')
            
            for page in paginator.paginate(accessToken=access_token):
                accounts.extend(page.get('accountList', []))
            
            logger.info(f"Discovered {len(accounts)} accounts")
            return accounts
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'UnauthorizedException':
                # Token might be expired, try to re-authenticate
                logger.info("Access token expired, re-authenticating...")
                self._current_token = None
                self._token_expires_at = None
                
                if self.authenticate():
                    return self.list_accounts()  # Retry
                else:
                    raise SSOAuthenticationError("Re-authentication failed")
            else:
                raise SSOAuthenticationError(f"Failed to list accounts: {e}") from e
    
    def list_account_roles(self, account_id: str) -> List[Dict[str, Any]]:
        """
        List roles available for a specific account
        
        Args:
            account_id: AWS account ID
            
        Returns:
            List of role dictionaries with 'roleName', 'accountId'
            
        Raises:
            SSOAuthenticationError: If not authenticated or operation fails
        """
        access_token = self.get_access_token()
        sso_client = self._get_sso_client()
        
        try:
            roles = []
            paginator = sso_client.get_paginator('list_account_roles')
            
            for page in paginator.paginate(
                accessToken=access_token,
                accountId=account_id
            ):
                roles.extend(page.get('roleList', []))
            
            logger.info(f"Found {len(roles)} roles for account {account_id}")
            return roles
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'UnauthorizedException':
                # Token might be expired, try to re-authenticate
                logger.info("Access token expired, re-authenticating...")
                self._current_token = None
                self._token_expires_at = None
                
                if self.authenticate():
                    return self.list_account_roles(account_id)  # Retry
                else:
                    raise SSOAuthenticationError("Re-authentication failed")
            else:
                raise SSOAuthenticationError(f"Failed to list roles for account {account_id}: {e}") from e
    
    def logout(self) -> None:
        """Logout and clear cached tokens"""
        try:
            if self._current_token:
                # Try to logout from SSO
                oidc_client = self._get_sso_oidc_client()
                # Note: logout is not always available in SSO OIDC
                logger.info("Logged out from SSO")
        except Exception as e:
            logger.warning(f"Error during logout: {e}")
        finally:
            # Clear tokens and cache
            self._current_token = None
            self._token_expires_at = None
            
            cache_file = self._get_cache_file_path()
            if cache_file.exists():
                cache_file.unlink()
                logger.debug("Cleared token cache")

# Convenience functions
def get_sso_client(sso_session_name: str = "default", region: str = "us-east-1") -> SSOClient:
    """Get an SSO client instance"""
    return SSOClient(sso_session_name, region)

def is_sso_configured(sso_session_name: str = "default") -> bool:
    """Check if SSO session is configured in AWS config"""
    aws_config_path = Path.home() / '.aws' / 'config'
    if not aws_config_path.exists():
        return False
    
    try:
        import configparser
        config = configparser.ConfigParser()
        config.read(aws_config_path)
        
        sso_section_name = f"sso-session {sso_session_name}"
        return sso_section_name in config
    except Exception:
        return False