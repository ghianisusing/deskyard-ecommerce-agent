import json
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

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
