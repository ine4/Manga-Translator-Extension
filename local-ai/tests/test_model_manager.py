import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_manager as m

class CatalogTests(unittest.TestCase):
    def test_default_valid(self):
        m.require_safe(m.DEFAULT)
        self.assertEqual(m.repo_id(m.DEFAULT["repo"]), "Qwen/Qwen3-VL-4B-Instruct-GGUF")

    def test_hugging_face_link(self):
        self.assertEqual(m.repo_id("https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/tree/main"), m.DEFAULT["repo"])
        with self.assertRaises(ValueError):
            m.repo_id("https://example.org/Qwen/model")

    def test_reject_path_traversal(self):
        for field, value in [("id","../escape"),("weights","../file.gguf"),("projector","C:/file.gguf")]:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    m.require_safe({**m.DEFAULT, field:value})
        with self.assertRaises(ValueError):
            m.require_safe({**m.DEFAULT, "projector":m.DEFAULT["weights"]})

    def test_incomplete_download_is_unregistered_and_retry_records_revision(self):
        import huggingface_hub
        with TemporaryDirectory() as directory, patch.object(m, "ROOT", Path(directory)), \
             patch.object(huggingface_hub, "HfApi") as api:
            api.return_value.model_info.return_value = SimpleNamespace(sha="a" * 40)
            model = {**m.DEFAULT, "id": "synthetic-recovery"}
            def download(**kwargs):
                path = Path(kwargs["local_dir"]) / kwargs["filename"]
                path.write_bytes(b"GGUFsynthetic-test-data")
                return str(path)
            def interrupted(**kwargs):
                if kwargs["filename"] == model["projector"]:
                    raise RuntimeError("Synthetic download interruption")
                return download(**kwargs)
            with patch.object(huggingface_hub, "hf_hub_download", side_effect=interrupted):
                with self.assertRaises(RuntimeError):
                    m.install(model)
            manifest = Path(directory) / model["id"] / "model.json"
            self.assertFalse(manifest.exists())
            with patch.object(huggingface_hub, "hf_hub_download", side_effect=download):
                m.install(model)
            self.assertEqual(json.loads(manifest.read_text())["revision"], "a" * 40)

if __name__ == "__main__":
    unittest.main()
