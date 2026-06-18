import os
from urllib.parse import quote, urlencode

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from src.email.mime_builder import build_gmail_raw_message
from src.models.complaint import ProcessedComplaint

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
REDIRECT_PATH = "/"


def oauth_configured() -> bool:
    return bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"))


def _client_config() -> dict:
    return {
        "web": {
            "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
            "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8501")],
        }
    }


def get_auth_url() -> str:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8501"),
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url


def exchange_code(code: str) -> Credentials:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8501"),
    )
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_from_session(token_data: dict) -> Credentials:
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes"),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def credentials_to_session(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }


def create_gmail_draft(
    creds: Credentials,
    processed: ProcessedComplaint,
    cc_emails: list[str] | None = None,
    from_email: str = "",
) -> dict:
    """Create a Gmail draft with body + attachments. User opens Drafts in Gmail."""
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    raw = build_gmail_raw_message(processed, cc_emails, from_email)
    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )
    return {
        "draft_id": draft.get("id"),
        "message_id": draft.get("message", {}).get("id"),
        "drafts_url": "https://mail.google.com/mail/u/0/#drafts",
    }
