"""Live synthetic-page acceptance. All fixtures and returned images remain in RAM."""
import base64
import io
import json
from pathlib import Path
import sys
import time
import urllib.request
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
from api_schemas import TranslateRequest
from pipeline.wrapper import _build_config, translate_image_base64


def fixture(language, colored=False, outside=False):
    fonts = {"Japanese": "C:/Windows/Fonts/msgothic.ttc", "Korean": "C:/Windows/Fonts/malgun.ttf",
        "Chinese": str(REPO / "backend/fonts/Noto Sans SC/NotoSansSC-Regular.ttf"),
        "English": "C:/Windows/Fonts/arial.ttf", "Blank": "C:/Windows/Fonts/arial.ttf"}
    words = {"Japanese": ["こんにちは", "ありがとう"], "Korean": ["안녕하세요", "감사합니다"],
        "Chinese": ["你好", "谢谢"], "English": ["HELLO WORLD", "THANK YOU"], "Blank": []}
    image = Image.new("RGB", (800, 900), "#999999")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(fonts[language], 40)
    for (x, y), word in zip([(430, 40), (50, 470)], words[language]):
        draw.ellipse((x, y, x+280, y+380), fill="#fff2bb" if colored else "white", outline="black", width=3)
        lines = word.split() if language == "English" else word
        for index, line in enumerate(lines):
            draw.text((x+30, y+120+index*50) if language == "English" else (x+120, y+70+index*40), line, font=font, fill="black")
    if outside:
        draw.text((380, 440), "助けて", font=font, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return image, base64.b64encode(buffer.getvalue()).decode("ascii")


def serve():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlsplit
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            uri = urlsplit(self.path)
            query = parse_qs(uri.query)
            language = query.get("lang", ["Japanese"])[0]
            mode = query.get("mode", [""])[0]
            if language not in ("Japanese", "Korean", "Chinese", "English", "Blank") or mode not in ("", "colored", "outside"):
                self.send_error(400)
                return
            if uri.path == "/image.png":
                _, data = fixture(language, colored=mode == "colored", outside=mode == "outside")
                body, kind = base64.b64decode(data), "image/png"
            else:
                body = ('<!doctype html><title>Synthetic reader</title><style>body{background:#333}img{display:block;margin:auto;width:600px}</style><img src="/image.png?lang=' + language + '&mode=' + mode + '">').encode()
                kind = "text/html"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print("RAM fixture server: http://127.0.0.1:%d" % server.server_port, flush=True)
    server.serve_forever()


def main():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for language in ("Japanese", "Korean", "Chinese", "English", "Blank"):
        image, data = fixture(language)
        start = time.monotonic()
        req = urllib.request.Request("http://127.0.0.1:7677/translate",
            data=json.dumps({"image": data, "provider": "Local", "input_language": "Auto",
                "output_language": "English", "supersampling_factor": 1}).encode(),
            headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=180) as response:
            result = json.load(response)
        assert result["source_language"] == ("Unknown" if language == "Blank" else language)
        bubbles = result["bubbles"]
        assert len(bubbles) == (0 if language == "Blank" else 2)
        if bubbles:
            assert "hello" in bubbles[0]["translated_text"].casefold()
            assert "thank" in bubbles[1]["translated_text"].casefold()
            assert bubbles[0]["bbox"][1] < bubbles[1]["bbox"][1], "Reading order changed"
        else:
            returned = Image.open(io.BytesIO(base64.b64decode(result["translated_image"]))).convert("RGB")
            assert ImageChops.difference(image, returned).getbbox() is None, "Blank page changed"
        print("PASS: %s Auto source, crops/order/translation/blank check; %.3fs" % (language, time.monotonic()-start), flush=True)

    import cv2
    violations = []
    save = Image.Image.save
    def ram_save(image, destination, *args, **kwargs):
        if not isinstance(destination, io.BytesIO):
            violations.append("PIL file output")
            raise AssertionError("Image file output attempted")
        return save(image, destination, *args, **kwargs)
    def no_imwrite(*args, **kwargs):
        violations.append("OpenCV file output")
        raise AssertionError("Image file output attempted")
    with patch.object(Image.Image, "save", ram_save), patch.object(cv2, "imwrite", no_imwrite):
        for mode in ("colored", "outside", "upscale"):
            _, data = fixture("Japanese", colored=mode == "colored", outside=mode == "outside")
            request = TranslateRequest(image=data, provider="Local", input_language="Japanese",
                output_language="English", supersampling_factor=1, outside_text_enabled=mode == "outside")
            options = request.model_dump(exclude={"image"})
            config = _build_config(**options, models_dir=REPO / "backend/models", fonts_base_dir=REPO / "backend/fonts")
            config.cleaning.inpaint_colored_bubbles = mode == "colored"
            config.output.upscale_final_image = mode == "upscale"
            start = time.monotonic()
            result, bubbles, _ = translate_image_base64(data, config)
            assert len(bubbles) >= 2, "Missing crops in " + mode
            assert any("hello" in b["translation"].casefold() for b in bubbles)
            assert any("thank" in b["translation"].casefold() for b in bubbles)
            if mode == "outside":
                assert len(bubbles) >= 3 and any("help" in b["translation"].casefold() for b in bubbles), "Outside text was not translated"
            if mode == "upscale":
                assert result.width > 800 and result.height > 900, "Upscale did not run"
            assert not violations, violations
            from core.caching import get_cache
            assert not any(get_cache().get_cache_stats().values()), "Page image caches were retained"
            print("PASS: %s pipeline with PIL/OpenCV file writes trapped; %.3fs" % (mode, time.monotonic()-start), flush=True)


if __name__ == "__main__":
    serve() if sys.argv[1:] == ["--serve"] else main()
