"""Keep APK media executables out of Python's OpenSSL/library namespace."""
import os
import subprocess

# A separate session lets the Android service cancel this request's entire process
# tree without affecting other downloads. Remove the flag before spawning children.
if os.environ.pop('VIDFETCH_PROCESS_GROUP', None) == '1':
    os.setsid()
    print('VIDFETCH_PID:' + str(os.getpid()), flush=True)

_media_paths = {
    os.path.abspath(path) for path in (
        os.environ.get('VIDFETCH_FFMPEG_EXECUTABLE'),
        os.environ.get('VIDFETCH_FFPROBE_EXECUTABLE'),
    ) if path
}
_media_libraries = os.environ.get('VIDFETCH_MEDIA_LIBRARY_PATH')
_original_popen = subprocess.Popen


class _MediaPopen(_original_popen):
    vidfetch_media_isolated = True

    def __init__(self, args, *positional, **kwargs):
        command = kwargs.get('executable', positional[1] if len(positional) > 1 else None)
        if command is None:
            command = args[0] if isinstance(args, (list, tuple)) and args else args
        if isinstance(command, (str, bytes, os.PathLike)) and _media_libraries:
            if os.path.abspath(os.fsdecode(command)) in _media_paths:
                inherited = kwargs.get('env', positional[9] if len(positional) > 9 else None)
                environment = dict(os.environ if inherited is None else inherited)
                environment['LD_LIBRARY_PATH'] = _media_libraries
                for name in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONNOUSERSITE', 'PYTHONUNBUFFERED', 'OPENSSL_MODULES', 'LD_PRELOAD'):
                    environment.pop(name, None)
                if len(positional) > 9:
                    positional = (*positional[:9], environment, *positional[10:])
                else:
                    kwargs['env'] = environment
        super().__init__(args, *positional, **kwargs)


subprocess.Popen = _MediaPopen
