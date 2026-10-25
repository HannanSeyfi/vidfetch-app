"""Private-chat owner commands and owner-bound personal cookie controls."""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass

from . import media
from .access import AccessStore, valid_id
from .cookies import MAX_COOKIE_BYTES, CookieError, UserCookieStores

SITES = {"youtube": "youtube.com", "reddit": "reddit.com"}
LABELS = {"youtube": "YouTube", "reddit": "Reddit"}
OWNER_HELP = (
    "\n\nOwner controls:\n/allow ID — approve a user (multiple IDs may be separated by spaces)\n"
    "/deny ID — revoke access, cancel requests and forget their cookies\n"
    "/users — list owners and approved users"
)


@dataclass
class CookieMenu:
    owner: tuple[int, int]
    expires: float
    confirmation_site: str | None = None


class PersonalControls:
    def __init__(self, bot, access: AccessStore, stores: UserCookieStores):
        self.bot = bot
        self.api = bot.api
        self.access = access
        self.stores = stores
        self.menus: dict[str, CookieMenu] = {}
        self.pending: dict[tuple[int, int], tuple[str, float]] = {}

    def expire(self, owner: tuple[int, int] | None = None) -> None:
        now = time.monotonic()
        self.menus = {key: menu for key, menu in self.menus.items() if menu.expires > now and menu.owner != owner}
        self.pending = {key: value for key, value in self.pending.items() if value[1] > now}
        while len(self.menus) >= 200:
            self.menus.pop(next(iter(self.menus)))

    def forget_controls(self, user_id: int) -> None:
        self.menus = {key: menu for key, menu in self.menus.items() if menu.owner[1] != user_id}
        self.pending = {owner: value for owner, value in self.pending.items() if owner[1] != user_id}

    def menu_key(self, owner: tuple[int, int], confirmation_site: str | None = None) -> str:
        self.expire(owner)
        key = secrets.token_urlsafe(8)
        self.menus[key] = CookieMenu(owner, time.monotonic() + 600, confirmation_site)
        return key

    async def show(self, owner: tuple[int, int]) -> None:
        if not self.access.allows(owner[1]):
            return
        store = self.stores.for_user(owner[1])
        key = self.menu_key(owner)
        buttons = []
        for label, site in SITES.items():
            name = LABELS[label]
            buttons.append([{"text": f"Import / replace {name}", "callback_data": f"c:{key}:import:{label}"}])
            if store.has_site(site):
                action = "disable" if store.is_enabled(site) else "enable"
                buttons.append([
                    {"text": f"{action.title()} {name}", "callback_data": f"c:{key}:{action}:{label}"},
                    {"text": f"Delete {name}", "callback_data": f"c:{key}:delete:{label}"},
                ])
        await self.api.message(
            owner[0], "Your personal cookies\n\n" + store.status()
            + "\n\nOnly your requests use these exports. Choose an action below. "
            "Cookies pass through Telegram and are stored on this bot's host; the host operator "
            "can access server files. Never upload someone else's session. /cancel cancels an import.",
            keyboard=buttons,
        )

    async def admin(self, owner: tuple[int, int], text: str) -> bool:
        parts = text.split(maxsplit=1)
        if not parts:
            return False
        command, *arguments = parts
        command = command.split("@")[0].lower()
        if command not in {"/allow", "/deny", "/users"}:
            return False
        if owner[1] not in self.access.owners:
            await self.api.message(owner[0], "Only the bot owner can manage access.")
            return True
        try:
            if command == "/users":
                rows = ["Owners: " + ", ".join(map(str, sorted(self.access.owners))), "Approved users:"]
                rows += [str(value) for value in sorted(self.access.users)] or ["None yet. Use /allow ID."]
                output = ""
                for row in rows:
                    if len(output) + len(row) > 3500:
                        await self.api.message(owner[0], output)
                        output = ""
                    output += row + "\n"
                await self.api.message(owner[0], output.rstrip())
                return True
            values = re.split(r"[\s,]+", arguments[0].strip()) if arguments else []
            if not values or any(not re.fullmatch(r"[0-9]{1,19}", value) for value in values):
                raise ValueError(f"Use {command} followed by numeric Telegram user IDs.")
            users = {int(value) for value in values}
            if not all(valid_id(value) for value in users):
                raise ValueError("Telegram user IDs must be positive integers.")
            if command == "/allow":
                self.access.allow(users)
                result = "Approved: "
            else:
                self.access.deny(users)
                for user_id in users:
                    await self.bot.cancel_user(user_id)
                    self.forget_controls(user_id)
                    try:
                        self.stores.forget(user_id)
                    except OSError:
                        await self.api.message(owner[0], "Access is revoked, but cookie cleanup could not finish. Check the server's storage permissions.")
                        return True
                result = "Access revoked and stored cookies forgotten: "
            details = ", ".join(map(str, sorted(users))) if len(users) <= 10 else f"{len(users)} users. Use /users for the list."
            await self.api.message(owner[0], result + details)
        except ValueError as error:
            await self.api.message(owner[0], str(error))
        except OSError:
            await self.api.message(owner[0], "Could not save access changes. Check the server's storage and try again.")
        return True

    async def callback(self, query: dict, owner: tuple[int, int]) -> None:
        self.expire()
        match = re.fullmatch(r"c:([A-Za-z0-9_-]+):(import|enable|disable|delete|confirm|cancel):(youtube|reddit)", query.get("data", ""))
        menu = self.menus.get(match[1]) if match else None
        if (
            not menu or menu.owner != owner
            or (match[2] == "confirm" and menu.confirmation_site != match[3])
            or (menu.confirmation_site is not None and (match[2] not in {"confirm", "cancel"} or menu.confirmation_site != match[3]))
        ):
            await self.api.acknowledge(query["id"], "This cookie menu expired. Use /cookies.")
            return
        await self.api.acknowledge(query["id"])
        self.menus.pop(match[1], None)
        action, label = match[2], match[3]
        site = SITES[label]
        store = self.stores.for_user(owner[1])
        if action == "delete":
            key = self.menu_key(owner, label)
            await self.api.message(owner[0], f"Delete your saved {LABELS[label]} cookies from this bot?", keyboard=[[
                {"text": "Delete my cookies", "callback_data": f"c:{key}:confirm:{label}"},
                {"text": "Keep them", "callback_data": f"c:{key}:cancel:{label}"},
            ]])
            return
        if action == "cancel":
            await self.show(owner)
            return
        await self.bot.cancel_user(owner[1])
        self.pending.pop(owner, None)
        if action == "import":
            self.pending[owner] = (site, time.monotonic() + 600)
            await self.api.message(
                owner[0], f"Send your {site} Netscape cookies.txt export as a document within 10 minutes (maximum 2 MB). "
                "The export will pass through Telegram and be saved on this bot's host for your requests only. "
                "Only upload your own session. After import, you may remove your upload message from Telegram. "
                "Use /cancel to stop."
            )
            return
        try:
            if action == "confirm":
                store.delete(site)
            else:
                store.set_enabled(site, action == "enable")
            await self.show(owner)
        except (CookieError, OSError):
            await self.api.message(owner[0], "Could not update your cookies. Use /cookies and try again.")

    async def document(self, message: dict, owner: tuple[int, int]) -> None:
        self.expire()
        pending = self.pending.get(owner)
        if not pending:
            await self.api.message(owner[0], "Use /cookies and choose Import before sending a cookie file.")
            return
        document = message["document"]
        size = document.get("file_size")
        file_id = document.get("file_id")
        if type(size) is not int or not 0 < size <= MAX_COOKIE_BYTES or not isinstance(file_id, str) or not file_id:
            await self.api.message(owner[0], "Send a Netscape cookie export with a known size under 2 MB.")
            return
        site = pending[0]

        async def import_cookie(status, folder):
            media.check_disk(folder)
            await status("Importing your cookie export…")
            data = await self.api.read_document(file_id, max_bytes=MAX_COOKIE_BYTES)
            if not self.access.allows(owner[1]):
                return
            try:
                self.stores.for_user(owner[1]).import_bytes(site, data)
            except CookieError as error:
                await status(str(error))
                return
            finally:
                del data
            await status(f"Your {site} cookies were imported. Only your requests will use them.")
            await self.show(owner)

        if await self.bot.schedule(owner, import_cookie):
            self.pending.pop(owner, None)
