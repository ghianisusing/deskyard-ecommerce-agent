import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ChatLog
from .views import parse_agent_reply


class ParseAgentReplyTests(TestCase):
    def test_plain_reply_has_no_escalation(self):
        text, escalate = parse_agent_reply("Standard shipping takes 3-5 business days.")
        self.assertEqual(text, "Standard shipping takes 3-5 business days.")
        self.assertFalse(escalate)

    def test_escalation_tag_is_detected_and_stripped(self):
        raw = "I'm sorry to hear that — let me get a human involved.\n[ESCALATE]"
        text, escalate = parse_agent_reply(raw)
        self.assertTrue(escalate)
        self.assertNotIn("[ESCALATE]", text)
        self.assertEqual(text, "I'm sorry to hear that — let me get a human involved.")

    def test_escalation_tag_anywhere_in_text_is_stripped(self):
        raw = "Sorry about that. [ESCALATE] I'll flag this for a teammate."
        text, escalate = parse_agent_reply(raw)
        self.assertTrue(escalate)
        self.assertNotIn("[ESCALATE]", text)

    def test_empty_reply(self):
        text, escalate = parse_agent_reply("")
        self.assertEqual(text, "")
        self.assertFalse(escalate)

    def test_none_reply_does_not_crash(self):
        text, escalate = parse_agent_reply(None)
        self.assertEqual(text, "")
        self.assertFalse(escalate)


def _mock_openai_response(content: str):
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


@override_settings(OPENAI_API_KEY="test-key", CHAT_RATE_LIMIT_MAX=3, CHAT_RATE_LIMIT_WINDOW=60)
class ChatApiRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("agent.views.OpenAI")
    def test_requests_within_limit_succeed(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response("Hi there!")
        mock_openai_cls.return_value = mock_client

        for _ in range(3):
            response = self.client.post(
                reverse("chat_api"),
                data=json.dumps({"message": "hello", "history": []}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)

    @patch("agent.views.OpenAI")
    def test_request_over_limit_is_rejected(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response("Hi there!")
        mock_openai_cls.return_value = mock_client

        for _ in range(3):
            self.client.post(
                reverse("chat_api"),
                data=json.dumps({"message": "hello", "history": []}),
                content_type="application/json",
            )

        response = self.client.post(
            reverse("chat_api"),
            data=json.dumps({"message": "one too many", "history": []}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn("error", response.json())

    @patch("agent.views.OpenAI")
    def test_escalation_flag_is_returned_to_client(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "I understand your frustration.\n[ESCALATE]"
        )
        mock_openai_cls.return_value = mock_client

        response = self.client.post(
            reverse("chat_api"),
            data=json.dumps({"message": "I want a refund now", "history": []}),
            content_type="application/json",
        )
        data = response.json()
        self.assertTrue(data["escalate"])
        self.assertNotIn("[ESCALATE]", data["reply"])


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SUPPORT_NOTIFICATION_EMAIL="support@example.com",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    SLACK_ESCALATION_WEBHOOK_URL="",
)
class EscalationEmailNotificationTests(TestCase):
    """Proves the signal in agent/signals.py actually sends mail — not just
    that ChatLog.escalated gets set to True."""

    def test_creating_an_escalated_chatlog_sends_email(self):
        ChatLog.objects.create(
            message="I want a refund now", reply="I'm sorry, let me get a human.", escalated=True
        )
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["support@example.com"])
        self.assertIn("escalated", sent.subject.lower())
        self.assertIn("I want a refund now", sent.body)

    def test_non_escalated_chatlog_sends_no_email(self):
        ChatLog.objects.create(message="What are your hours?", reply="9-5 Mon-Fri", escalated=False)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(SUPPORT_NOTIFICATION_EMAIL="")
    def test_unconfigured_recipient_is_a_silent_no_op(self):
        ChatLog.objects.create(message="ugh", reply="sorry", escalated=True)
        self.assertEqual(len(mail.outbox), 0)

    def test_escalated_chatlog_includes_the_requesting_user(self):
        user = User.objects.create_user(username="alice", password="testpass123")
        ChatLog.objects.create(user=user, message="help", reply="on it", escalated=True)
        self.assertIn("alice", mail.outbox[0].body)

    @patch("agent.signals.send_mail", side_effect=RuntimeError("SMTP is down"))
    def test_a_broken_mail_server_does_not_raise(self, mock_send_mail):
        # Must not raise — a notification failure can never break the
        # request/response cycle that already returned a reply to the user.
        # assertLogs both captures the expected error log (instead of it
        # printing a raw traceback to the test console) and proves the
        # failure really was logged, not just silently swallowed.
        with self.assertLogs("agent.signals", level="ERROR"):
            try:
                ChatLog.objects.create(message="help", reply="on it", escalated=True)
            except RuntimeError:
                self.fail("email failure in the signal handler must not propagate")


@override_settings(
    SUPPORT_NOTIFICATION_EMAIL="",
    SLACK_ESCALATION_WEBHOOK_URL="https://hooks.slack.com/services/fake/webhook",
)
class EscalationSlackNotificationTests(TestCase):
    @patch("agent.signals.httpx.post")
    def test_creating_an_escalated_chatlog_posts_to_slack(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        ChatLog.objects.create(message="this is broken!!", reply="sorry about that", escalated=True)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://hooks.slack.com/services/fake/webhook")
        self.assertIn("this is broken!!", kwargs["json"]["text"])

    @patch("agent.signals.httpx.post")
    def test_non_escalated_chatlog_does_not_post_to_slack(self, mock_post):
        ChatLog.objects.create(message="hi", reply="hello!", escalated=False)
        mock_post.assert_not_called()

    @override_settings(SLACK_ESCALATION_WEBHOOK_URL="")
    @patch("agent.signals.httpx.post")
    def test_unconfigured_webhook_is_a_silent_no_op(self, mock_post):
        ChatLog.objects.create(message="ugh", reply="sorry", escalated=True)
        mock_post.assert_not_called()

    @patch("agent.signals.httpx.post", side_effect=RuntimeError("webhook unreachable"))
    def test_a_broken_webhook_does_not_raise(self, mock_post):
        with self.assertLogs("agent.signals", level="ERROR"):
            try:
                ChatLog.objects.create(message="help", reply="on it", escalated=True)
            except RuntimeError:
                self.fail("Slack failure in the signal handler must not propagate")
