"""Production settings for a Python 3.12+ WSGI/ASGI host."""
from .base import *  # noqa: F403

DEBUG = False
if not SECRET_KEY or SECRET_KEY.startswith("development-only"):  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be configured in production.")
if not DATABASES["default"]["NAME"]:  # noqa: F405
    raise RuntimeError("MYSQL_DATABASE must be configured in production.")

