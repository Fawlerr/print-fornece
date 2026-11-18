"""Shared settings for the Print Fornece Django application."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    value = os.getenv(name) or default
    return [item.strip() for item in value.split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or os.getenv("SECRET_KEY") or "django-insecure-development-key-change-in-production"
DEBUG = env_bool("DJANGO_DEBUG", env_bool("DEBUG", False))
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", os.getenv("ALLOWED_HOSTS", "*"))
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    os.getenv("CSRF_TRUSTED_ORIGINS", "https://*.devdream.tech,https://*.duckdns.org,https://*.cloud,http://177.7.52.70,https://177.7.52.70,http://127.0.0.1:8080,http://localhost:8080")
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.audit",
    "apps.notifications",
    "apps.orders",
    "apps.production",
    "apps.expenses",
    "apps.reports",
    "apps.dashboard",
    "apps.payments",
    "apps.bug_reports",
    "apps.inventory",
    "apps.backups",
    "apps.business",
    "apps.whatsapp",
    "apps.integracoes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.UserActivityMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.security.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notifications.context_processors.navigation_notifications",
                "apps.business.context_processors.receipt_print",
                "apps.whatsapp.context_processors.chat",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME", "print_fornece"),
        "USER": os.getenv("MYSQL_USER") or os.getenv("DB_USER", "print_user"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASSWORD", "print_password"),
        "HOST": os.getenv("MYSQL_HOST") or os.getenv("DB_HOST", "db"),
        "PORT": os.getenv("MYSQL_PORT") or os.getenv("DB_PORT", "3306"),
        "CONN_MAX_AGE": int(os.getenv("MYSQL_CONN_MAX_AGE", "60")),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "apps.accounts.hashers.LegacyPHPBcryptPasswordHasher",
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = os.getenv("TIMEZONE", "America/Fortaleza")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",
    BASE_DIR / "images",
]
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_MANIFEST_STRICT = False
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
BACKUP_ROOT = BASE_DIR / "backups"
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
GOOGLE_DRIVE_CREDENTIALS_JSON = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON", "")
GOOGLE_DRIVE_CREDENTIALS_PATH = os.getenv("GOOGLE_DRIVE_CREDENTIALS_PATH", "")

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "6442450944"))  # 6 GB
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", "6442450944"))  # 6 GB
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("FILE_UPLOAD_MAX_MEMORY_SIZE", "10485760"))  # 10 MB em RAM antes de stream temporário em disco
LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "5"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
LOGIN_RATE_LIMIT_SECONDS = LOGIN_RATE_LIMIT_WINDOW_SECONDS

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "accounts:login"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", False)
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "pagamentos": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "whatsapp": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "integracoes": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ==============================================================================
# Stone / Pagar.me V5 Integration (Sandbox & Production)
# ==============================================================================
_raw_stone_env = os.getenv("STONE_ENVIRONMENT", "sandbox").strip().lower()

if _raw_stone_env in {"production", "prod", "live"}:
    STONE_ENVIRONMENT = "production"
    STONE_ACCOUNT_ID = (
        os.getenv("STONE_PROD_ACCOUNT_ID")
        or os.getenv("STONE_ACCOUNT_ID")
        or os.getenv("STONE_SANDBOX_ACCOUNT_ID")
        or ""
    ).strip()
    STONE_PUBLIC_KEY = (
        os.getenv("STONE_PROD_PUBLIC_KEY")
        or os.getenv("STONE_PUBLIC_KEY")
        or os.getenv("STONE_SANDBOX_PUBLIC_KEY")
        or ""
    ).strip()
    STONE_SECRET_KEY = (
        os.getenv("STONE_PROD_SECRET_KEY")
        or os.getenv("STONE_SECRET_KEY")
        or os.getenv("STONE_SANDBOX_SECRET_KEY")
        or ""
    ).strip()
    STONE_WEBHOOK_SECRET = (
        os.getenv("STONE_PROD_WEBHOOK_SECRET")
        or os.getenv("STONE_WEBHOOK_SECRET")
        or os.getenv("STONE_SANDBOX_WEBHOOK_SECRET")
        or ""
    ).strip()
    STONE_API_BASE_URL = (
        os.getenv("STONE_PROD_API_URL")
        or os.getenv("STONE_API_BASE_URL")
        or "https://api.pagar.me/core/v5"
    ).strip()
else:
    STONE_ENVIRONMENT = _raw_stone_env if _raw_stone_env in {"sandbox", "test"} else "sandbox"
    STONE_ACCOUNT_ID = (
        os.getenv("STONE_SANDBOX_ACCOUNT_ID")
        or os.getenv("STONE_ACCOUNT_ID")
        or ""
    ).strip()
    STONE_PUBLIC_KEY = (
        os.getenv("STONE_SANDBOX_PUBLIC_KEY")
        or os.getenv("STONE_PUBLIC_KEY")
        or ""
    ).strip()
    STONE_SECRET_KEY = (
        os.getenv("STONE_SANDBOX_SECRET_KEY")
        or os.getenv("STONE_SECRET_KEY")
        or ""
    ).strip()
    STONE_WEBHOOK_SECRET = (
        os.getenv("STONE_SANDBOX_WEBHOOK_SECRET")
        or os.getenv("STONE_WEBHOOK_SECRET")
        or ""
    ).strip()
    STONE_API_BASE_URL = (
        os.getenv("STONE_SANDBOX_API_URL")
        or os.getenv("STONE_API_BASE_URL")
        or "https://api.pagar.me/core/v5"
    ).strip()

STONE_TIMEOUT_SECONDS = int(os.getenv("STONE_TIMEOUT_SECONDS", "15"))
STONE_PIX_EXPIRES_IN = int(os.getenv("STONE_PIX_EXPIRES_IN", "86400"))
STONE_IDEMPOTENCY_TTL_SECONDS = int(os.getenv("STONE_IDEMPOTENCY_TTL_SECONDS", "300"))
STONE_ACCOUNT_TYPE = os.getenv("STONE_ACCOUNT_TYPE", "gateway").strip().lower()
STONE_PIX_DEBUG = env_bool("STONE_PIX_DEBUG", True)



# ==============================================================================
# Link de pagamento (Pagar.me V5 /paymentlinks) — host próprio por ambiente
# ==============================================================================
STONE_PAYMENT_LINK_API_URL = (
    os.getenv("STONE_PAYMENT_LINK_API_URL")
    or ("https://api.pagar.me/core/v5" if STONE_ENVIRONMENT == "production" else "https://sdx-api.pagar.me/core/v5")
).rstrip("/")

# ==============================================================================
# Chat de WhatsApp — provedor padrão: Umbler Talk (API oficial com token)
# ==============================================================================
WHATSAPP_PROVEDOR = os.getenv("WHATSAPP_PROVEDOR", "umbler").strip().lower()
UMBLER_API_URL = os.getenv("UMBLER_API_URL", "https://app-utalk.umbler.com/api").strip().rstrip("/")
# Token gerado em https://account.umbler.com/profile (fica só no servidor).
UMBLER_API_TOKEN = os.getenv("UMBLER_API_TOKEN", "").strip()
# Id da organização (GET /v1/members/me/).
UMBLER_ORGANIZATION_ID = os.getenv("UMBLER_ORGANIZATION_ID", "").strip()
UMBLER_TIMEOUT_SECONDS = int(os.getenv("UMBLER_TIMEOUT_SECONDS", "20"))
# Segredo que vai na URL do webhook cadastrada no painel da Umbler. Vazio = webhook recusa tudo.
UMBLER_WEBHOOK_SECRET = os.getenv("UMBLER_WEBHOOK_SECRET", "").strip()

# Chaves salvas pela página de desenvolvedor (Dev > Chaves de integração) ficam criptografadas com esta chave Fernet.
# Vazio = derivada da SECRET_KEY. Gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
INTEGRACOES_CHAVE_MESTRA = os.getenv("INTEGRACOES_CHAVE_MESTRA", "").strip()
# Endereço público do Print (usado para montar a URL do webhook na tela de números).
WHATSAPP_WEBHOOK_BASE_URL = (os.getenv("WHATSAPP_WEBHOOK_BASE_URL") or os.getenv("EVOLUTION_WEBHOOK_BASE_URL", "")).strip().rstrip("/")

# ==============================================================================
# Chat de WhatsApp — Evolution API (alternativa)
# ==============================================================================
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").strip().rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "").strip()
EVOLUTION_API_VERSION = os.getenv("EVOLUTION_API_VERSION", "2").strip()
EVOLUTION_TIMEOUT_SECONDS = int(os.getenv("EVOLUTION_TIMEOUT_SECONDS", "15"))
# Segredo que a Evolution devolve na URL/cabeçalho do webhook. Vazio = webhook recusa tudo.
EVOLUTION_WEBHOOK_SECRET = os.getenv("EVOLUTION_WEBHOOK_SECRET", "").strip()
# Endereço público do Print Fornece que a Evolution consegue acessar (ex.: https://print.exemplo.com.br).
EVOLUTION_WEBHOOK_BASE_URL = os.getenv("EVOLUTION_WEBHOOK_BASE_URL", "").strip().rstrip("/")
# Mídias do chat ficam fora de MEDIA_ROOT (não são servidas em /media/) e só saem por view com login.
WHATSAPP_MEDIA_ROOT = Path(os.getenv("WHATSAPP_MEDIA_ROOT", str(BASE_DIR / "private_media")))
WHATSAPP_MAX_UPLOAD_MB = int(os.getenv("WHATSAPP_MAX_UPLOAD_MB", "16"))
WHATSAPP_REVOGAR_ATE_HORAS = int(os.getenv("WHATSAPP_REVOGAR_ATE_HORAS", "48"))
