import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import TranslationConfig
from core.services.translation import _call_llm_endpoint
from utils.endpoints import openai_compatible


class ProviderRequestTests(unittest.TestCase):
    def config(self, url, key):
        return TranslationConfig(provider="OpenAI-Compatible", model_name="synthetic-model",
            openai_compatible_url=url, openai_compatible_api_key=key)

    def response(self):
        response = Mock(is_redirect=False)
        response.json.return_value = {"choices": [{"message": {"content": "1: Hola"}}]}
        return response

    def test_cloud_multimodal_request_keeps_provider_settings(self):
        config = self.config("https://synthetic-provider.invalid/v1", "synthetic-key")
        with patch.object(openai_compatible.requests, "post", return_value=self.response()) as post:
            result = _call_llm_endpoint(config,
                [{"inline_data": {"mime_type": "image/png", "data": "c3ludGhldGlj"}}],
                "Synthetic translation request", system_prompt="Synthetic system instruction")
        self.assertEqual(result, "1: Hola")
        self.assertEqual(post.call_args.args[0], "https://synthetic-provider.invalid/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer synthetic-key")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "synthetic-model")
        self.assertTrue(payload["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_local_multimodal_request_disables_proxy_and_redirect(self):
        config = self.config("http://127.0.0.1:7678/v1", "manga-local")
        with patch.object(openai_compatible.requests, "Session") as factory:
            session = factory.return_value.__enter__.return_value
            session.post.return_value = self.response()
            self.assertEqual(_call_llm_endpoint(config, [], "Synthetic request"), "1: Hola")
            self.assertFalse(session.trust_env)
            self.assertFalse(session.post.call_args.kwargs["allow_redirects"])


if __name__ == "__main__":
    unittest.main()
