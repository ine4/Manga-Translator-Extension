"""Live Windows cleanup check. Stop the stack first; never sends an image."""
import json
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
import urllib.request


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main():
    if sys.platform != "win32":
        raise RuntimeError("This test requires Windows")
    if listening(7678) or listening(7679):
        raise RuntimeError("Stop the stack and any inference worker before this test")
    root = Path(__file__).resolve().parents[1]
    controller = subprocess.Popen([str(root / "local-ai/target/release/manga-local.exe")], cwd=root)
    try:
        deadline = time.monotonic() + 10
        while not listening(7678):
            if controller.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Controller did not become ready")
            time.sleep(0.1)
        body = {"id": "gui:" + str(uuid.uuid4()), "model": "qwen3-vl-4b", "keep": True}
        req = urllib.request.Request("http://127.0.0.1:7678/local/lease",
            data=json.dumps(body).encode(),
            headers={"X-Manga-Local": "1", "Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=150) as response:
            assert json.load(response)["loaded_model"] == body["model"]
        assert listening(7679), "Worker was not listening after load"
        controller.kill()
        controller.wait(timeout=10)
        deadline = time.monotonic() + 10
        while listening(7679) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not listening(7679), "Worker survived forced controller termination"
        print("PASS: forced controller termination closed the owned worker port")
    finally:
        if controller.poll() is None:
            controller.kill()
            controller.wait(timeout=10)


if __name__ == "__main__":
    main()
