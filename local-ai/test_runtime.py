"""Live Windows fault checks; release browser/GUI pins first. No images are used."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

import psutil

REPO = Path(__file__).resolve().parents[1]
MODEL = "qwen3-vl-4b"
ROOT = "http://127.0.0.1:7678"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path, body=None, expected=200):
    req = urllib.request.Request(ROOT + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Manga-Local": "1", "Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=150) as response:
            assert response.status == expected
            return json.load(response)
    except urllib.error.HTTPError as error:
        assert error.code == expected, (path, error.code, expected)
        return json.load(error)


def lease(identity, keep=True, model=MODEL, expected=200):
    return request("/local/lease", {"id": identity, "model": model, "keep": keep}, expected)


def main():
    state = request("/local/models")
    assert state["leases"] == 0 and state["loaded_model"] is None, "Release all pins first"
    first, second = ["gui:" + str(uuid.uuid4()) for _ in range(2)]
    try:
        lease(first, model="not-installed", expected=404)
        request("/local/remove", {"id": "../invalid"}, 400)
        lease(first)
        lease(second)
        lease("gui:" + str(uuid.uuid4()), model="competing-model", expected=409)
        request("/local/remove", {"id": MODEL}, 409)
        lease(first, False)
        assert request("/local/models")["loaded_model"] == MODEL
        engine = (REPO / "local-ai/runtime/llama-server.exe").resolve()
        workers = [p for p in psutil.process_iter(["exe"])
                   if p.info["exe"] and Path(p.info["exe"]).resolve() == engine]
        assert len(workers) == 1, "Expected exactly one test worker"
        workers[0].kill()
        workers[0].wait(timeout=10)
        lease(second)
        assert request("/local/models")["loaded_model"] == MODEL
        print("PASS: competing model, loaded removal refusal, two pins and worker crash/reload", flush=True)
    finally:
        lease(first, False)
        lease(second, False)
    assert request("/local/models")["loaded_model"] is None

    library = REPO / "local-ai/runtime/ggml-cuda.dll"
    disabled = library.with_suffix(".dll.acceptance-disabled")
    assert library.is_file() and not disabled.exists()
    library.rename(disabled)
    try:
        start = time.monotonic()
        lease(first, expected=503)
        assert request("/local/models")["loaded_model"] is None
        print("PASS: missing CUDA library failed without residency in %.3fs" % (time.monotonic() - start), flush=True)
    finally:
        disabled.rename(library)

    identity = "synthetic-invalid-" + uuid.uuid4().hex
    directory = REPO / "local-ai/models" / identity
    directory.mkdir()
    for name in ("weights.gguf", "mmproj.gguf"):
        (directory / name).write_bytes(b"GGUFsynthetic-invalid-model")
    (directory / "model.json").write_text(json.dumps({"id": identity, "label": identity,
        "repo": "synthetic/invalid", "revision": "synthetic", "weights": "weights.gguf",
        "projector": "mmproj.gguf"}), encoding="utf-8")
    try:
        lease(first, model=identity, expected=503)
        assert request("/local/models")["loaded_model"] is None
    finally:
        request("/local/remove", {"id": identity})
    assert not directory.exists()
    lease(first)
    lease(first, False)
    print("PASS: corrupt model load, inactive model removal and restored CUDA load/release", flush=True)


if __name__ == "__main__":
    main()
