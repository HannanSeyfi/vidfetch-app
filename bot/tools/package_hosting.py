"""Package the source-built official server and its Linux libraries for non-root hosting."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from vidfetch_bot.local_api import API_REVISION, install_server

ROOT = Path(__file__).resolve().parents[1]


def package(output: Path):
    binary = install_server()
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        vendor = stage / "vendor"
        (vendor / "bin").mkdir(parents=True)
        (vendor / "lib").mkdir()
        shutil.copy2(binary, vendor / "bin/telegram-bot-api")
        libraries = subprocess.check_output(["ldd", str(binary)], text=True)
        for name in re.findall(r"(/[^\s()]+)", libraries):
            path = Path(name)
            shutil.copy2(path, vendor / "lib" / path.name)
        if not (vendor / "lib/ld-linux-x86-64.so.2").is_file():
            raise RuntimeError("This package requires the Linux x86-64 glibc loader.")
        wrapper = vendor / "telegram-bot-api"
        wrapper.write_text(
            '#!/bin/sh\nROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'exec "$ROOT/lib/ld-linux-x86-64.so.2" --library-path "$ROOT/lib" '
            '"$ROOT/bin/telegram-bot-api" "$@"\n'
        )
        wrapper.chmod(0o755)
        # Test the actual bundled loader and libraries, rather than the cached executable.
        subprocess.run([str(wrapper), "--version"], check=True)
        shutil.copytree(ROOT / "vidfetch_bot", stage / "vidfetch_bot", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "main.py", stage / "main.py")
        shutil.copy2(ROOT / "README.md", stage / "README.md")
        shutil.copy2(ROOT / "README.hosting.md", stage / "README.hosting.md")
        (stage / "requirements.txt").write_text(
            (ROOT / "requirements.txt").read_text() + "\npython-dotenv==1.2.4\n"
        )
        manifest = {
            "telegram_api_revision": API_REVISION,
            "platform": "linux-x86_64",
            "sha256": {
                str(path.relative_to(stage)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(stage.rglob("*")) if path.is_file()
            },
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(stage))
    print(f"Hosting package: {output.name} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    package(parser.parse_args().output)
