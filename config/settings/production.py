"""Production settings for Python 3.14 WSGI/ASGI host."""
from .base import *  # noqa: F403

DEBUG = False
if not SECRET_KEY or SECRET_KEY == "development-only-change-me-before-production":  # noqa: F405
    raise RuntimeError("SECRET_KEY (ou DJANGO_SECRET_KEY) precisa ser configurado no arquivo .env para produção.")
if not DATABASES["default"]["NAME"]:  # noqa: F405
    raise RuntimeError("DB_NAME (ou MYSQL_DATABASE) precisa ser configurado no arquivo .env para produção.")
