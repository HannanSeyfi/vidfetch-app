"""Exercise updated extractors with Python 3.12 and the app's CLI arguments."""
import importlib
import io
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.response

engine, native, base_url, folder, expected_version = sys.argv[1:6]
cli_file = sys.argv[6] if len(sys.argv) > 6 else None
sys.path.insert(0, engine)
import yt_dlp
from yt_dlp.networking import Request

assert yt_dlp.version.__version__ == expected_version

with open(os.path.join(folder, 'reddit.json'), 'w') as stream:
    json.dump([{'data': {'children': [{'data': {
        'id': 'fixture123', 'title': 'Compatibility fixture', 'author': 'fixture',
        'url': 'https://www.redgifs.com/watch/syntheticclip', 'over_18': False,
        'created_utc': 1, 'subreddit': 'videos',
    }}]}}], stream)
with open(os.path.join(folder, 'redgifs-auth.json'), 'w') as stream:
    json.dump({'token': 'synthetic-token'}, stream)
with open(os.path.join(folder, 'redgifs.json'), 'w') as stream:
    json.dump({'gif': {'id': 'syntheticclip', 'height': 240, 'width': 320,
                      'duration': 1, 'tags': [], 'urls': {'hd': base_url + '/source.mp4'}}}, stream)
with open(os.path.join(folder, 'share.html'), 'w') as stream:
    stream.write('<html><body>Share fixture</body></html>')
with open(os.path.join(folder, 'session.html'), 'w') as stream:
    stream.write('<html><body>Anonymous session fixture</body></html>')


class FixtureYoutubeDL(yt_dlp.YoutubeDL):
    def urlopen(self, request):
        if isinstance(request, str):
            request = Request(request)
        original = request.url
        parsed = urllib.parse.urlparse(original)
        path = None
        if parsed.hostname == 'www.reddit.com':
            path = '/reddit.json' if parsed.path.endswith('.json') else '/share.html'
            if path == '/reddit.json':
                assert any(cookie.name == 'loid' for cookie in self.cookiejar)
        elif parsed.hostname == 'old.reddit.com':
            path = '/session.html'
        elif parsed.hostname == 'api.redgifs.com':
            path = '/redgifs-auth.json' if parsed.path.endswith('/auth/temporary') else '/redgifs.json'
            if path == '/redgifs.json':
                assert request.headers.get('Authorization') == 'Bearer synthetic-token'
        if path:
            request = Request(base_url + path, data=request.data, headers=request.headers,
                              method=request.method, extensions=request.extensions)
        response = super().urlopen(request)
        if path:
            response.url = response.headers.get('X-Fixture-Url') or original
            # Preserve the original cookie origin while routing fixture traffic locally.
            self.cookiejar.extract_cookies(
                urllib.response.addinfourl(io.BytesIO(), response.headers, original),
                urllib.request.Request(original))
        return response


if cli_file:
    with open(cli_file) as stream:
        cli = json.load(stream)
    if cli.get('warning'):
        importlib.import_module('yt_dlp.YoutubeDL')._get_outdated_warning = lambda: (
            'Your yt-dlp version is older than 90 days!\n         Update recommended.')
    if cli.get('failure'):
        with open(os.path.join(folder, 'reddit.json'), 'w') as stream:
            json.dump({'error': 403, 'reason': 'private'}, stream)
    yt_dlp.YoutubeDL = FixtureYoutubeDL
    yt_dlp.main(cli['arguments'])
    sys.exit(0)


heights = []
cases = [
    ('reddit-share', 'https://www.reddit.com/r/videos/s/synthetic'),
    ('redgifs', 'https://www.redgifs.com/watch/syntheticclip'),
    ('hls', base_url + '/source.m3u8'),
    ('dash', base_url + '/source.mpd'),
]
for label, url in cases:
    with FixtureYoutubeDL({'quiet': True, 'noprogress': True, 'noplaylist': True,
                          'continuedl': False, 'overwrites': True,
                          'ffmpeg_location': os.path.join(native, 'libffmpeg.so'),
                          'format': ('bestvideo*+bestaudio/best' if label == 'hls'
                                     else 'bestvideo*[height<=360]+bestaudio/best[height<=360]'),
                          'merge_output_format': 'mp4',
                          'outtmpl': os.path.join(folder, 'compat-' + label + '.%(ext)s')}) as ydl:
        info = ydl.extract_info(url, download=True)
        heights.append(info.get('height'))
        destination = os.path.join(folder, 'compat-' + label + '.mp4')
        assert os.path.getsize(destination) > 1000
        probe = subprocess.check_output([os.path.join(native, 'libffprobe.so'), '-v', 'error',
                                         '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', destination], text=True)
        assert 'video' in probe and 'audio' in probe
        if label == 'redgifs':
            with open(os.path.join(folder, 'compat-info.json'), 'w') as stream:
                json.dump(ydl.sanitize_info(info), stream)
assert heights == [240, 240, None, 240], heights
print('VIDFETCH_COMPATIBILITY_OK')
