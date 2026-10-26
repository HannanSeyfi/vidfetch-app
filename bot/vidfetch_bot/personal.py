"""Private-chat access management, explicit cookie delegation and custom website imports."""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass, field

from . import media
from .access import AccessStore, valid_id
from .cookie_routing import RoutedCookieStore
from .cookies import (
    MAX_COOKIE_BYTES,
    MAX_SITES,
    CookieError,
    UserCookieStores,
    normalize_site,
    scoped_cookies,
)

SITES = {"youtube": "youtube.com", "reddit": "reddit.com"}
LABELS = {"youtube.com": "YouTube", "reddit.com": "Reddit"}
PAGE_SIZE = 4
OWNER_HELP = (
    "\n\nOwner controls:\n/allow ID — approve users (multiple IDs may be separated by spaces)\n"
    "/deny ID — revoke access, cancel requests and forget their cookies\n"
    "/users — list approved users and cookie-sharing status\n"
    "/sharecookies ID [domain|all] — let an approved user use your cookies\n"
    "/unsharecookies ID [domain|all] — remove cookie sharing"
)


def site_label(site: str) -> str:
    return LABELS.get(site, site if len(site) <= 40 else site[:37] + "...")


def site_selector(site: str) -> str:
    return {"youtube.com": "youtube", "reddit.com": "reddit"}.get(site, "s" + hashlib.sha256(site.encode()).hexdigest()[:16])


@dataclass
class CookieMenu:
    owner: tuple[int, int]
    expires: float
    confirmation_site: str | None = None
    sites: dict[str, str] = field(default_factory=dict)
    page: int = 0


