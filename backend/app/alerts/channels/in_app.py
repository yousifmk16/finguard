"""
ALT-04: In-app alert channel.

For in-app alerts the delivery mechanism *is* the database write performed by
the orchestrator — this channel's ``send()`` is therefore a no-op.  The
orchestrator persists an ``AlertRow(channel="in_app", status="sent")`` after
a successful ``send()``, making the alert immediately visible via API-04.
"""

from __future__ import annotations

import logging

from services.detection.anomaly_emitter import AnomalyEvent

logger = logging.getLogger(__name__)


class InAppChannel:
    """ALT-04: In-app delivery channel."""

    name = "in_app"

    def send(self, event: AnomalyEvent) -> None:
        """
        No-op: the alert is delivered by the orchestrator writing to the DB.

        Logging here gives an audit trail even if the DB write fails.
        """
        logger.info(
            "ALT-04: in-app alert queued",
            extra={
                "anomaly_id": event.anomaly_id,
                "account_id": event.account_id,
                "service": event.service,
                "severity": event.severity,
            },
        )
