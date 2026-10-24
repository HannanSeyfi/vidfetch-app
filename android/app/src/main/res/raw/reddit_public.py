"""Use media exposed by the requested Reddit post when its JSON endpoint rejects access."""

import json
from html.parser import HTMLParser
from urllib.parse import urlsplit

from yt_dlp.extractor.reddit import RedditIE
from yt_dlp.utils import ExtractorError


class _PublicPost(HTMLParser):
    def __init__(self, post_id):
        super().__init__(convert_charrefs=True)
        self.post_id = "t3_" + post_id
        self.depth = 0
        self.post = None
        self.player = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "shreddit-post":
            if self.depth:
                self.depth += 1
            elif self.post is None and attrs.get("id") == self.post_id:
                self.post, self.depth = attrs, 1
        if (
            tag == "shreddit-player"
            and self.depth == 1
            and self.player is None
            and attrs.get("post-id") == self.post_id
            and attrs.get("src")
        ):
            self.player = attrs

    def handle_endtag(self, tag):
        if tag == "shreddit-post" and self.depth:
            self.depth -= 1


def public_post_media(webpage, post_id):
    parser = _PublicPost(post_id)
    parser.feed(webpage)
    if not parser.post or not parser.player:
        return None
    content = urlsplit(parser.post.get("content-href", ""))
    source = urlsplit(parser.player["src"])
    media_id = content.path.strip("/")
    if (
        content.scheme != "https"
        or content.hostname != "v.redd.it"
        or not media_id
        or "/" in media_id
        or source.scheme != "https"
        or source.hostname != "v.redd.it"
        or source.username
        or source.password
        or not source.path.startswith("/" + media_id + "/")
    ):
        return None
    return parser.post, parser.player, media_id


class RedditPublicIE(RedditIE, plugin_name="vidfetch_public"):
    def _real_extract(self, url):
        try:
            return super()._real_extract(url)
        except ExtractorError as original:
            detail = str(original).lower()
            if any(
                item in detail
                for item in ("private subreddit", "quarantined", "removed", "deleted", "429")
            ) or not any(
                item in detail
                for item in (
                    "403",
                    "unable to access the reddit api",
                    "account authentication is required",
                )
            ):
                raise
            post_id = self._match_id(url)
            public_url = "https://www.reddit.com" + urlsplit(url).path
            webpage = self._download_webpage(
                public_url,
                post_id,
                "Checking accessible Reddit post page",
                fatal=False,
                impersonate=True,
            )
            parsed = public_post_media(webpage or "", post_id)
            if parsed is None:
                raise original
            post, player, media_id = parsed
            source = player["src"]
            if urlsplit(source).path.endswith(".m3u8"):
                formats, subtitles = self._extract_m3u8_formats_and_subtitles(
                    source, media_id, "mp4", m3u8_id="public-hls", fatal=False
                )
            elif urlsplit(source).path.endswith(".mpd"):
                formats, subtitles = self._extract_mpd_formats_and_subtitles(
                    source, media_id, mpd_id="public-dash", fatal=False
                )
            else:
                raise original
            if not formats:
                raise original
            duration = None
            try:
                duration = json.loads(player.get("packaged-media-json", "{}"))["playbackMp4s"][
                    "duration"
                ]
            except (ValueError, TypeError, KeyError):
                pass
            return {
                "id": media_id,
                "display_id": post_id,
                "title": post.get("post-title") or player.get("post-title") or post_id,
                "uploader": post.get("author"),
                "thumbnail": player.get("poster"),
                "duration": duration,
                "formats": formats,
                "subtitles": subtitles,
                "webpage_url": public_url,
            }
