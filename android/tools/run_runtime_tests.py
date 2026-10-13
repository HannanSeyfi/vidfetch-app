"""Run the native JUnit suite with non-streaming APK installation on older Android."""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys


def parse_result(output, expected):
    codes = []
    final_code = None
    for line in output.splitlines():
        if line.startswith("INSTRUMENTATION_STATUS_CODE:"):
            codes.append(int(line.split(":", 1)[1]))
        elif line.startswith("INSTRUMENTATION_CODE:"):
            final_code = int(line.split(":", 1)[1])
    passed = codes.count(0)
    failed = sum(code < 0 for code in codes)
    return {"passed": passed, "failed": failed, "expected": expected,
            "success": final_code == -1 and passed == expected and failed == 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-url")
    args = parser.parse_args()
    adb = shutil.which("adb")
    if not adb:
        raise RuntimeError("ADB is not available")
    base = [adb, "-s", "emulator-5554"]
    for apk in ("app/build/outputs/apk/debug/app-x86_64-debug.apk",
                "app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"):
        # Avoid Android 7's intermittently failing install-write stream transport.
        subprocess.run(base + ["install", "--no-streaming", "-r", "-t", apk], check=True, timeout=180)
    command = base + ["shell", "am", "instrument", "-w", "-r"]
    if args.live_url:
        command += ["-e", "class", "com.vidfetch.app.data.extractor.ExtractorRuntimeTest#userProvidedYoutubeLink",
                    "-e", "liveUrl", args.live_url]
    command += ["com.vidfetch.app.test/com.vidfetch.app.data.extractor.ExtractorInstrumentationRunner"]
    run = subprocess.run(command, text=True, capture_output=True, timeout=300)
    output = run.stdout + run.stderr
    print(output, flush=True)
    result = parse_result(output, 1 if args.live_url else 6)
    directory = pathlib.Path("app/build/reports/runtime-tests")
    directory.mkdir(parents=True, exist_ok=True)
    name = "live-youtube" if args.live_url else "required-runtime"
    (directory / f"{name}.txt").write_text(output, encoding="utf-8")
    (directory / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if run.returncode or not result["success"]:
        print("Runtime test failed: " + json.dumps(result), file=sys.stderr)
        return 1
    print("Runtime test passed: " + json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
