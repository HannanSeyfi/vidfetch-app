"""YouTube-style separate streams through the app's real CLI and native FFmpeg."""
import copy
import json
import sys

engine, base, config_file = sys.argv[1:]
sys.path.insert(0, engine)
import yt_dlp

formats = [
    {'format_id': 'avc240', 'url': base + '/video240.mp4', 'height': 240, 'width': 320, 'ext': 'mp4', 'vcodec': 'avc1', 'acodec': 'none'},
    {'format_id': 'avc360', 'url': base + '/video360.mp4', 'height': 360, 'width': 640, 'ext': 'mp4', 'vcodec': 'avc1', 'acodec': 'none'},
    {'format_id': 'vp9-480', 'url': base + '/video480.webm', 'height': 480, 'width': 854, 'ext': 'webm', 'vcodec': 'vp9', 'acodec': 'none'},
    {'format_id': 'aac', 'url': base + '/audio.m4a', 'ext': 'm4a', 'vcodec': 'none', 'acodec': 'mp4a.40.2', 'abr': 128},
    {'format_id': 'opus', 'url': base + '/audio.webm', 'ext': 'webm', 'vcodec': 'none', 'acodec': 'opus', 'abr': 160},
]
fixture = {'id': 'synthetic-video', 'title': 'Separate streams fixture', 'extractor': 'youtube', 'extractor_key': 'Youtube',
           'webpage_url': 'https://www.youtube.com/watch?v=synthetic-video', 'formats': formats}

class FixtureYoutubeDL(yt_dlp.YoutubeDL):
    def extract_info(self, url, download=True, **kwargs):
        assert 'synthetic-video' in url
        return self.process_ie_result(copy.deepcopy(fixture), download=download)

yt_dlp.YoutubeDL = FixtureYoutubeDL
with open(config_file) as stream:
    arguments = json.load(stream)
yt_dlp.main(arguments)
