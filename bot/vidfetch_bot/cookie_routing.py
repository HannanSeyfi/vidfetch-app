"""Choose personal or explicitly delegated owner cookies for each request."""

from contextlib import contextmanager

from .access import AccessStore
from .cookies import CookieError, UserCookieStores, site_for_url


class RoutedCookieStore:
    def __init__(self, access: AccessStore, stores: UserCookieStores, user_id: int):
        self.access = access
        self.stores = stores
        self.user_id = user_id

    def _provider(self, url: str):
        if not self.access.allows(self.user_id):
            raise CookieError("Your access to this bot was removed.")
        grants = self.access.shares.get(self.user_id, {})
        explicit = site_for_url(url, [site for site in grants if site != "*"])
        provider = grants.get(explicit) if explicit else grants.get("*")
        if not provider:
            return self.stores.for_user(self.user_id), False, None
        if provider not in self.access.owners:
            raise CookieError("The owner who shared these cookies is no longer available. Contact the bot owner.")
        store = self.stores.for_user(provider)
        site = site_for_url(url, store.sites())
        if site is None and explicit:
            raise CookieError(f"Owner-shared cookies for {explicit} are missing. Ask the owner to import them.")
        return store, True, site

    @contextmanager
    def snapshot_for(self, url, folder):
        store, shared, site = self._provider(url)
        if not shared:
            with store.snapshot_for(url, folder) as snapshot:
                yield snapshot
            return
        if site is None:
            # Whole-set mode uses guest access where the owner has no export, never another account.
            yield None
            return
        if not store.is_enabled(site):
            raise CookieError(f"Owner-shared cookies for {site} are disabled. Ask the owner to enable them.")
        try:
            with store.snapshot_site(site, folder) as snapshot:
                yield snapshot
        except CookieError:
            raise CookieError(f"Owner-shared cookies for {site} are expired or invalid. Ask the owner to replace them.") from None

    def shared_sites(self) -> tuple[str, ...]:
        grants = self.access.shares.get(self.user_id, {})
        sites = {site for site, provider in grants.items() if site != "*" and provider}
        provider = grants.get("*")
        if provider in self.access.owners:
            sites.update(self.stores.for_user(provider).sites())
        return tuple(sorted(sites))

    def summary(self, sites) -> str:
        grants = self.access.shares.get(self.user_id, {})
        if not grants:
            return "Cookie source: your own exports, or guest access when none are enabled."
        lines = []
        if "*" in grants:
            lines.append("Owner-cookie mode: the owner's set is used, including future imports. Your exports are not used unless a site is unshared.")
        for site in sites:
            explicit = site_for_url("https://" + site, [key for key in grants if key != "*"])
            provider = grants.get(explicit) if explicit else grants.get("*")
            lines.append(f"{site}: " + ("owner-shared cookies" if provider else "your own cookies / guest"))
        return "\n".join(lines)
