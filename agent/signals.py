"""Turns `ChatLog(escalated=True)` from a database row nobody's watching
into an actual notification to a human.

Design choices:
- Hooked on `post_save` for `ChatLog`, not called inline from `chat_api()`,
  so escalation delivery stays decoupled from the request/response cycle —
  the customer's reply is never delayed or blocked by a slow mail server.
- Both notification paths are individually try/excepted. A misconfigured
  SMTP server must never prevent a Slack ping from going out, and neither
  must ever bubble up and break the view that created the ChatLog row.
- Both are no-ops if unconfigured (no SUPPORT_NOTIFICATION_EMAIL /
  SLACK_ESCALATION_WEBHOOK_URL), so this is safe to ship without forcing
  every deployment to wire up email or Slack immediately.
"""

import logging

import httpx
from django.conf import settings
from django.core.mail import send_mail
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

    _notify_email(instance)
    _notify_slack(instance)


def _who(chat_log: ChatLog) -> str:
    return chat_log.user.get_username() if chat_log.user else "a guest"


def _notify_email(chat_log: ChatLog) -> None:
    recipient = settings.SUPPORT_NOTIFICATION_EMAIL
    if not recipient:
        return
    try:
        send_mail(
            subject=f"[Deskyard] Chat escalated — {_who(chat_log)}",
            message=(
                f"A customer chat was flagged for human follow-up.\n\n"
                f"Customer: {_who(chat_log)}\n"
                f"Message: {chat_log.message}\n\n"
                f"Agent reply: {chat_log.reply}\n\n"
                f"View in admin: /admin/agent/chatlog/{chat_log.pk}/change/"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001 - a broken mail server must never break the chat
        logger.exception("Failed to send escalation email for ChatLog #%s", chat_log.pk)


def _notify_slack(chat_log: ChatLog) -> None:
    webhook_url = settings.SLACK_ESCALATION_WEBHOOK_URL
    if not webhook_url:
        return
    text = (
        f":bell: *Chat escalated* — {_who(chat_log)}\n"
        f"> {chat_log.message}\n"
        f"Agent replied: {chat_log.reply}"
    )
    try:
        response = httpx.post(webhook_url, json={"text": text}, timeout=5.0)
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - a broken webhook must never break the chat
        logger.exception("Failed to send Slack escalation notice for ChatLog #%s", chat_log.pk)
