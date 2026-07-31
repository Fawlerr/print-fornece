"""Safe defaults for local development and the isolated test database."""
from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
SECRET_KEY = "development-only-not-for-production"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DATABASES = {  # SQLite is intentionally limited to local development/tests, never production.
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}  # noqa: F405
}
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405

