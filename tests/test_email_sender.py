import logging
import smtplib
from urllib.error import URLError

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


@pytest.mark.parametrize("failure_step", ["connect", "login"])
def test_gmail_send_failures_do_not_expose_secrets(monkeypatch, failure_step, caplog):
    class FailingSMTP(FakeSMTP):
        def __init__(self, *args, **kwargs):
            if failure_step == "connect":
                raise smtplib.SMTPException("connection failed password=FAKE_APP_PASSWORD")
            super().__init__(*args, **kwargs)

        def login(self, username, password):
            if failure_step == "login":
                raise smtplib.SMTPAuthenticationError(535, b"invalid FAKE_APP_PASSWORD")
            super().login(username, password)

        def send_message(self, _message):
            raise smtplib.SMTPException("simulated failure FAKE_APP_PASSWORD")

    monkeypatch.setattr(smtplib, "SMTP", FailingSMTP)
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError, match="email delivery failed") as exc_info:
        GmailSMTPEmailSender("sender@gmail.com", "FAKE_APP_PASSWORD").send_verification_email(
            email="recipient@example.com", code="FAKE_CODE", expires_minutes=10
        )
    assert "FAKE_APP_PASSWORD" not in str(exc_info.value)
    assert "FAKE_CODE" not in caplog.text
    assert "FAKE_APP_PASSWORD" not in caplog.text


def test_resend_failure_does_not_expose_api_key_or_code(monkeypatch, caplog):
    def fail(*_args, **_kwargs):
        raise URLError("provider rejected FAKE_RESEND_API_KEY")

    monkeypatch.setattr("backend.services.email_sender.urlopen", fail)
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError, match="email delivery failed") as exc_info:
        from backend.services.email_sender import ResendEmailSender

        ResendEmailSender("FAKE_RESEND_API_KEY", "sender@example.com").send_verification_email(
            email="recipient@example.com", code="FAKE_CODE", expires_minutes=10
        )
    assert "FAKE_RESEND_API_KEY" not in str(exc_info.value)
    assert "FAKE_CODE" not in caplog.text
    assert "FAKE_RESEND_API_KEY" not in caplog.text


def test_configured_gmail_sender_reads_environment_only(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.setenv("GMAIL_SMTP_USER", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    sender = configured_email_sender()
    assert isinstance(sender, GmailSMTPEmailSender)
    assert sender.username == "sender@gmail.com"
    assert sender.sender == "sender@gmail.com"


def test_missing_gmail_config_uses_recording_with_local_warning(monkeypatch, caplog):
    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.delenv("GMAIL_SMTP_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    with caplog.at_level("WARNING"):
        sender = configured_email_sender()
    assert isinstance(sender, RecordingEmailSender)
    assert "required settings are missing" in caplog.text


def test_missing_gmail_config_fails_closed_outside_local(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.setenv("PROVENA_ENV", "production")
    monkeypatch.delenv("GMAIL_SMTP_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="required settings are missing"):
        configured_email_sender()


def test_missing_email_provider_fails_closed_in_production(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "production")
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    with pytest.raises(RuntimeError, match="EMAIL_PROVIDER is required"):
        configured_email_sender()


def test_missing_email_provider_keeps_recording_sender_for_local_and_tests(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    monkeypatch.delenv("PROVENA_ENV", raising=False)
    assert isinstance(configured_email_sender(), RecordingEmailSender)

    monkeypatch.setenv("PROVENA_ENV", "local")
    assert isinstance(configured_email_sender(), RecordingEmailSender)


def test_unsupported_email_provider_warns_and_records_locally(monkeypatch, caplog):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp-typo")
    monkeypatch.setenv("PROVENA_ENV", "local")
    with caplog.at_level("WARNING"):
        sender = configured_email_sender()
    assert isinstance(sender, RecordingEmailSender)
    assert "Unsupported email provider configured" in caplog.text


def test_unsupported_email_provider_fails_closed_outside_local(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp-typo")
    monkeypatch.setenv("PROVENA_ENV", "production")
    with pytest.raises(RuntimeError, match="Unsupported EMAIL_PROVIDER configuration"):
        configured_email_sender()
