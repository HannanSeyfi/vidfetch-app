"""Private, domain-scoped cookie imports. Never include cookie values in messages."""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from publicsuffixlist import PublicSuffixList

MAX_COOKIE_BYTES = 2_000_000
SITES = ("youtube.com", "reddit.com")
MAX_SITES = 25
_PSL = PublicSuffixList()


class CookieError(ValueError):
    pass


def domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def normalize_site(value: str) -> str:
    """A single website, never a public suffix, IP, URL credential or filesystem path."""
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise CookieError("Enter a website domain, such as youtube.com or example.com.")
    value = value.strip().removeprefix(".")
    value = {"youtube": "youtube.com", "reddit": "reddit.com"}.get(value.lower(), value)
    try:
        parsed = urlsplit(value if "://" in value else "https://" + value)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.port:
            raise ValueError
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        if len(host) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", host):
            raise ValueError
        if any(len(label) > 63 for label in host.split(".")) or not _PSL.privatesuffix(host):
            raise ValueError
        if not re.search(r"[a-z]", host.split(".")[-1]):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        if host.endswith((".localhost", ".local", ".internal", ".invalid", ".test", ".onion")):
            raise ValueError
        if host.startswith("www.") and host[4:] == _PSL.privatesuffix(host):
            host = host[4:]
    except (ValueError, UnicodeError):
        raise CookieError("Use a website domain, not an IP, public suffix, path or address with a port.") from None
    return canonical_host(host)


def canonical_host(host: str) -> str:
    if host == "youtu.be" or any(domain_matches(host, item) for item in ("youtube.com", "youtube-nocookie.com")):
        return "youtube.com"
    if any(domain_matches(host, item) for item in ("reddit.com", "redditmedia.com", "redd.it")):
        return "reddit.com"
    return host


def site_for_url(value: str, sites=None) -> str | None:
    try:
        parsed = urlsplit(value if "://" in value else "https://" + value)
        if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
            return None
        host = (parsed.hostname or "").encode("idna").decode().lower().rstrip(".")
    except (ValueError, UnicodeError):
        return None
    host = canonical_host(host)
    matches = [site for site in (SITES if sites is None else sites) if domain_matches(host, site)]
    return max(matches, key=len) if matches else None


def scoped_cookies(data: bytes, site: str) -> str:
    site = normalize_site(site)
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
        raise CookieError(f"No unexpired cookies for {site}. Check the domain or export a fresh signed-in session.")
    result = "# Netscape HTTP Cookie File\n" + "\n".join(rows) + "\n"
    return result


class CookieStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)

    def _path(self, site: str) -> Path:
        site = normalize_site(site)
        stem = site if len(site) <= 240 else "site-" + hashlib.sha256(site.encode()).hexdigest()
        return self.directory / f"{stem}.cookies"

    def sites(self) -> tuple[str, ...]:
        found = set()
        for path in self.directory.glob("*.cookies"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                name = path.stem
                if name.startswith("site-") and "." not in name:
                    with path.open("rb") as stream:
                        header = stream.read(1024)
                    name = next(line.removeprefix(b"# VidFetch site: ").decode("ascii") for line in header.splitlines() if line.startswith(b"# VidFetch site: "))
                site = normalize_site(name)
                if self._path(site) == path:
                    found.add(site)
            except (CookieError, OSError, UnicodeError, StopIteration):
                continue
        return tuple(sorted(found))

    def import_file(self, site: str, path: Path) -> None:
        with path.open("rb") as source:
            data = source.read(MAX_COOKIE_BYTES + 1)
        self.import_bytes(site, data)

    def import_bytes(self, site: str, data: bytes) -> None:
        site = normalize_site(site)
        if not self.has_site(site) and len(self.sites()) >= MAX_SITES:
            raise CookieError(f"You can save cookies for {MAX_SITES} sites. Remove an old site first.")
        value = scoped_cookies(data, site)
        if len(site) > 240:
            value = value.replace("# Netscape HTTP Cookie File\n", f"# Netscape HTTP Cookie File\n# VidFetch site: {site}\n", 1)
        descriptor, name = tempfile.mkstemp(prefix="import-", dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(value)
            temporary.replace(self._path(site))
            self._marker(site).unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)

    def set_enabled(self, site: str, enabled: bool) -> None:
        site = normalize_site(site)
        if not self._path(site).is_file():
            raise CookieError(f"Import {site} cookies first.")
        marker = self._marker(site)
        if enabled:
            marker.unlink(missing_ok=True)
        else:
            marker.touch(mode=0o600)

    def delete(self, site: str) -> None:
        self._path(site).unlink(missing_ok=True)
        self._marker(site).unlink(missing_ok=True)

    def _marker(self, site: str) -> Path:
        return self._path(site).with_suffix(".disabled")

    def has_enabled(self) -> bool:
        return any(self._enabled(site) for site in self.sites())

    def has_site(self, site: str) -> bool:
        return self._path(site).is_file()

    def is_enabled(self, site: str) -> bool:
        return self._enabled(site)

    def _enabled(self, site: str) -> bool:
        return self._path(site).is_file() and not self._marker(site).exists()

    def status(self, sites=None) -> str:
        lines = []
        for site in (tuple(dict.fromkeys((*SITES, *self.sites()))) if sites is None else sites):
            if not self._path(site).exists():
                lines.append(f"{site}: no imported cookies")
                continue
            state = "enabled" if self._enabled(site) else "disabled"
            try:
                value = scoped_cookies(self._path(site).read_bytes(), site)
                rows = value.splitlines()[1:]
                names = {line.removeprefix("#HttpOnly_").split("\t")[5] for line in rows}
                account = {"reddit.com": {"reddit_session"}, "youtube.com": {"SID", "__Secure-1PSID", "__Secure-3PSID"}}.get(site)
                session = ("sign-in cookie present" if names & account else "no sign-in cookie found") if account else "session validity unverified"
                lines.append(f"{site}: {state}, {len(rows)} unexpired cookies, {session}")
            except CookieError:
                lines.append(f"{site}: {state}, expired or invalid; import a fresh export")
        return "\n".join(lines)

    @contextlib.contextmanager
    def snapshot_for(self, url: str, folder: Path):
        site = site_for_url(url, self.sites())
        if site is None or not self._enabled(site):
            yield None
            return
        with self.snapshot_site(site, folder) as snapshot:
            yield snapshot

    @contextlib.contextmanager
    def snapshot_site(self, site: str, folder: Path):
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
        for site in set(SITES) | set(store.sites()):
            store.delete(site)
        try:
            store.directory.rmdir()
        except OSError:
            pass  # Only the two known exports/markers are removed; never recurse.
