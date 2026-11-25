import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.image import detection


class DetectionFallbackTests(unittest.TestCase):
    def test_secondary_runs_when_primary_finds_no_bubbles(self):
        primary_result = SimpleNamespace(boxes=SimpleNamespace(
            xyxy=torch.empty((0, 4)), conf=torch.empty(0), cls=torch.empty(0)))
        secondary_result = SimpleNamespace(boxes=SimpleNamespace(
            xyxy=torch.tensor([[5., 5., 25., 35.], [50., 50., 75., 85.]]),
            conf=torch.tensor([0.9, 0.9]), cls=torch.tensor([0., 0.])))
        primary = Mock(return_value=[primary_result])
        secondary = Mock(return_value=[secondary_result])
        secondary.names = {0: "text_bubble"}
        manager = Mock()
        manager.load_yolo_speech_bubble.return_value = primary
        manager.load_yolo_conjoined_bubble.return_value = secondary
        cache = Mock()
        cache.get_yolo_detection.return_value = None
        with patch.object(detection, "get_model_manager", return_value=manager), \
             patch.object(detection, "get_cache", return_value=cache), \
             patch.object(detection, "_build_segmentation_detections", return_value=[{"bbox": [5, 5, 25, 35]}]) as masks:
            bubbles, _ = detection.detect_speech_bubbles(Path("in-memory.png"), "synthetic-model",
                device="cpu", image_override=Image.new("RGB", (100, 100)), conjoined_detection=True)
        self.assertEqual(len(bubbles), 1)
        self.assertEqual(len(masks.call_args.args[0]), 2)
        self.assertTrue(all(source == "secondary" for source, _ in masks.call_args.args[2]))
        secondary.assert_called_once()


if __name__ == "__main__":
    unittest.main()
