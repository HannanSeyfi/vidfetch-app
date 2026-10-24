"""Optional Colab uploads staged outside notebook source and outputs."""

import os
import tempfile
from pathlib import Path

from .cookies import CookieError, CookieStore


def configure_cookies(store: CookieStore, actions: dict[str, str]) -> None:
    for site, action in actions.items():
        try:
            if action == "Import / replace":
                from google.colab import files

                print(f"Choose one Netscape cookies.txt export for {site}.")
                previous = Path.cwd()
                with tempfile.TemporaryDirectory(prefix="vidfetch-upload-") as directory:
                    try:
                        os.chdir(directory)
                        uploaded = files.upload()
                    finally:
                        os.chdir(previous)
                    if len(uploaded) != 1:
                        raise CookieError("Choose exactly one cookie file for each site.")
                    store.import_bytes(site, next(iter(uploaded.values())))
                    del uploaded
            elif action in {"Enable", "Disable"}:
                store.set_enabled(site, action == "Enable")
            elif action == "Delete":
                store.delete(site)
            elif action != "Keep":
                raise CookieError("Choose a cookie action from the menu.")
        except CookieError as error:
            print(str(error))
    print(store.status())
    print("Cookie values are private. Enabled cookies require a user allowlist in the start cell.")
