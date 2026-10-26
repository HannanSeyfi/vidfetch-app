"""Persistent, owner-managed access. An empty member list never makes a private bot public."""

import json
import os
import tempfile
from pathlib import Path

from .cookies import MAX_SITES, normalize_site

MAX_USERS = 200


def valid_id(value: object) -> bool:
    return type(value) is int and 0 < value < 2**63


class AccessStore:
    def __init__(self, path: Path, owners: set[int], initial_users: set[int] | None = None):
        if not owners or not all(valid_id(value) for value in owners):
            raise ValueError("Configure at least one valid VIDFETCH_ADMIN_USERS owner ID.")
        self.path = path
        self.owners = frozenset(owners)
        self.shares: dict[int, dict[str, int]] = {}
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        if path.exists():
            try:
                if path.stat().st_size > 2_000_000:
                    raise ValueError
                payload = json.loads(path.read_text(encoding="utf-8"))
                values = payload["allowed_users"]
                if payload.get("version") not in {1, 2} or not isinstance(values, list):
                    raise ValueError
                if not all(valid_id(value) for value in values) or len(values) > MAX_USERS:
                    raise ValueError
                self.users = set(values) - self.owners
                raw_shares = payload.get("cookie_shares", {})
                if not isinstance(raw_shares, dict) or len(raw_shares) > MAX_USERS:
                    raise ValueError
                for recipient, grants in raw_shares.items():
                    if not isinstance(recipient, str) or not recipient.isascii() or not recipient.isdecimal():
                        raise ValueError
                    recipient_text = recipient
                    recipient = int(recipient)
                    if str(recipient) != recipient_text:
                        raise ValueError
                    if not valid_id(recipient) or not self.allows(recipient) or not isinstance(grants, dict) or len(grants) > MAX_SITES + 1:
                        raise ValueError
                    for site, provider in grants.items():
                        if site != "*" and normalize_site(site) != site:
                            raise ValueError
                        if not valid_id(provider) and not (type(provider) is int and provider == 0 and site != "*"):
                            raise ValueError
                    self.shares[recipient] = dict(grants)
                self.path.chmod(0o600)
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError("The private access file is invalid. Restore it before starting.") from None
        else:
            users = set(initial_users or ()) - self.owners
            self._save(users)

    def allows(self, user_id: int) -> bool:
        return user_id in self.owners or user_id in self.users

    def _save(self, users: set[int], shares: dict[int, dict[str, int]] | None = None) -> None:
        if not all(valid_id(value) for value in users) or len(users) > MAX_USERS:
            raise ValueError(f"Use positive Telegram IDs; at most {MAX_USERS} users can be approved.")
        shares = self.shares if shares is None else shares
        shares = {user: dict(grants) for user, grants in shares.items() if user in users or user in self.owners}
        if len(shares) > MAX_USERS or any(len(grants) > MAX_SITES + 1 for grants in shares.values()):
            raise ValueError("Too many cookie-sharing rules. Remove an old rule first.")
        payload = json.dumps({"version": 2, "allowed_users": sorted(users), "cookie_shares": {str(user): grants for user, grants in shares.items()}}) + "\n"
        if len(payload.encode()) > 2_000_000:
            raise ValueError("The access configuration is too large.")
        descriptor, name = tempfile.mkstemp(prefix="access-", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            self.users = set(users)
            self.shares = shares
        finally:
            temporary.unlink(missing_ok=True)

    def allow(self, users: set[int]) -> None:
        self._save((self.users | users) - self.owners)

    def deny(self, users: set[int]) -> None:
        if users & self.owners:
            raise ValueError("Owner access is configured on the server and cannot be removed here.")
        self._save(self.users - users)

    def share_cookies(self, recipient: int, provider: int, site: str = "*") -> None:
        if not valid_id(recipient) or not self.allows(recipient):
            raise ValueError("Approve this user with /allow ID first.")
        if not valid_id(provider) or provider not in self.owners:
            raise ValueError("Only a configured owner can share their cookie set.")
        if recipient == provider:
            raise ValueError("Your requests already use your own cookies.")
        site = "*" if site in {"*", "all"} else normalize_site(site)
        shares = {user: dict(grants) for user, grants in self.shares.items()}
        grants = shares.setdefault(recipient, {})
        if site == "*":
            grants.clear()
        grants[site] = provider
        self._save(self.users, shares)

    def unshare_cookies(self, recipient: int, site: str = "*") -> None:
        site = "*" if site in {"*", "all"} else normalize_site(site)
        shares = {user: dict(grants) for user, grants in self.shares.items()}
        if site == "*":
            shares.pop(recipient, None)
        elif recipient in shares:
            shares[recipient].pop(site, None)
            if "*" in shares[recipient]:
                shares[recipient][site] = 0  # An explicit exception to an entire-set grant.
            if not shares[recipient]:
                shares.pop(recipient)
        self._save(self.users, shares)

    def recipients_for_owner(self, provider: int) -> set[int]:
        return {user for user, grants in self.shares.items() if provider in grants.values()}
