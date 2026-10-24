"""Bounded-memory, byte-exact delivery of files above Telegram's per-message ceiling."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from .media import check_disk

BLOCK = 8 * 1024 * 1024


async def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(BLOCK):
            digest.update(block)
            await asyncio.sleep(0)
    return digest.hexdigest()


async def file_parts(source: Path, limit: int, name: str):
    if limit <= 0 or Path(name).name != name:
        raise ValueError("Use a positive part size and a plain filename.")
    count = (source.stat().st_size + limit - 1) // limit
    with source.open("rb") as stream:
        for index in range(1, count + 1):
            path = source.parent / f"{name}.part{index:04d}"
            created = False
            try:
                remaining = limit
                with path.open("xb") as part:
                    created = True
                    while remaining and (block := stream.read(min(remaining, BLOCK))):
                        check_disk(source.parent)
                        part.write(block)
                        remaining -= len(block)
                        await asyncio.sleep(0)
                yield path, index, count
            finally:
                if created:
                    path.unlink(missing_ok=True)


def join_program(name: str, count: int, size: int, digest: str) -> str:
    """A dependency-free joiner verifies every byte before creating the completed media file."""
    return f'''"""Save this script beside all {count} parts and run it with Python 3."""
import hashlib
from pathlib import Path

folder = Path(__file__).resolve().parent
name = {name!r}
expected_size = {size}
expected_hash = {digest!r}
parts = [folder / (name + ".part%04d" % n) for n in range(1, {count + 1})]
if any(not part.is_file() for part in parts):
    raise SystemExit("Missing parts. Download every part into the same folder as this script.")
output = folder / name
if output.exists():
    raise SystemExit("The output already exists. Move it before joining again.")
temporary = folder / (name + ".joining")
digest = hashlib.sha256()
created = False
try:
    with temporary.open("xb") as result:
        created = True
        for part in parts:
            with part.open("rb") as source:
                while block := source.read(8 * 1024 * 1024):
                    result.write(block)
                    digest.update(block)
    if temporary.stat().st_size != expected_size or digest.hexdigest() != expected_hash:
        raise SystemExit("Parts are incomplete or corrupt. Download them again.")
    temporary.rename(output)
    print("Restored original file:", output.name)
finally:
    if created:
        temporary.unlink(missing_ok=True)
'''
