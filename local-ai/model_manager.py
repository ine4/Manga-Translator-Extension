"""Download only explicit GGUF files with the official huggingface_hub client."""
import argparse
import json
import os
from pathlib import Path
import re
import urllib.request
import urllib.parse

ROOT = Path(os.environ.get("MANGA_LOCAL_MODELS", Path(__file__).parent / "models")).resolve()
DEFAULT = json.loads((Path(__file__).parent / "default-model.json").read_text(encoding="utf-8"))
ID = re.compile(r"[a-zA-Z0-9_-]{1,80}\Z")
FILE = re.compile(r"[a-zA-Z0-9_-][a-zA-Z0-9_.-]*\.gguf\Z")
REPO = re.compile(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+\Z")

def repo_id(value):
    value = value.strip()
    if "://" in value:
        uri = urllib.parse.urlsplit(value)
        if uri.scheme != "https" or uri.netloc.lower() != "huggingface.co":
            raise ValueError("Use a Hugging Face model repository URL")
        value = "/".join(uri.path.strip("/").split("/")[:2])
    if not REPO.fullmatch(value) or any(x in (".", "..") for x in value.split("/")):
        raise ValueError("Invalid model repository")
    return value

def require_safe(model):
    if not ID.fullmatch(model["id"]) or not FILE.fullmatch(model["weights"]) or not FILE.fullmatch(model["projector"]):
        raise ValueError("Use simple model IDs and GGUF filenames; no nested paths")
    if model["weights"] == model["projector"]:
        raise ValueError("Select separate model weights and vision projector")

def gguf(path):
    with path.open("rb") as f:
        return f.read(4) == b"GGUF"

def install(model):
    from huggingface_hub import HfApi, hf_hub_download
    model = dict(model)
    require_safe(model)
    model["repo"] = repo_id(model["repo"])
    dest = ROOT / model["id"]
    if dest.is_symlink():
        raise ValueError("Model directory must not be a symlink")
    dest.mkdir(parents=True, exist_ok=True)
    descriptor = dest / "model.json"
    if descriptor.exists():
        old = json.loads(descriptor.read_text(encoding="utf-8"))
        # Do not overwrite an existing model which could be in use.
        if old["repo"] == model["repo"] and old["weights"] == model["weights"] and old["projector"] == model["projector"] and all((dest / old[k]).is_file() and gguf(dest / old[k]) for k in ("weights", "projector")):
            print("Already installed:", model["id"])
            return
        raise ValueError("Remove the existing model before replacing it")
    info = HfApi().model_info(model["repo"], revision=model["revision"])
    model["revision"] = info.sha
    for key in ("weights", "projector"):
        name = model[key]
        print("Downloading", name, flush=True)
        path = Path(hf_hub_download(repo_id=model["repo"], filename=name,
                                   revision=model["revision"], local_dir=str(dest)))
        if not gguf(path):
            raise ValueError("Downloaded file is not GGUF")
    temp = descriptor.with_suffix(".tmp")
    temp.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    temp.replace(descriptor)
    print("Installed", model["id"], flush=True)

def list_files(repo):
    from huggingface_hub import HfApi
    files = HfApi().list_repo_files(repo_id(repo))
    print(json.dumps([f for f in files if FILE.fullmatch(f)]))

def remove(model_id):
    if not ID.fullmatch(model_id):
        raise ValueError("Invalid model ID")
    req = urllib.request.Request("http://127.0.0.1:7678/local/remove",
                                 data=json.dumps({"id": model_id}).encode(),
                                 headers={"Content-Type":"application/json","X-Manga-Local":"1"},
                                 method="POST")
    # No proxy and no external URLs for controller requests.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=30) as r:
        if not json.load(r).get("ok"):
            raise RuntimeError("Controller refused removal")
    print("Removed", model_id)

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install-default")
    files = sub.add_parser("files")
    files.add_argument("repo")
    add = sub.add_parser("install")
    for field in ("id", "repo", "weights", "projector"):
        add.add_argument(field)
    delete = sub.add_parser("remove")
    delete.add_argument("id")
    args = parser.parse_args()
    if args.command == "install-default":
        install(DEFAULT)
    elif args.command == "files":
        list_files(args.repo)
    elif args.command == "remove":
        remove(args.id)
    else:
        install({"id":args.id,"label":args.id,"repo":repo_id(args.repo),"revision":"main",
                 "weights":args.weights,"projector":args.projector})

if __name__ == "__main__":
    main()
