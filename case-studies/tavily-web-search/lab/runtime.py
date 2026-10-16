"""Shared terminal credential prompt; no model/search execution on import."""
from getpass import getpass
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def request_key(name, label):
    value = os.environ.get(name, "").strip()
    if not value:
        if not sys.stdin.isatty():
            raise RuntimeError("Run in Terminal to enter missing credentials.")
        value = getpass(label + " (hidden): ").strip()
    if not value:
        raise RuntimeError("A required credential was left empty.")
    return value
