import logging
import os
import tempfile

from django.conf import settings
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from .base import StorageNotConfigured

logger = logging.getLogger(__name__)

# drive.file only grants access to files and folders this app creates (or the user
# explicitly opens with it). The rest of the user's Drive stays inaccessible.
SCOPES = ['https://www.googleapis.com/auth/drive.file']

CONNECT_HINT = "Open /google-drive/ and click 'Connect Google Drive'."


def _client_secrets_file():
    path = settings.GOOGLE_OAUTH_CLIENT_SECRETS_FILE
    if not path:
        raise StorageNotConfigured("GOOGLE_OAUTH_CLIENT_SECRETS_FILE is not set in .env.")
    if not os.path.isfile(path):
        raise StorageNotConfigured(f"Google OAuth client secrets file not found at {path}.")
    return path


def _token_file():
    path = settings.GOOGLE_DRIVE_TOKEN_FILE
    if not path:
        raise StorageNotConfigured("GOOGLE_DRIVE_TOKEN_FILE is not set in .env.")
    return path


def _build_flow(state=None, code_verifier=None):
    kwargs = {'redirect_uri': settings.GOOGLE_OAUTH_REDIRECT_URI}
    if state is not None:
        kwargs['state'] = state
    if code_verifier is not None:
        kwargs['code_verifier'] = code_verifier
        kwargs['autogenerate_code_verifier'] = False
    return Flow.from_client_secrets_file(_client_secrets_file(), scopes=SCOPES, **kwargs)


def build_authorization_url():
    """
    Starts the OAuth web-server flow.

    Returns:
        tuple: (authorization_url, state, code_verifier). The caller must keep state and
        code_verifier (e.g. in the session) and pass them to exchange_code().
    """
    flow = _build_flow()
    # offline + consent so Google returns a refresh token the app can reuse.
    url, state = flow.authorization_url(access_type='offline', prompt='consent')
    return url, state, flow.code_verifier


def exchange_code(authorization_response, state, code_verifier):
    """
    Completes the OAuth flow and stores the resulting credentials in the token file.

    Args:
        authorization_response (str): The full callback URL Google redirected to.
        state (str): The state returned by build_authorization_url().
        code_verifier (str): The PKCE verifier returned by build_authorization_url().
    """
    flow = _build_flow(state=state, code_verifier=code_verifier)
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    if not credentials.refresh_token:
        logger.warning("Google did not return a refresh token; the connection will expire with the access token.")
    save_credentials(credentials)
    logger.info("Google Drive authorized; credentials saved to the configured token file.")


def save_credentials(credentials):
    """
    Writes credentials to GOOGLE_DRIVE_TOKEN_FILE atomically. Token values are never logged.
    """
    path = _token_file()
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix='.token-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(credentials.to_json())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def load_credentials():
    """
    Loads stored credentials, refreshing the access token if it has expired.

    Returns:
        google.oauth2.credentials.Credentials: Valid credentials for the Drive API.

    Raises:
        StorageNotConfigured: If Drive has not been connected or the connection was revoked.
    """
    path = _token_file()
    if not os.path.isfile(path):
        raise StorageNotConfigured(f"Google Drive is not connected yet. {CONNECT_HINT}")
    try:
        credentials = Credentials.from_authorized_user_file(path, SCOPES)
    except (ValueError, OSError) as e:
        raise StorageNotConfigured(f"Stored Google Drive token is unreadable ({type(e).__name__}). {CONNECT_HINT}")

    if credentials.valid:
        return credentials
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError:
            raise StorageNotConfigured(f"Google Drive authorization has expired or was revoked. {CONNECT_HINT}")
        except GoogleAuthError as e:
            raise StorageNotConfigured(f"Could not refresh Google Drive authorization ({type(e).__name__}). {CONNECT_HINT}")
        save_credentials(credentials)
        return credentials
    raise StorageNotConfigured(f"Stored Google Drive token cannot be refreshed. {CONNECT_HINT}")


def is_connected():
    """
    Returns True if a token file exists. Does not contact Google.
    """
    path = settings.GOOGLE_DRIVE_TOKEN_FILE
    return bool(path) and os.path.isfile(path)


def disconnect():
    """
    Deletes the local token file. Access can also be revoked at https://myaccount.google.com/permissions.
    """
    path = _token_file()
    if os.path.isfile(path):
        os.remove(path)
        logger.info("Google Drive token file removed.")
