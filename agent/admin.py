from django.contrib import admin

from .models import ChatLog, KnowledgeBaseEntry


@admin.register(KnowledgeBaseEntry)
class KnowledgeBaseEntryAdmin(admin.ModelAdmin):
    list_display = ("topic", "created_at")
    search_fields = ("topic", "content")


@admin.register(ChatLog)
class ChatLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "escalated", "has_error")
    list_filter = ("escalated",)
    search_fields = ("message", "reply", "error")
    readonly_fields = ("timestamp", "user", "message", "reply", "escalated", "error")

    def has_error(self, obj):
        return bool(obj.error)

    has_error.boolean = True

    def has_add_permission(self, request):
        return False
