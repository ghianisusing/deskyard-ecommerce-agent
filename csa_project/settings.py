import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _get_dev_secret_key() -> str:
    """Local dev fallback so SECRET_KEY is never hardcoded in source.
    Generated once and cached to a gitignored file so restarting the
    server doesn't invalidate every existing session/cookie.
    """
    key_file = BASE_DIR / ".dev_secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    new_key = secrets.token_urlsafe(50)
    key_file.write_text(new_key)
    return new_key


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or _get_dev_secret_key()
DEBUG = True
ALLOWED_HOSTS = ["*"]

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Used by the browser voice call feature (agent/views.py:tts_api) for
# natural-sounding spoken replies. "nova" is a warm, friendly-sounding
# voice — see https://platform.openai.com/docs/guides/text-to-speech for
# the full list if you want to try a different one.
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "nova")

INSTALLED_APPS = [
    'django.contrib.sessions',
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "agent.apps.AgentConfig",
    "store",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "product_list"
LOGOUT_REDIRECT_URL = "product_list"

ROOT_URLCONF = "csa_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "store.context_processors.cart_count",
            ],
        },
    },
]

WSGI_APPLICATION = "csa_project.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

STATIC_URL = "static/"

# Uploaded product images (via /admin/) get saved here and served from
# MEDIA_URL. In production, swap this for real object storage (S3, GCS,
# etc.) — Django's own media serving isn't meant for production traffic.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
SESSION_ENGINE = "django.contrib.sessions.backends.db"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Max chat messages a single session may send within CHAT_RATE_LIMIT_WINDOW
# seconds, and how many past conversation turns get sent to the LLM.
CHAT_RATE_LIMIT_MAX = int(os.environ.get("CHAT_RATE_LIMIT_MAX", "10"))
CHAT_RATE_LIMIT_WINDOW = int(os.environ.get("CHAT_RATE_LIMIT_WINDOW", "60"))
CHAT_HISTORY_MAX_TURNS = int(os.environ.get("CHAT_HISTORY_MAX_TURNS", "10"))
# Longest single chat message accepted, so one request can't send an
# arbitrarily large (and arbitrarily expensive) prompt to the LLM.
CHAT_MESSAGE_MAX_CHARS = int(os.environ.get("CHAT_MESSAGE_MAX_CHARS", "1000"))

# Seconds before an OpenAI call gives up (the SDK default is 10 minutes),
# and how many times it retries transient failures.
OPENAI_TIMEOUT = float(os.environ.get("OPENAI_TIMEOUT", "30"))
OPENAI_MAX_RETRIES = int(os.environ.get("OPENAI_MAX_RETRIES", "2"))

# --- Escalation notifications -------------------------------------------
# When the agent flags a chat with [ESCALATE], agent/signals.py fires these
# so a human actually finds out — not just a row in the admin nobody's
# watching. Both are optional and independently no-op if left unset.

# EMAIL_BACKEND defaults to printing to the console, which is fine for dev.
# Set to "django.core.mail.backends.smtp.EmailBackend" (and the EMAIL_HOST*
# settings below) to send real email in production.
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True") == "True"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@deskyard.local")
# Without this, a hung SMTP server blocks the sending thread forever.
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))

# Address that gets emailed on every escalation. Empty string = disabled.
SUPPORT_NOTIFICATION_EMAIL = os.environ.get("SUPPORT_NOTIFICATION_EMAIL", "")

# Slack incoming-webhook URL for escalation pings. Empty string = disabled.
SLACK_ESCALATION_WEBHOOK_URL = os.environ.get("SLACK_ESCALATION_WEBHOOK_URL", "")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

