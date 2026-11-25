"""Offline tests: no model weights, no real pictures and no GPU required."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_ai

class LocalAiTests(unittest.TestCase):
    def test_page_lease_released_even_on_failure(self):
        with patch.object(local_ai, "_post", return_value={}) as post:
            with self.assertRaises(ValueError):
                with local_ai.page_lease("qwen3-vl-4b"):
                    raise ValueError("synthetic failure")
            self.assertEqual(post.call_count, 2)
            first, last = [c.args[1] for c in post.call_args_list]
            self.assertEqual(first["id"], last["id"])
            self.assertTrue(first["keep"])
            self.assertFalse(last["keep"])

    def test_language_detection_and_inline_image(self):
        result = {"choices":[{"message":{"content":'{"language":"Korean","reading_direction":"ltr"}'}}]}
        with patch.object(local_ai, "_post", return_value=result) as post:
            self.assertEqual(local_ai.detect_page_language(Image.new("RGB",(20,20)), "qwen3-vl-4b"), ("Korean","ltr"))
            url, payload, timeout = post.call_args.args
            self.assertTrue(url.startswith("http://127.0.0.1:7678/"))
            self.assertTrue(payload["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_invalid_detection_unknown(self):
        with patch.object(local_ai, "_post", return_value={"choices":[]}):
            self.assertEqual(local_ai.detect_page_language(Image.new("RGB",(20,20)), "qwen3-vl-4b"), ("Unknown","rtl"))

    def test_local_requests_do_not_use_proxy_or_redirect(self):
        with patch.object(local_ai.requests, "Session") as factory:
            s = factory.return_value.__enter__.return_value
            s.post.return_value.ok = True
            s.post.return_value.is_redirect = False
            s.post.return_value.json.return_value = {"ok": True}
            self.assertTrue(local_ai._post(local_ai.CONTROL_URL, {}, 1)["ok"])
            self.assertFalse(s.trust_env)
            self.assertFalse(s.post.call_args.kwargs["allow_redirects"])

if __name__ == "__main__":
    unittest.main()
