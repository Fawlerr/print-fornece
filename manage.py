#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - normal Django bootstrap text
        raise ImportError(
            "Django could not be imported. Activate the Python 3.12+ virtualenv "
            "and install requirements.txt."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

