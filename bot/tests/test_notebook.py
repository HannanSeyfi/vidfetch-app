import ast
import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import nbformat

ROOT = Path(__file__).resolve().parents[1]


class NotebookTests(unittest.TestCase):
    def test_start_with_account_cookies_and_no_allowlist_never_reads_credentials(self):
        notebook = json.loads((ROOT / "VidFetch_Telegram_Colab.ipynb").read_text(encoding="utf-8"))
        source = "".join(
            next(cell for cell in notebook["cells"] if cell["id"] == "start")["source"]
        )
        namespace = {"vidfetch_cookies": SimpleNamespace(has_enabled=lambda: True)}
        with (
            patch("vidfetch_bot.credentials.read_secret") as read,
            patch("builtins.print") as output,
        ):
            code = compile(source, "notebook-start", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            asyncio.run(eval(code, namespace))
            read.assert_not_called()
            self.assertIn("allowed_user_ids", str(output.call_args_list))

    def test_cookie_uploads_are_scoped_private_and_temporary(self):
        from vidfetch_bot.colab_cookies import configure_cookies
        from vidfetch_bot.cookies import CookieStore

        uploaded_directory = []

        def upload():
            uploaded_directory.append(Path.cwd())
            data = b"# Netscape HTTP Cookie File\n.reddit.com\tTRUE\t/\tTRUE\t0\treddit_session\tprivate-fixture\n"
            Path("cookies.txt").write_bytes(data)
            return {"cookies.txt": data}

        with tempfile.TemporaryDirectory() as directory:
            store = CookieStore(Path(directory) / "private")
            original = Path.cwd()
            with (
                patch.dict(
                    sys.modules,
                    {"google.colab": SimpleNamespace(files=SimpleNamespace(upload=upload))},
                ),
                patch("builtins.print") as output,
            ):
                configure_cookies(store, {"reddit.com": "Import / replace"})
                self.assertNotIn("private-fixture", str(output.call_args_list))
            self.assertEqual(Path.cwd(), original)
            self.assertFalse(uploaded_directory[0].exists())
            self.assertTrue(store.has_enabled())
            configure_cookies(store, {"reddit.com": "Delete"})
            self.assertFalse(store.has_enabled())

    def test_start_cell_uses_all_credentials_and_the_local_api_context(self):
        notebook = json.loads((ROOT / "VidFetch_Telegram_Colab.ipynb").read_text(encoding="utf-8"))
        source = "".join(
            next(cell for cell in notebook["cells"] if cell["id"] == "start")["source"]
        )
        connected = object()
        calls = []

        @asynccontextmanager
        async def server(token, identifier, secret, *, binary):
            calls.append((token, identifier, secret, binary))
            yield connected
            calls.append("stopped")

        cookies = SimpleNamespace(has_enabled=lambda: False)
        namespace = {"vidfetch_api_binary": Path("server-fixture"), "vidfetch_cookies": cookies}
        with (
            patch(
                "vidfetch_bot.credentials.read_secret",
                side_effect=["hidden-token", "123", "hidden-hash"],
            ),
            patch("vidfetch_bot.local_api.local_bot_api", server),
            patch("vidfetch_bot.app.run_bot", AsyncMock()) as run,
            patch("builtins.print") as output,
        ):
            code = compile(source, "notebook-start", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            asyncio.run(eval(code, namespace))
            run.assert_awaited_once_with(
                "hidden-token", allowed_users=set(), api=connected, cookie_store=cookies
            )
            self.assertEqual(
                calls, [("hidden-token", "123", "hidden-hash", Path("server-fixture")), "stopped"]
            )
            self.assertNotIn("hidden-", str(output.call_args_list))

    def test_generated_notebook_matches_sources_and_is_valid(self):
        spec = importlib.util.spec_from_file_location(
            "build_notebook", ROOT / "tools" / "build_notebook.py"
        )
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        notebook = json.loads((ROOT / "VidFetch_Telegram_Colab.ipynb").read_text(encoding="utf-8"))
        self.assertEqual(notebook, builder.notebook())
        nbformat.validate(nbformat.from_dict(notebook))
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                self.assertIsNone(cell["execution_count"])
                self.assertEqual(cell["outputs"], [])
                compile(
                    "".join(cell["source"]),
                    "notebook",
                    "exec",
                    flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
                )

    def test_setup_cell_materializes_importable_package_without_github(self):
        notebook = json.loads((ROOT / "VidFetch_Telegram_Colab.ipynb").read_text(encoding="utf-8"))
        source = "".join(notebook["cells"][1]["source"])
        namespace = {}
        real_import = __import__

        def setup_import(name, *args, **kwargs):
            if name == "vidfetch_bot.local_api":
                return SimpleNamespace(install_server=lambda: Path("mock-server"))
            return real_import(name, *args, **kwargs)

        # Exercise the generated bootstrap itself; dependency installation is tested by CI.
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("tempfile.mkdtemp", return_value=directory),
            patch("subprocess.run"),
            patch("shutil.which", return_value="installed"),
            patch("subprocess.check_output", return_value="libx264"),
            patch("builtins.print"),
            patch("builtins.__import__", side_effect=setup_import),
        ):
            import sys

            original_path = sys.path[:]
            original_modules = {
                name: module
                for name, module in sys.modules.items()
                if name == "vidfetch_bot" or name.startswith("vidfetch_bot.")
            }
            try:
                exec(compile(source, "notebook-setup", "exec"), namespace)
                for path in (ROOT / "vidfetch_bot").glob("*.py"):
                    self.assertEqual(
                        (Path(directory) / "vidfetch_bot" / path.name).read_text(encoding="utf-8"),
                        path.read_text(encoding="utf-8"),
                    )
            finally:
                sys.path[:] = original_path
                for name in list(sys.modules):
                    if name == "vidfetch_bot" or name.startswith("vidfetch_bot."):
                        del sys.modules[name]
                sys.modules.update(original_modules)
