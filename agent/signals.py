"""Turns `ChatLog(escalated=True)` from a database row nobody's watching
into an email to a human.

Design choices:
- Django signals run synchronously inside the request that saved the row,
  so the handler itself does almost nothing: it builds the email, then
  hands delivery to a background thread once the transaction commits. The
  customer's reply is never delayed by a slow mail server. A task queue
  (Celery, RQ, etc.) is the sturdier option once the project has one; a
  thread is enough until then, but an email in flight is lost if the
  process exits.
- The thread gets plain strings only, never model instances, so it never
  touches the database (and never leaks a DB connection).
- Sending is try/excepted and has a timeout (EMAIL_TIMEOUT), so a
  misconfigured SMTP server never breaks the chat.
- It's a no-op if SUPPORT_NOTIFICATION_EMAIL is unset, so this is safe to
  ship without forcing every deployment to wire up email immediately.
"""

import logging
import threading
from collections.abc import Callable

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ChatLog

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ChatLog)
def notify_on_escalation(sender, instance: ChatLog, created: bool, **kwargs) -> None:
    # ChatLog rows are write-once (created in _log_chat and never updated
    # afterward), but guard on `created` anyway so this can never double-fire
    # if that ever changes.
    if not created or not instance.escalated:
        return

    email_job = _build_email_job(instance)
    if not email_job:
        return

    # on_commit: don't notify about a row that might still be rolled back.
    transaction.on_commit(lambda: _run_in_background(email_job))


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
