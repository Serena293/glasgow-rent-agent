from __future__ import annotations

import base64
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


GMAIL_SEND_SCOPE = ["https://www.googleapis.com/auth/gmail.send"]


class GmailMailer:
    def __init__(self, email_config: dict):
        self.recipient = email_config["recipient"]
        self.sender_name = email_config.get("sender_name", "House Agent")
        self.credentials_file = Path(email_config.get("credentials_file", "credentials.json"))
        self.token_file = Path(email_config.get("token_file", ".secrets/gmail_token.json"))
        self.token_json_env = email_config.get("token_json_env", "GOOGLE_TOKEN_JSON")

    def send(self, *, subject: str, html: str, text: str) -> dict:
        service = self._gmail_service()
        message = MIMEMultipart("alternative")
        message["To"] = self.recipient
        message["Subject"] = subject
        message.attach(MIMEText(text, "plain", "utf-8"))
        message.attach(MIMEText(html, "html", "utf-8"))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        return (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )

    def _gmail_service(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google Gmail dependencies are missing. Run: python -m pip install -e ."
            ) from exc

        creds = None
        loaded_from_env = False
        token_json = os.getenv(self.token_json_env)
        if token_json:
            creds = Credentials.from_authorized_user_info(json.loads(token_json), GMAIL_SEND_SCOPE)
            loaded_from_env = True
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), GMAIL_SEND_SCOPE)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_file.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials file not found: {self.credentials_file}. "
                        "Download it from Google Cloud as credentials.json."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), GMAIL_SEND_SCOPE)
                creds = flow.run_local_server(port=0)
            if not loaded_from_env:
                self.token_file.parent.mkdir(parents=True, exist_ok=True)
                self.token_file.write_text(creds.to_json(), encoding="utf-8")
        return build("gmail", "v1", credentials=creds)


def make_mailer(config: dict) -> GmailMailer:
    provider = config.get("provider", "gmail_api")
    if provider != "gmail_api":
        raise ValueError(f"Unsupported email provider: {provider}")
    return GmailMailer(config)
