from django.apps import AppConfig


class AgentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agent"

    def ready(self):
        # Import triggers the @receiver registration in signals.py. Must
        # happen in ready(), not at module import time, so Django's app
        # registry is fully loaded before we touch models.
        from . import signals  # noqa: F401
