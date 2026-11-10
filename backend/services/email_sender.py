from __future__ import annotations

import json
import os
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol
from urllib.request import Request, urlopen


class EmailSender(Protocol):
    def send_verification_email(self, *, email: str, code: str, expires_minutes: int) -> None: ...


@dataclass
class RecordingEmailSender:
    deliveries: list[dict[str, str]] = field(default_factory=list)

    def send_verification_email(self, *, email: str, code: str, expires_minutes: int) -> None:
        self.deliveries.append({"email": email, "code": code, "expires_minutes": str(expires_minutes)})


class ResendEmailSender:
    def __init__(self, api_key: str, sender: str) -> None:
        self.api_key = api_key
        self.sender = sender

    def send_verification_email(self, *, email: str, code: str, expires_minutes: int) -> None:
        body = json.dumps({
            "from": self.sender,
            "to": [email],
            "subject": "Provena 이메일 인증번호",
            "text": f"인증번호: {code}\n{expires_minutes}분 안에 입력해 주세요.",
        }).encode("utf-8")
        request = Request(
            "https://api.resend.com/emails",
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10):  # nosec B310: fixed HTTPS provider URL
            return


class GmailSMTPEmailSender:
    """Gmail submission over STARTTLS using a Gmail app password."""

    def __init__(self, username: str, app_password: str, *, sender: str | None = None,
                 subject: str = "Provena 이메일 인증번호", host: str = "smtp.gmail.com", port: int = 587) -> None:
        self.username = username
        self.app_password = app_password
        self.sender = sender or username
        self.subject = subject
        self.host = host
        self.port = port

    def send_verification_email(self, *, email: str, code: str, expires_minutes: int) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = email
        message["Subject"] = self.subject
        message.set_content(f"인증번호: {code}\n{expires_minutes}분 안에 입력해 주세요.")
        # Do not log the password, code, or provider response.
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(self.username, self.app_password)
            smtp.send_message(message)


def configured_email_sender() -> EmailSender:
    provider = os.getenv("EMAIL_PROVIDER", "recording").lower()
    if provider == "gmail":
        username = os.getenv("GMAIL_SMTP_USER", "").strip()
        app_password = os.getenv("GMAIL_APP_PASSWORD", "")
        sender = os.getenv("EMAIL_FROM", "").strip() or username
        if username and app_password and sender:
            return GmailSMTPEmailSender(username, app_password, sender=sender)
    if provider == "resend":
        api_key = os.getenv("RESEND_API_KEY", "")
        sender = os.getenv("EMAIL_FROM", "")
        if api_key and sender:
            return ResendEmailSender(api_key, sender)
    return RecordingEmailSender()
