"""Live CUDA smoke/benchmark. Creates a synthetic image entirely in RAM."""
import base64
import io
import json
from pathlib import Path
import sys
import time
import uuid
import urllib.request
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
from core.config import TranslationConfig
from core.services.translation import call_translation_api_batch

ROOT = "http://127.0.0.1:7678"
MODEL = "qwen3-vl-4b"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def request(path, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(ROOT+path, data=data,
        headers={"X-Manga-Local":"1","Content-Type":"application/json"})
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)

def main():
    before = request("/local/models")
    if before["leases"] or before["loaded_model"]:
        raise RuntimeError("Release all browser/GUI pins and stop other translations before benchmark")
    if not any(m["id"]==MODEL and m["installed"] for m in before["models"]):
        raise RuntimeError("Install the default model first")
    lease = "gui:" + str(uuid.uuid4())
    config = TranslationConfig(provider="OpenAI-Compatible", local_managed=True,
        model_name=MODEL, input_language="English", output_language="Spanish",
        openai_compatible_url=ROOT + "/v1", openai_compatible_api_key="manga-local",
        translation_mode="one-step", send_full_page_context=False, temperature=0)
    font = ImageFont.truetype(str(REPO / "backend/fonts/Roboto/Roboto-Regular.ttf"), 32)
    try:
        start = time.perf_counter()
        request("/local/lease",{"id":lease,"model":MODEL,"keep":True})
        print(f"Initial model load: {time.perf_counter()-start:.3f}s")
        for i, (source, expected) in enumerate([
            ("HELLO WORLD", ("hola", "mundo")), ("THANK YOU", ("gracias",)),
        ]):
            image = Image.new("RGB", (480,160), "white")
            draw = ImageDraw.Draw(image)
            draw.ellipse((10,10,470,150), outline="black", width=3)
            draw.text((100,60), source, font=font, fill="black")
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            data = base64.b64encode(buf.getvalue()).decode("ascii")
            start=time.perf_counter()
            result = call_translation_api_batch(config, [data], "", ["image/png"],
                "image/png", [{"is_outside_text":False}])
            assert len(result) == 1 and all(word in result[0].casefold() for word in expected), "Production vision translation was incorrect"
            print(f"Warm production vision request {i+1}: {time.perf_counter()-start:.3f}s; translation PASS")
    finally:
        request("/local/lease",{"id":lease,"keep":False})
    after = request("/local/models")
    assert after["loaded_model"] is None, "Model did not unload"
    assert after["leases"] == 0, "Lease not released"
    print("PASS: controller loaded, generated twice, unloaded. Verify VRAM via nvidia-smi separately.")

if __name__ == "__main__":
    main()
