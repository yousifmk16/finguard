"""
ALT-05: Email alert channel.

Sends a plain-text email notification via SMTP.  When SMTP is not configured
(``SMTP_HOST`` env var absent) the channel operates in **stub mode**: the
message is logged at INFO level and treated as successfully delivered so the
service starts cleanly in development without an SMTP server.

Environment variables
---------------------
SMTP_HOST           SMTP server hostname (required for live mode)
SMTP_PORT           Port — default 587 (STARTTLS)
SMTP_USER           Username for authentication (optional)
SMTP_PASSWORD       Password for authentication (optional)
ALERT_FROM_ADDRESS  Sender address (default: alerts@finguard.io)
ALERT_RECIPIENTS    Comma-separated recipient list (default: empty → no send)
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

from services.detection.anomaly_emitter import AnomalyEvent

logger = logging.getLogger(__name__)

_DEFAULT_FROM = "alerts@finguard.io"


class EmailChannel:
    """ALT-05: Email delivery channel."""

    name = "email"

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        from_address: str | None = None,
        recipients: list[str] | None = None,
    ) -> None:
        self._host = smtp_host or os.getenv("SMTP_HOST")
        self._port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self._user = smtp_user or os.getenv("SMTP_USER")
        self._password = smtp_password or os.getenv("SMTP_PASSWORD")
        self._from = from_address or os.getenv("ALERT_FROM_ADDRESS", _DEFAULT_FROM)
        raw_recipients = recipients or os.getenv("ALERT_RECIPIENTS", "")
        self._recipients: list[str] = (
            [r.strip() for r in raw_recipients.split(",") if r.strip()]
            if isinstance(raw_recipients, str)
            else raw_recipients
        )

    @classmethod
    def from_env(cls) -> "EmailChannel":
        return cls()

    # ------------------------------------------------------------------
    # Public API (called by orchestrator, wrapped by RetryPolicy)
    # ------------------------------------------------------------------

    def send(self, event: AnomalyEvent) -> None:
        """
        Deliver an email alert for ``event``.

        Raises ``smtplib.SMTPException`` (or ``OSError``) on failure so the
        orchestrator's ``RetryPolicy`` can retry before marking the alert as
        ``"failed"``.
        """
        if not self._host:
            self._stub_send(event)
            return
        if not self._recipients:
            logger.warning("ALT-05: ALERT_RECIPIENTS not configured — email not sent")
            return
        self._smtp_send(event)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _smtp_send(self, event: AnomalyEvent) -> None:
        msg = self._build_message(event)
        with smtplib.SMTP(self._host, self._port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            if self._user and self._password:
                server.login(self._user, self._password)
            server.send_message(msg)
        logger.info(
            "ALT-05: email sent",
            extra={
                "anomaly_id": event.anomaly_id,
                "recipients": self._recipients,
                "severity": event.severity,
            },
        )

    def _stub_send(self, event: AnomalyEvent) -> None:
        logger.info(
            "ALT-05 [stub]: email would be sent — SMTP_HOST not configured.\n%s",
            self._format_body(event),
        )

    def _build_message(self, event: AnomalyEvent) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = (
            f"[FinGuard] {event.severity.capitalize()} anomaly — "
            f"{event.service} / {event.region}"
        )
        msg["From"] = self._from
        msg["To"] = ", ".join(self._recipients)
        msg.set_content(self._format_body(event))
        return msg

    @staticmethod
    def _format_body(event: AnomalyEvent) -> str:
        return (
            f"A {event.severity} billing anomaly has been detected.\n\n"
            f"Account:  {event.account_id}\n"
            f"Service:  {event.service}\n"
            f"Region:   {event.region}\n"
            f"Window:   {event.bucket}\n"
            f"Score:    {event.anomaly_score:.2f}\n"
            f"Status:   {event.status}\n"
        )