class PersonalControls:
    def __init__(self, bot, access: AccessStore, stores: UserCookieStores):
        self.bot = bot
        self.api = bot.api
        self.access = access
        self.stores = stores
        self.menus: dict[str, CookieMenu] = {}
        self.pending: dict[tuple[int, int], tuple[str, float]] = {}
        self.pending_domain: dict[tuple[int, int], float] = {}

    def expire(self, owner: tuple[int, int] | None = None) -> None:
        now = time.monotonic()
        self.menus = {key: menu for key, menu in self.menus.items() if menu.expires > now and menu.owner != owner}
        self.pending = {key: value for key, value in self.pending.items() if value[1] > now}
        self.pending_domain = {key: expires for key, expires in self.pending_domain.items() if expires > now}
        while len(self.menus) >= 200:
            self.menus.pop(next(iter(self.menus)))

    def forget_controls(self, user_id: int) -> None:
        self.menus = {key: menu for key, menu in self.menus.items() if menu.owner[1] != user_id}
        self.pending = {owner: value for owner, value in self.pending.items() if owner[1] != user_id}
        self.pending_domain = {owner: expires for owner, expires in self.pending_domain.items() if owner[1] != user_id}

    def menu_key(self, owner: tuple[int, int], confirmation_site: str | None = None, *, sites=(), page=0) -> str:
        self.expire(owner)
        key = secrets.token_urlsafe(8)
        values = tuple(sites) or ((confirmation_site,) if confirmation_site else tuple(SITES.values()))
        self.menus[key] = CookieMenu(owner, time.monotonic() + 600, confirmation_site, {site_selector(site): site for site in values}, page)
        return key

    async def show(self, owner: tuple[int, int], page: int = 0) -> None:
        if not self.access.allows(owner[1]):
            return
        self.pending_domain.pop(owner, None)
        store = self.stores.for_user(owner[1])
        routing = RoutedCookieStore(self.access, self.stores, owner[1])
        sites = tuple(dict.fromkeys((*SITES.values(), *store.sites(), *routing.shared_sites())))
        pages = max(1, (len(sites) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(0, min(page, pages - 1))
        visible = sites[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        key = self.menu_key(owner, sites=visible, page=page)
        buttons = []
        for site in visible:
            selector, label = site_selector(site), site_label(site)
            buttons.append([{"text": f"Import / replace {label}", "callback_data": f"c:{key}:import:{selector}"}])
            if store.has_site(site):
                action = "disable" if store.is_enabled(site) else "enable"
                buttons.append([
                    {"text": f"{action.title()} {label}", "callback_data": f"c:{key}:{action}:{selector}"},
                    {"text": f"Delete {label}", "callback_data": f"c:{key}:delete:{selector}"},
                ])
        buttons.append([{"text": "Add another site", "callback_data": f"c:{key}:add:new"}])
        navigation = []
        if page:
            navigation.append({"text": "Previous sites", "callback_data": f"c:{key}:page:{page - 1}"})
        if page + 1 < pages:
            navigation.append({"text": "More sites", "callback_data": f"c:{key}:page:{page + 1}"})
        if navigation:
            buttons.append(navigation)
        await self.api.message(
            owner[0], f"Your personal cookies · page {page + 1}/{pages}\n\nYour saved exports:\n" + store.status(visible)
            + "\n\n" + routing.summary(visible)
            + "\n\nUse /cookies example.com to import any website's cookies. These buttons manage only your own exports. "
            "Cookies pass through Telegram and are stored on this bot's host; host administrators can access server files. "
            "Only upload your own sessions. /cancel cancels an import.",
            keyboard=buttons,
        )

    async def cancel_dependents(self, provider: int) -> None:
        for recipient in self.access.recipients_for_owner(provider):
            await self.bot.cancel_user(recipient)

    async def start_import(self, owner: tuple[int, int], value: str) -> None:
        try:
            site = normalize_site(value)
            store = self.stores.for_user(owner[1])
            if not store.has_site(site) and len(store.sites()) >= MAX_SITES:
                raise CookieError(f"You can save cookies for {MAX_SITES} sites. Delete an old site first.")
        except CookieError as error:
            await self.api.message(owner[0], str(error))
            return
        await self.bot.cancel_user(owner[1])
        await self.cancel_dependents(owner[1])
        self.pending[owner] = (site, time.monotonic() + 600)
        sharing = " Users you have given owner-cookie access may also use this import." if owner[1] in self.access.owners else ""
        await self.api.message(
            owner[0], f"Send your {site} Netscape cookies.txt export as a document within 10 minutes (maximum 2 MB). "
            "It will pass through Telegram and be saved as your personal export on this host." + sharing
            + " Only upload your own session. You may remove the upload message afterward. Use /cancel to stop."
        )

    async def domain_message(self, owner: tuple[int, int], text: str) -> bool:
        self.expire()
        if owner not in self.pending_domain or not text or text.startswith("/"):
            return False
        await self.start_import(owner, text)
        return True

    async def admin(self, owner: tuple[int, int], text: str) -> bool:
        parts = text.split(maxsplit=1)
        if not parts:
            return False
        command = parts[0].split("@")[0].lower()
        if command not in {"/allow", "/deny", "/users", "/sharecookies", "/unsharecookies"}:
            return False
        if owner[1] not in self.access.owners:
            await self.api.message(owner[0], "Only the bot owner can manage access and cookie sharing.")
            return True
        try:
            if command == "/users":
                page = int(parts[1]) if len(parts) > 1 else 1
                users = sorted(self.access.users)
                pages = max(1, (len(users) + 19) // 20)
                if not 1 <= page <= pages:
                    raise ValueError(f"Use /users with a page number from 1 to {pages}.")
                rows = ["Owners: " + ", ".join(map(str, sorted(self.access.owners))), f"Approved users · page {page}/{pages}:"]
                for user in users[(page - 1) * 20:page * 20]:
                    grants = self.access.shares.get(user, {})
                    label = "owner cookie set" if "*" in grants else f"{sum(bool(v) for v in grants.values())} shared sites"
                    rows.append(str(user) + (" · " + label if grants else " · personal cookies"))
                if not users:
                    rows.append("None yet. Use /allow ID.")
                if page < pages:
                    rows.append(f"Next page: /users {page + 1}")
                await self.api.message(owner[0], "\n".join(rows))
                return True
            if command in {"/sharecookies", "/unsharecookies"}:
                arguments = parts[1].split() if len(parts) > 1 else []
                if len(arguments) not in {1, 2} or not re.fullmatch(r"[0-9]{1,19}", arguments[0]):
                    raise ValueError(f"Use {command} USER_ID [domain|all].")
                recipient = int(arguments[0])
                if not valid_id(recipient):
                    raise ValueError("Use a positive Telegram user ID.")
                site = arguments[1] if len(arguments) > 1 else "all"
                site = "*" if site.lower() in {"*", "all"} else normalize_site(site)
                if command == "/sharecookies":
                    self.access.share_cookies(recipient, owner[1], site)
                    detail = "your entire cookie set, including future imports" if site == "*" else f"your cookies for {site}"
                    result = f"{recipient} can now use {detail}. The cookie files are not sent to them."
                else:
                    self.access.unshare_cookies(recipient, site)
                    result = f"Cookie sharing removed for {recipient}" + ("." if site == "*" else f" on {site}.")
                await self.bot.cancel_user(recipient)
                await self.api.message(owner[0], result + " Existing requests were canceled; new requests use the updated setting.")
                return True
            arguments = re.split(r"[\s,]+", parts[1].strip()) if len(parts) > 1 else []
            if not arguments or any(not re.fullmatch(r"[0-9]{1,19}", value) for value in arguments):
                raise ValueError(f"Use {command} followed by numeric Telegram user IDs.")
            users = {int(value) for value in arguments}
            if not all(valid_id(value) for value in users):
                raise ValueError("Telegram user IDs must be positive integers.")
            if command == "/allow":
                self.access.allow(users)
                result = "Approved: "
            else:
                self.access.deny(users)
                for user_id in users:
                    await self.bot.cancel_user(user_id)
                    try:
                        self.stores.forget(user_id)
                    except OSError:
                        await self.api.message(owner[0], "Access and cookie sharing are revoked, but export cleanup could not finish. Check server storage permissions.")
                        return True
                result = "Access/sharing revoked and personal exports forgotten: "
            details = ", ".join(map(str, sorted(users))) if len(users) <= 10 else f"{len(users)} users. Use /users for the list."
            await self.api.message(owner[0], result + details)
        except ValueError as error:
            await self.api.message(owner[0], str(error))
        except OSError:
            await self.api.message(owner[0], "Could not save changes. Check server storage and try again.")
        return True

    async def callback(self, query: dict, owner: tuple[int, int]) -> None:
        self.expire()
        match = re.fullmatch(r"c:([A-Za-z0-9_-]+):(import|enable|disable|delete|confirm|cancel|add|page):([A-Za-z0-9_-]{1,20})", query.get("data", ""))
        menu = self.menus.get(match[1]) if match else None
        action = match[2] if match else ""
        selector = match[3] if match else ""
        site = menu.sites.get(selector) if menu else None
        special = (action == "add" and selector == "new") or (action == "page" and selector.isdecimal())
        if (
            not menu or menu.owner != owner or (not site and not special)
            or (action == "confirm" and menu.confirmation_site != site)
            or (menu.confirmation_site is not None and (action not in {"confirm", "cancel"} or menu.confirmation_site != site))
        ):
            await self.api.acknowledge(query["id"], "This cookie menu expired. Use /cookies.")
            return
        self.menus.pop(match[1], None)
        await self.api.acknowledge(query["id"])
        if action == "page":
            await self.show(owner, int(selector))
            return
        if action == "add":
            await self.bot.cancel_user(owner[1])
            self.pending_domain[owner] = time.monotonic() + 600
            await self.api.message(owner[0], "Send a website domain, such as youtube.com or example.com. Then I'll ask for its Netscape cookie export. Use /cancel to stop.")
            return
        if action == "import":
            await self.start_import(owner, site)
            return
        if action == "delete":
            key = self.menu_key(owner, site)
            await self.api.message(owner[0], f"Delete your saved cookies for {site}?", keyboard=[[
                {"text": "Delete my cookies", "callback_data": f"c:{key}:confirm:{site_selector(site)}"},
                {"text": "Keep them", "callback_data": f"c:{key}:cancel:{site_selector(site)}"},
            ]])
            return
        if action == "cancel":
            await self.show(owner, menu.page)
            return
        await self.bot.cancel_user(owner[1])
        try:
            await self.cancel_dependents(owner[1])
            store = self.stores.for_user(owner[1])
            if action == "confirm":
                store.delete(site)
            else:
                store.set_enabled(site, action == "enable")
            await self.show(owner, menu.page)
        except (CookieError, OSError):
            await self.api.message(owner[0], "Could not update your cookies. Use /cookies and try again.")

    async def document(self, message: dict, owner: tuple[int, int]) -> None:
        self.expire()
        pending = self.pending.get(owner)
        if not pending:
            await self.api.message(owner[0], "Use /cookies DOMAIN or choose Import before sending a cookie file.")
            return
        document = message["document"]
        size, file_id = document.get("file_size"), document.get("file_id")
        if type(size) is not int or not 0 < size <= MAX_COOKIE_BYTES or not isinstance(file_id, str) or not file_id:
            await self.api.message(owner[0], "Send a Netscape cookie export with a known size under 2 MB.")
            return
        site = pending[0]
        await self.cancel_dependents(owner[1])

        async def import_cookie(status, folder):
            media.check_disk(folder)
            await status("Importing your cookie export…")
            data = await self.api.read_document(file_id, max_bytes=MAX_COOKIE_BYTES)
            try:
                filtered = scoped_cookies(data, site).encode("utf-8")
            except CookieError as error:
                await status(str(error))
                return
            finally:
                del data
            if not self.access.allows(owner[1]):
                return
            try:
                await self.cancel_dependents(owner[1])
                self.stores.for_user(owner[1]).import_bytes(site, filtered)
            except CookieError as error:
                await status(str(error))
                return
            finally:
                del filtered
            await status(f"Your {site} cookies were imported. Any explicit owner-sharing permissions also apply to this export.")
            await self.show(owner)

        if await self.bot.schedule(owner, import_cookie):
            self.pending.pop(owner, None)
