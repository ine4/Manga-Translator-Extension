import sys
from pathlib import Path
import unittest

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

if __name__ == "__main__":
    unittest.main()
