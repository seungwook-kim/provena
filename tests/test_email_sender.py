import smtplib

import pytest

from backend.services.email_sender import GmailSMTPEmailSender, RecordingEmailSender, configured_email_sender


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout):
        self.args = (host, port, timeout)
        self.calls = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def ehlo(self):
        self.calls.append(("ehlo",))

    def starttls(self):
        self.calls.append(("starttls",))

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message):
        self.calls.append(("send_message", message))


def test_gmail_sender_uses_starttls_and_does_not_store_sender_secrets(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    sender = GmailSMTPEmailSender("sender@gmail.com", "app-password", sender="sender@gmail.com")
    sender.send_verification_email(email="recipient@example.com", code="123456", expires_minutes=10)
    smtp = FakeSMTP.instances[0]
    assert smtp.args == ("smtp.gmail.com", 587, 10)
    assert [call[0] for call in smtp.calls] == ["ehlo", "starttls", "ehlo", "login", "send_message"]
    message = smtp.calls[-1][1]
    assert message["To"] == "recipient@example.com"
    assert "123456" in message.get_content()
    assert sender.app_password == "app-password"


def test_gmail_send_failure_is_propagated(monkeypatch):
    class FailingSMTP(FakeSMTP):
        def send_message(self, _message):
            raise smtplib.SMTPException("simulated failure")

    monkeypatch.setattr(smtplib, "SMTP", FailingSMTP)
    with pytest.raises(smtplib.SMTPException):
        GmailSMTPEmailSender("sender@gmail.com", "app-password").send_verification_email(
            email="recipient@example.com", code="123456", expires_minutes=10
        )


def test_configured_gmail_sender_reads_environment_only(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.setenv("GMAIL_SMTP_USER", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    sender = configured_email_sender()
    assert isinstance(sender, GmailSMTPEmailSender)
    assert sender.username == "sender@gmail.com"
    assert sender.sender == "sender@gmail.com"


def test_missing_gmail_config_keeps_recording_fallback(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.delenv("GMAIL_SMTP_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert isinstance(configured_email_sender(), RecordingEmailSender)
