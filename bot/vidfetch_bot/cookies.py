"""Private, domain-scoped cookie imports. Never include cookie values in messages."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

MAX_COOKIE_BYTES = 2_000_000
SITES = ("youtube.com", "reddit.com")


class CookieError(ValueError):
    pass


def domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def site_for_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value if "://" in value else "https://" + value)
        if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
            return None
        host = (parsed.hostname or "").encode("idna").decode().lower().rstrip(".")
    except (ValueError, UnicodeError):
        return None
    if host == "youtu.be" or any(
        domain_matches(host, item) for item in ("youtube.com", "youtube-nocookie.com")
    ):
        return "youtube.com"
    if any(domain_matches(host, item) for item in ("reddit.com", "redditmedia.com", "redd.it")):
        return "reddit.com"
    return None


def scoped_cookies(data: bytes, site: str) -> str:
    if site not in SITES:
        raise CookieError("Choose youtube.com or reddit.com.")
    if len(data) > MAX_COOKIE_BYTES:
        raise CookieError("Cookie files must be smaller than 2 MB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        raise CookieError("Export a UTF-8 Netscape cookies.txt file.") from None
    if not text.startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File")):
        raise CookieError("Export cookies in Netscape cookies.txt format.")
    rows = []
    now = time.time()
    for line in text.splitlines():
        if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        fields = line.removeprefix("#HttpOnly_").split("\t")
        if (
            len(fields) != 7
            or fields[1] not in {"TRUE", "FALSE"}
            or fields[3] not in {"TRUE", "FALSE"}
            or not fields[2].startswith("/")
            or not fields[4].isascii()
            or not fields[4].isdigit()
            or len(fields[4]) > 20
            or (fields[0].startswith(".") != (fields[1] == "TRUE"))
            or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", fields[0].lstrip("."))
            or not fields[5]
            or "\x00" in line
        ):
            raise CookieError("The file contains an invalid Netscape cookie entry.")
        domain = fields[0].lstrip(".").lower().rstrip(".")
        expires = int(fields[4])
        if domain_matches(domain, site) and (expires == 0 or expires > now):
            rows.append(line)
    if not rows:
        raise CookieError(f"No unexpired cookies for {site}. Export a fresh signed-in session.")
    result = "# Netscape HTTP Cookie File\n" + "\n".join(rows) + "\n"
    return result


class CookieStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)

    def _path(self, site: str) -> Path:
        if site not in SITES:
            raise CookieError("Choose youtube.com or reddit.com.")
        return self.directory / f"{site}.cookies"

    def import_file(self, site: str, path: Path) -> None:
        with path.open("rb") as source:
            data = source.read(MAX_COOKIE_BYTES + 1)
        self.import_bytes(site, data)

    def import_bytes(self, site: str, data: bytes) -> None:
        value = scoped_cookies(data, site)
        descriptor, name = tempfile.mkstemp(prefix="import-", dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(value)
            temporary.replace(self._path(site))
            (self.directory / f"{site}.disabled").unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)

    def set_enabled(self, site: str, enabled: bool) -> None:
        if not self._path(site).is_file():
            raise CookieError(f"Import {site} cookies first.")
        marker = self.directory / f"{site}.disabled"
        if enabled:
            marker.unlink(missing_ok=True)
        else:
            marker.touch(mode=0o600)

    def delete(self, site: str) -> None:
        self._path(site).unlink(missing_ok=True)
        (self.directory / f"{site}.disabled").unlink(missing_ok=True)

    def has_enabled(self) -> bool:
        return any(self._enabled(site) for site in SITES)

    def has_site(self, site: str) -> bool:
        return self._path(site).is_file()

    def is_enabled(self, site: str) -> bool:
        return self._enabled(site)

    def _enabled(self, site: str) -> bool:
        return self._path(site).is_file() and not (self.directory / f"{site}.disabled").exists()

    def status(self) -> str:
        lines = []
        for site in SITES:
            if not self._path(site).exists():
                lines.append(f"{site}: no imported cookies")
                continue
            state = "enabled" if self._enabled(site) else "disabled"
            try:
                value = scoped_cookies(self._path(site).read_bytes(), site)
                rows = value.splitlines()[1:]
                names = {line.removeprefix("#HttpOnly_").split("\t")[5] for line in rows}
                account = (
                    {"reddit_session"}
                    if site == "reddit.com"
                    else {"SID", "__Secure-1PSID", "__Secure-3PSID"}
                )
                session = "sign-in cookie present" if names & account else "no sign-in cookie found"
                lines.append(f"{site}: {state}, {len(rows)} unexpired cookies, {session}")
            except CookieError:
                lines.append(f"{site}: {state}, expired or invalid; import a fresh export")
        return "\n".join(lines)

    @contextlib.contextmanager
    def snapshot_for(self, url: str, folder: Path):
        site = site_for_url(url)
        if site is None or not self._enabled(site):
            yield None
            return
        value = scoped_cookies(self._path(site).read_bytes(), site)
        descriptor, name = tempfile.mkstemp(prefix="session-", suffix=".cookies", dir=folder)
        snapshot = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(value)
            yield snapshot
        finally:
            snapshot.unlink(missing_ok=True)


class UserCookieStores:
    """Numeric user IDs select private stores; uploaded filenames never select paths."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def for_user(self, user_id: int) -> CookieStore:
        if type(user_id) is not int or not 0 < user_id < 2**63:
            raise CookieError("A valid Telegram user ID is required.")
        folder = self.root / str(user_id)
        if folder.is_symlink() or folder.resolve().parent != self.root:
            raise CookieError("The personal cookie directory is unavailable.")
        return CookieStore(folder)

    def forget(self, user_id: int) -> None:
        store = self.for_user(user_id)
        for site in SITES:
            store.delete(site)
        try:
            store.directory.rmdir()
        except OSError:
            pass  # Only the two known exports/markers are removed; never recurse.
