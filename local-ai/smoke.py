"""Live CUDA smoke/benchmark. Creates a synthetic image entirely in RAM."""
import base64
import io
import json
import time
import uuid
import urllib.request
from PIL import Image, ImageDraw

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
    image = Image.new("RGB",(480,160),"white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((10,10,470,150),outline="black",width=3)
    draw.text((150,70),"HELLO WORLD",fill="black")
    buf = io.BytesIO()
    image.save(buf,format="PNG")
    data = "data:image/png;base64,"+base64.b64encode(buf.getvalue()).decode()
    try:
        start = time.perf_counter()
        request("/local/lease",{"id":lease,"model":MODEL,"keep":True})
        print(f"Initial model load: {time.perf_counter()-start:.3f}s")
        for i in range(2):
            start=time.perf_counter()
            result=request("/v1/chat/completions",{"model":MODEL,"temperature":0,"max_tokens":80,
                "messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":data}},
                {"type":"text","text":"Read the English text in the image and translate it into Spanish."}]}]})
            answer=result["choices"][0]["message"]["content"]
            assert answer.strip(), "Empty inference result"
            print(f"Warm inference {i+1}: {time.perf_counter()-start:.3f}s; synthetic answer: {answer[:120]}")
    finally:
        request("/local/lease",{"id":lease,"keep":False})
    after = request("/local/models")
    assert after["loaded_model"] is None, "Model did not unload"
    assert after["leases"] == 0, "Lease not released"
    print("PASS: controller loaded, generated twice, unloaded. Verify VRAM via nvidia-smi separately.")

if __name__ == "__main__":
    main()
