"""Turns `ChatLog(escalated=True)` from a database row nobody's watching
into an actual notification to a human.

Design choices:
- Django signals run synchronously inside the request that saved the row,
  so the handler itself does almost nothing: it builds the notification
  text, then hands delivery to a background thread once the transaction
  commits. The customer's reply is never delayed by a slow mail server or
  Slack webhook. A task queue (Celery, RQ, etc.) is the sturdier option once
  the project has one; a thread is enough until then, but a notification
  in flight is lost if the process exits.
- The thread gets plain strings only, never model instances, so it never
  touches the database (and never leaks a DB connection).
- Both notification paths are individually try/excepted and have timeouts.
  A misconfigured SMTP server must never prevent a Slack ping from going
  out.
- Both are no-ops if unconfigured (no SUPPORT_NOTIFICATION_EMAIL /
  SLACK_ESCALATION_WEBHOOK_URL), so this is safe to ship without forcing
  every deployment to wire up email or Slack immediately.
"""

import logging
import threading
from typing import Callable

import httpx
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ChatLog

logger = logging.getLogger(__name__)

SLACK_TIMEOUT_SECONDS = 5.0


@receiver(post_save, sender=ChatLog)
def notify_on_escalation(sender, instance: ChatLog, created: bool, **kwargs) -> None:
    # ChatLog rows are write-once (created in _log_chat and never updated
    # afterward), but guard on `created` anyway so this can never double-fire
    # if that ever changes.
    if not created or not instance.escalated:
        return

    email_job = _build_email_job(instance)
    slack_job = _build_slack_job(instance)
    if not email_job and not slack_job:
        return

    def deliver() -> None:
        if email_job:
            email_job()
        if slack_job:
            slack_job()

    # on_commit: don't notify about a row that might still be rolled back.
    transaction.on_commit(lambda: _run_in_background(deliver))


def _run_in_background(fn: Callable[[], None]) -> None:
    """Separate function so tests can swap in a synchronous runner."""
    threading.Thread(target=fn, name="escalation-notify", daemon=True).start()


def _who(chat_log: ChatLog) -> str:
    return chat_log.user.get_username() if chat_log.user else "a guest"


def _build_email_job(chat_log: ChatLog) -> Callable[[], None] | None:
    recipient = settings.SUPPORT_NOTIFICATION_EMAIL
    if not recipient:
        return None

    pk = chat_log.pk
    subject = f"[Deskyard] Chat escalated — {_who(chat_log)}"
    body = (
        f"A customer chat was flagged for human follow-up.\n\n"
        f"Customer: {_who(chat_log)}\n"
        f"Message: {chat_log.message}\n\n"
        f"Agent reply: {chat_log.reply}\n\n"
        f"View in admin: /admin/agent/chatlog/{pk}/change/"
    )

    def job() -> None:
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception:  # noqa: BLE001 - a broken mail server must never break the chat
            logger.exception("Failed to send escalation email for ChatLog #%s", pk)

    return job


def _build_slack_job(chat_log: ChatLog) -> Callable[[], None] | None:
    webhook_url = settings.SLACK_ESCALATION_WEBHOOK_URL
    if not webhook_url:
        return None

    pk = chat_log.pk
    text = (
        f":bell: *Chat escalated* — {_who(chat_log)}\n"
        f"> {chat_log.message}\n"
        f"Agent replied: {chat_log.reply}"
    )

    def job() -> None:
        try:
            response = httpx.post(webhook_url, json={"text": text}, timeout=SLACK_TIMEOUT_SECONDS)
            response.raise_for_status()
        except Exception:  # noqa: BLE001 - a broken webhook must never break the chat
            logger.exception("Failed to send Slack escalation notice for ChatLog #%s", pk)

    return job
