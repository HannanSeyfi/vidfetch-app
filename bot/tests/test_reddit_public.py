import unittest
from pathlib import Path
from unittest.mock import patch

from yt_dlp import YoutubeDL
from yt_dlp.utils import ExtractorError

from vidfetch_bot.reddit_public import RedditPublicIE, public_post_media

PAGE = """<shreddit-post id="t3_fixture" post-title="Requested post" author="fixture"
content-href="https://v.redd.it/media123"><shreddit-player post-id="t3_fixture"
src="https://v.redd.it/media123/HLSPlaylist.m3u8?token=public&amp;v=1"></shreddit-player>
</shreddit-post><shreddit-player post-id="t3_fixture"
src="https://v.redd.it/comment/HLSPlaylist.m3u8"></shreddit-player>"""


class PublicRedditTests(unittest.TestCase):
    def test_only_requested_posts_own_player_is_selected(self):
        post, player, media_id = public_post_media(PAGE, "fixture")
        self.assertEqual(media_id, "media123")
        self.assertEqual(post["post-title"], "Requested post")
        self.assertIn("token=public&v=1", player["src"])
        for text in (
            PAGE.replace('id="t3_fixture"', 'id="t3_other"', 1),
            PAGE.replace('post-id="t3_fixture"', 'post-id="t3_other"', 1),
            PAGE.replace("https://v.redd.it/media123/HLS", "https://attacker.example/HLS"),
            PAGE.replace("https://v.redd.it/media123/HLS", "https://v.redd.it/other/HLS"),
        ):
            self.assertIsNone(public_post_media(text, "fixture"))

    def test_json_rejection_falls_back_but_private_and_rate_limit_errors_do_not(self):
        with YoutubeDL({"quiet": True}) as ydl:
            ie = RedditPublicIE(ydl)
            base = RedditPublicIE.__mro__[1]
            original = ExtractorError("Account authentication is required", expected=True)
            with (
                patch.object(base, "_real_extract", side_effect=original),
                patch.object(ie, "_download_webpage", return_value=PAGE),
                patch.object(
                    ie,
                    "_extract_m3u8_formats_and_subtitles",
                    return_value=(
                        [{"format_id": "hls", "url": "https://v.redd.it/media123/video.ts"}],
                        {},
                    ),
                ),
            ):
                result = ie._real_extract("https://www.reddit.com/r/videos/comments/fixture/test/")
                self.assertEqual(result["id"], "media123")
                self.assertEqual(result["title"], "Requested post")
            for message in ("Private subreddit; HTTP 403", "HTTP 429", "Removed post"):
                failure = ExtractorError(message, expected=True)
                with (
                    patch.object(base, "_real_extract", side_effect=failure),
                    patch.object(ie, "_download_webpage") as page,
                ):
                    with self.assertRaises(ExtractorError) as caught:
                        ie._real_extract("https://www.reddit.com/r/videos/comments/fixture/test/")
                    self.assertIs(caught.exception, failure)
                    page.assert_not_called()

    def test_inaccessible_or_unrelated_page_preserves_the_original_error(self):
        with YoutubeDL({"quiet": True}) as ydl:
            ie = RedditPublicIE(ydl)
            failure = ExtractorError("HTTP 403", expected=True)
            with (
                patch.object(RedditPublicIE.__mro__[1], "_real_extract", side_effect=failure),
                patch.object(ie, "_download_webpage", return_value="<h1>Sign in</h1>"),
            ):
                with self.assertRaises(ExtractorError) as caught:
                    ie._real_extract("https://www.reddit.com/r/videos/comments/fixture/test/")
                self.assertIs(caught.exception, failure)

    def test_android_and_bot_ship_the_same_reviewed_fallback(self):
        root = Path(__file__).resolve().parents[2]
        android = root / "android/app/src/main/res/raw/reddit_public.py"
        bot = root / "bot/vidfetch_bot/reddit_public.py"
        self.assertEqual(android.read_text(encoding="utf-8"), bot.read_text(encoding="utf-8"))
