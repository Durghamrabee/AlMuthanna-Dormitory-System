"""Single-computer SQLite settings. Secrets come from the private local .env."""
import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_DIR))
BASE_DIR = Path(os.getenv("DORMITORY_DATA_DIR", str(PROJECT_DIR))).resolve()
load_dotenv(BASE_DIR / ".env")


def env_list(name, default=""):
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to at least 50 random characters.")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "apps.common", "apps.accounts", "apps.academics", "apps.students",
    "apps.dormitories", "apps.applications", "apps.accommodations",
    "apps.violations", "apps.maintenance", "apps.audit", "apps.reports",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.accounts.middleware.LocalOnlyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.LocalAccessMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [RESOURCE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": BASE_DIR / "db.sqlite3",
    "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
    # File-backed tests exercise the actual SQLite writer lock between connections.
    "TEST": {"NAME": BASE_DIR / "test_db.sqlite3"},
}}
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "ar"
LANGUAGES = [("ar", "العربية")]
TIME_ZONE = "Asia/Baghdad"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [RESOURCE_DIR / "static"]
# No media URL or development media serving: documents require authorized streaming views.
MEDIA_ROOT = BASE_DIR / "private_media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
LOCAL_HTTP = os.getenv("DJANGO_LOCAL_HTTP", "true").lower() == "true"
LOCAL_NO_LOGIN = os.getenv("DJANGO_LOCAL_NO_LOGIN", "false").lower() == "true"
if LOCAL_NO_LOGIN and not LOCAL_HTTP:
    raise ImproperlyConfigured("No-login mode is only supported in local HTTP mode.")
SESSION_COOKIE_SECURE = not LOCAL_HTTP
CSRF_COOKIE_SECURE = not LOCAL_HTTP
SECURE_SSL_REDIRECT = not LOCAL_HTTP
SECURE_HSTS_SECONDS = 31536000 if not LOCAL_HTTP else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not LOCAL_HTTP
SECURE_HSTS_PRELOAD = not LOCAL_HTTP
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = LOGIN_URL
SESSION_COOKIE_AGE = 1800
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = BASE_DIR / "private_mail"
DEFAULT_FROM_EMAIL = "dormitory@localhost"
PASSWORD_RESET_TIMEOUT = 1800
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "filters": {"redact_recovery": {"()": "apps.accounts.logging.RedactRecoveryLinks"}},
    "handlers": {"local_console": {"class": "logging.StreamHandler", "filters": ["redact_recovery"]}},
    "loggers": {"django.server": {"handlers": ["local_console"], "level": "INFO", "propagate": False}},
}
