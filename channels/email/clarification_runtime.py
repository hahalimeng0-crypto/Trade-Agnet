"""Runtime assembly for automatic missing-RFQ-field replies."""

from __future__ import annotations

from agent.business.email_clarification import EmailClarificationRepository
from agent.business.email_secret_store import create_default_email_secret_store
from channels.email.delivery_worker import EmailDeliveryWorker
from channels.email.smtp_sender import SmtpSslSender


def create_default_clarification_delivery_worker(*, worker_id: str,
                                                  timeout_seconds: int = 20):
    repository = EmailClarificationRepository()
    sender = SmtpSslSender(
        create_default_email_secret_store(), timeout_seconds=timeout_seconds,
    )
    return EmailDeliveryWorker(repository, sender, worker_id=worker_id)

