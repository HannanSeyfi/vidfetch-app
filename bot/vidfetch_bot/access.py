"""Persistent, owner-managed access. An empty member list never makes a private bot public."""

import json
import os
import tempfile
from pathlib import Path

MAX_USERS = 200


def valid_id(value: object) -> bool:
    return type(value) is int and 0 < value < 2**63


class AccessStore:
    def __init__(self, path: Path, owners: set[int], initial_users: set[int] | None = None):
        if not owners or not all(valid_id(value) for value in owners):
            raise ValueError("Configure at least one valid VIDFETCH_ADMIN_USERS owner ID.")
        self.path = path
        self.owners = frozenset(owners)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        if path.exists():
            try:
                if path.stat().st_size > 65_536:
                    raise ValueError
                payload = json.loads(path.read_text(encoding="utf-8"))
                values = payload["allowed_users"]
                if payload.get("version") != 1 or not isinstance(values, list):
                    raise ValueError
                if not all(valid_id(value) for value in values) or len(values) > MAX_USERS:
                    raise ValueError
                self.users = set(values) - self.owners
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError("The private access file is invalid. Restore it before starting.") from None
        else:
            users = set(initial_users or ()) - self.owners
            self._save(users)

    def allows(self, user_id: int) -> bool:
        return user_id in self.owners or user_id in self.users

    def _save(self, users: set[int]) -> None:
        if not all(valid_id(value) for value in users) or len(users) > MAX_USERS:
            raise ValueError(f"Use positive Telegram IDs; at most {MAX_USERS} users can be approved.")
        descriptor, name = tempfile.mkstemp(prefix="access-", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "allowed_users": sorted(users)}, stream)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            self.users = set(users)
        finally:
            temporary.unlink(missing_ok=True)

    def allow(self, users: set[int]) -> None:
        self._save((self.users | users) - self.owners)

    def deny(self, users: set[int]) -> None:
        if users & self.owners:
            raise ValueError("Owner access is configured on the server and cannot be removed here.")
        self._save(self.users - users)
