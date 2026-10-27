import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
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


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


# Secure by default: DEBUG is off unless DJANGO_DEBUG=True is set (local
# dev sets it in .env). Production mode refuses to start without a real
# secret key instead of quietly using the generated dev one.
DEBUG = _env_bool("DJANGO_DEBUG")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off. For local "
            "development, set DJANGO_DEBUG=True in .env (see .env.example)."
        )
    SECRET_KEY = _get_dev_secret_key()

# Comma-separated, e.g. "shop.example.com,www.shop.example.com".
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS") or (["localhost", "127.0.0.1", "[::1]"] if DEBUG else [])
# Full origins, e.g. "https://shop.example.com". Needed for form posts
# when the site is served over HTTPS behind a proxy on another host name.
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Number of reverse proxies (load balancer, nginx, etc.) in front of the
# app that append to X-Forwarded-For. 0 means trust only REMOTE_ADDR, so
# clients can't spoof their IP to dodge the chat rate limit.
NUM_PROXIES = int(os.environ.get("DJANGO_NUM_PROXIES", "0"))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Used by the browser voice call feature (agent/views.py:tts_api) for
# natural-sounding spoken replies. "nova" is a warm, friendly-sounding
# voice — see https://platform.openai.com/docs/guides/text-to-speech for
# the full list if you want to try a different one.
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "nova")

INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "agent.apps.AgentConfig",
    "store",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# HTTPS hardening, on whenever DEBUG is off. The redirect and HSTS are
# opt-in because they depend on how TLS is terminated: set
# DJANGO_SECURE_SSL_REDIRECT=True if Django should redirect HTTP to HTTPS,
# and DJANGO_SECURE_HSTS_SECONDS only once HTTPS is confirmed working
# (browsers remember HSTS, so a mistake is hard to undo).
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT")
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
if NUM_PROXIES:
    # Trust the proxy's report of the original scheme so request.is_secure()
    # (and the SSL redirect) work behind a TLS-terminating proxy.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

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
# Where `manage.py collectstatic` gathers files for the web server in production.
STATIC_ROOT = BASE_DIR / "staticfiles"

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
EMAIL_BACKEND = os.environ.get("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
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

# Send app logs (e.g. failed OpenAI calls, failed escalation alerts) to the
# console, where the process manager or container runtime collects them.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "agent": {"handlers": ["console"], "level": "INFO"},
        "store": {"handlers": ["console"], "level": "INFO"},
    },
}
