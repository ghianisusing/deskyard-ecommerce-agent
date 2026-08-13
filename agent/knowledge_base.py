from .models import KnowledgeBaseEntry


def format_knowledge_base() -> str:
    """Render the knowledge base (from the database) as plain text for
    the system prompt. Manage entries via /admin/ or the Django shell —
    the agent always reads whatever is currently in the table.
    """
    entries = KnowledgeBaseEntry.objects.all()
    if not entries:
        return "No knowledge base entries yet."
    return "\n\n".join(f"[{entry.topic}]\n{entry.content}" for entry in entries)
