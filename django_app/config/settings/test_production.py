"""CI-only deployment-check profile using the isolated SQLite test database.

It never represents production: production.py always uses MySQL/MariaDB. This
module exists so `check --deploy` can be exercised on developer machines that
do not have MySQL client libraries installed.
"""
from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "CI-only-7dXy4!mQ9vL2@rT8#kP5$zN1wB6cF3hJ0sA7eD4gU9iO2xY5"
ALLOWED_HOSTS = ["testserver", "example.test"]
CSRF_TRUSTED_ORIGINS = ["https://example.test"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "deployment-check.sqlite3"}}  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
