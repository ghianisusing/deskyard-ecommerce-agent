from .models import KnowledgeBaseEntry


def knowledge_base_topics() -> list[str]:
    """Topic names of the knowledge base entries in the database. The agent
    sees only these names in its prompt and reads the content it needs with
    the get_policies tool. Manage entries via /admin/ or the Django shell.
    """
    return list(KnowledgeBaseEntry.objects.values_list("topic", flat=True))
