"""Mock the image pipeline; exercise real API schemas and local/cloud config."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from endpoints import translate


class ApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(translate.router)
        self.client = TestClient(app)
        self.image = Image.new("RGB", (20, 20), "white")
        self.pipeline = patch.object(translate, "translate_image_base64",
            return_value=(self.image, [], 0.01))
        self.mock_pipeline = self.pipeline.start()
        self.addCleanup(self.pipeline.stop)
        self.addCleanup(self.image.close)

    def test_single_cloud_settings_remain_independent(self):
        response = self.client.post("/translate", json={"image": "synthetic",
            "provider": "OpenAI-Compatible", "base_url": "https://provider.example/v1",
            "api_key": "synthetic-key", "model_name": "cloud-model"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()), {"translated_image", "bubbles",
            "processing_time_seconds", "source_language", "target_language", "provider"})
        config = self.mock_pipeline.call_args.args[1].translation
        self.assertFalse(config.local_managed)
        self.assertEqual(config.openai_compatible_url, "https://provider.example/v1")
        self.assertEqual(config.openai_compatible_api_key, "synthetic-key")

    def test_local_discards_cloud_settings(self):
        response = self.client.post("/translate", json={"image": "synthetic",
            "provider": "Local", "base_url": "https://provider.example/v1",
            "api_key": "synthetic-key"})
        self.assertEqual(response.status_code, 200, response.text)
        config = self.mock_pipeline.call_args.args[1].translation
        self.assertTrue(config.local_managed)
        self.assertEqual(config.openai_compatible_url, "http://127.0.0.1:7678/v1")
        self.assertEqual(config.openai_compatible_api_key, "manga-local")

    def test_batch_success_and_failure_wire_shapes(self):
        self.mock_pipeline.side_effect = [(self.image, [], 0.01), RuntimeError("synthetic")]
        response = self.client.post("/translate/batch", json={"images": [
            {"id": "one", "image": "synthetic"}, {"id": "two", "image": "synthetic"}]})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["success_count"], body["error_count"]), (1, 1))
        self.assertEqual([item["id"] for item in body["results"]], ["one", "two"])
        self.assertTrue(body["results"][0]["translated_image"])
        self.assertIsNone(body["results"][1]["translated_image"])
        self.assertEqual(body["results"][1]["error"], "Translation failed.")

    def test_rejects_path_output_before_running_pipeline(self):
        for route, body in [("/translate", {"image": "synthetic"}),
                            ("/translate/batch", {"images": []})]:
            for option in ("output_path", "output_dir"):
                with self.subTest(route=route, option=option):
                    response = self.client.post(route, json={**body, option: "forbidden.png"})
                    self.assertEqual(response.status_code, 422, response.text)
        self.mock_pipeline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
