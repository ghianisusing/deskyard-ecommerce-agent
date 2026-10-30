from django.contrib import admin
from django.db.models import Avg, Count, Sum

from .models import ChatLog, KnowledgeBaseEntry


@admin.register(KnowledgeBaseEntry)
class KnowledgeBaseEntryAdmin(admin.ModelAdmin):
    list_display = ("topic", "created_at")
    search_fields = ("topic", "content")


@admin.register(ChatLog)
class ChatLogAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp",
        "user",
        "escalated",
        "has_error",
        "total_tokens",
        "latency_ms",
        "cost",
        "tools_used",
    )
    list_filter = ("escalated", "model")
    date_hierarchy = "timestamp"
    search_fields = ("message", "reply", "error")
    readonly_fields = (
        "timestamp",
        "user",
        "message",
        "reply",
        "escalated",
        "error",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "estimated_cost_usd",
        "tool_calls",
    )

    @admin.display(boolean=True)
    def has_error(self, obj):
        return bool(obj.error)

    @admin.display(description="Est. cost (USD)", ordering="estimated_cost_usd")
    def cost(self, obj):
        if obj.estimated_cost_usd is None:
            return "-"
        return f"${obj.estimated_cost_usd:.6f}"

    @admin.display(description="Tools")
    def tools_used(self, obj):
        return ", ".join(call.get("name", "?") for call in obj.tool_calls or []) or "-"

    def has_add_permission(self, request):
        return False

    def changelist_view(self, request, extra_context=None):
        """Add totals for the chats matching the current filters and search,
        shown above the list by admin/agent/chatlog/change_list.html."""
        response = super().changelist_view(request, extra_context)
        context = getattr(response, "context_data", None)
        if context and "cl" in context:
            context["usage_summary"] = context["cl"].queryset.aggregate(
                chats=Count("id"),
                tokens=Sum("total_tokens"),
                cost=Sum("estimated_cost_usd"),
                avg_latency_ms=Avg("latency_ms"),
            )
        return response
