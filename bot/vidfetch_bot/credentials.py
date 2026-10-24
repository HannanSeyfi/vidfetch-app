"""Read credentials without putting them in notebook source or output."""

import os
from getpass import getpass


def read_secret(name: str, prompt: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        try:
            from google.colab import userdata

            value = str(userdata.get(name) or "").strip()
        except Exception:
            # Missing Colab secret, denied permission, or a non-Colab environment.
            # Do not print exception text, which is controlled by the secret provider.
            value = ""
    return value or getpass(prompt).strip()
