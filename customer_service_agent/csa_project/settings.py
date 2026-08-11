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

INSTALLED_APPS = [
    'django.contrib.sessions',
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "agent",
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

