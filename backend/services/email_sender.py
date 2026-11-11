from __future__ import annotations

import json
import logging
import os
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol
from urllib.request import Request, urlopen


log = logging.getLogger(__name__)


class EmailSender(Protocol):
    def send_verification_email(self, *, email: str, code: str, expires_minutes: int) -> None: ...


@dataclass
class RecordingEmailSender:
    deliveries: list[dict[str, str]] = field(default_factory=list)

    def send_verification_email(self, *, email: str, code: str, expires_minutes: int) -> None:
        self.deliveries.append({"email": email, "code": code, "expires_minutes": str(expires_minutes)})
        # 로컬(PROVENA_ENV=local)에서만 서버 로그에 인증번호를 남긴다. 실제 메일이 가지 않으니 이 줄이 유일한 확인 수단이다(K-21).
        # 기록용 발송기는 로컬에서만 만들어지지만(configured_email_sender), 배포 설정으로 잘못 쓰여도 인증번호가 로그에 나가지 않게 여기서도 막는다.
        if os.getenv("PROVENA_ENV", "").strip().lower() == "local":
            log.warning("[로컬 전용] 가입 인증번호 %s (받는 주소 %s, %d분 유효). 실제 메일은 보내지 않았다", code, email, expires_minutes)


class EmailDeliveryUnavailable(RuntimeError):
    """메일 공급자가 설정되지 않아 보낼 수 없다(발송 실패와 같은 RuntimeError 계열)."""


class UnavailableEmailSender:
    """EMAIL_PROVIDER 미설정(로컬이 아닌 환경): 서버는 켜 두고 발송만 거절한다."""

    def send_verification_email(self, *, email: str, code: str, expires_minutes: int) -> None:
        raise EmailDeliveryUnavailable("email provider is not configured")


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
        try:
            with urlopen(request, timeout=10):  # nosec B310: fixed HTTPS provider URL
                return
        except Exception:
            raise RuntimeError("email delivery failed") from None


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
        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(self.username, self.app_password)
                smtp.send_message(message)
        except Exception:
            raise RuntimeError("email delivery failed") from None


def configured_email_sender() -> EmailSender:
    provider = os.getenv("EMAIL_PROVIDER", "").strip().lower()
    environment = os.getenv("PROVENA_ENV", "").strip().lower()
    local = environment == "local"
    if not provider:
        if local:
            return RecordingEmailSender()
        # 운영에서 EMAIL_PROVIDER 를 아직 설정하지 않았어도 서버는 떠야 한다(로그인·채팅과 무관하다).
        # 대신 가입 메일을 보내는 경로만 막는다: 발송 시도마다 EmailDeliveryUnavailable 이 나고
        # 가입·재발송 라우트가 503 으로 답한다. 기록용 발송기로 내려가 성공처럼 보이는 일은 없다.
        log.error("EMAIL_PROVIDER is not set; email signup verification is disabled until it is configured")
        return UnavailableEmailSender()
    if provider == "gmail":
        username = os.getenv("GMAIL_SMTP_USER", "").strip()
        app_password = os.getenv("GMAIL_APP_PASSWORD", "")
        sender = os.getenv("EMAIL_FROM", "").strip() or username
        if not username or not app_password or not sender:
            if local:
                log.warning("Gmail email provider is selected but required settings are missing; using recording sender")
                return RecordingEmailSender()
            raise RuntimeError("Gmail email provider is configured but required settings are missing")
        return GmailSMTPEmailSender(username, app_password, sender=sender)
    if provider == "resend":
        api_key = os.getenv("RESEND_API_KEY", "")
        sender = os.getenv("EMAIL_FROM", "")
        if not api_key or not sender:
            if local:
                log.warning("Resend email provider is selected but required settings are missing; using recording sender")
                return RecordingEmailSender()
            raise RuntimeError("Resend email provider is configured but required settings are missing")
        return ResendEmailSender(api_key, sender)
    if local:
        log.warning("Unsupported email provider configured; using recording sender")
        return RecordingEmailSender()
    raise RuntimeError("Unsupported EMAIL_PROVIDER configuration")
