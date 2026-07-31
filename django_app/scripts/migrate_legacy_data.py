"""Convenience wrapper for `manage.py import_legacy_data`; no credentials live here."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

from django.core.management import execute_from_command_line  # noqa: E402

execute_from_command_line([str(ROOT / "manage.py"), "import_legacy_data", *sys.argv[1:]])

