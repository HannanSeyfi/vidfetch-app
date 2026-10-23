import ast
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nbformat

ROOT = Path(__file__).resolve().parents[1]


class NotebookTests(unittest.TestCase):
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
            try:
                exec(compile(source, "notebook-setup", "exec"), namespace)
                for path in (ROOT / "vidfetch_bot").glob("*.py"):
                    self.assertEqual(
                        (Path(directory) / "vidfetch_bot" / path.name).read_text(encoding="utf-8"),
                        path.read_text(encoding="utf-8"),
                    )
            finally:
                sys.path[:] = original_path
