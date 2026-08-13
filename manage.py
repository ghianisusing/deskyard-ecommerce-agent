#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "csa_project.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Did you activate your virtualenv and "
            "run 'pip install -r requirements.txt'?"
        ) from exc
    execute_from_command_line(sys.argv)
