from django.conf import settings
from django.db import models


class KnowledgeBaseEntry(models.Model):
    """One fact the agent is allowed to answer from."""

    topic = models.CharField(max_length=100)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["topic"]

    def __str__(self):
        return self.topic


class ChatLog(models.Model):
    """One record per /api/chat/ call — captures what was asked, what the
    agent replied, whether it escalated, and any error, so problems and
    escalations are visible after the fact instead of only in a terminal.
    """

    timestamp = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_logs",
    )
    message = models.TextField()
    reply = models.TextField(blank=True)
    escalated = models.BooleanField(default=False)
    error = models.TextField(blank=True)

    # What the OpenAI call cost and how long it took. Token counts are empty
    # when the call failed or the API didn't report usage. The cost is an
    # estimate at the prices configured when the call was made, stored so
    # later price changes don't rewrite history.
    model = models.CharField(max_length=100, blank=True)
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    estimated_cost_usd = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    # Tools the agent called to answer, in order: [{"name": ..., "arguments": ...}].
    tool_calls = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        who = self.user or "guest"
        return f"{who} @ {self.timestamp:%Y-%m-%d %H:%M}"
