"""End-to-end: run the node against a real MarkLayer server and inspect the file it saved.

ComfyUI itself isn't needed: we stub its `folder_paths` module. The server is the MarkLayer API
started locally (set MARKLAYER_REPO to its checkout; defaults to ../MarkLayer).

    python -m pytest tests
"""
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import time
import types
import urllib.request
from pathlib import Path

import pytest
import torch
from PIL import Image

NODE_DIR = Path(__file__).resolve().parent.parent
REPO = Path(os.environ.get("MARKLAYER_REPO", NODE_DIR.parent / "MarkLayer"))
SECRET_KEY = "test-key-must-not-leak-1234567890"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server():
    if not (REPO / "app" / "main.py").exists():
        pytest.skip(f"MarkLayer API checkout not found at {REPO}")
    port = _free_port()
    python = REPO / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = REPO / ".venv" / "bin" / "python"
    env = {**os.environ, "RAPIDAPI_PROXY_SECRET": "", "MAX_MEGAPIXELS": "1.0", "PYTHONUTF8": "1"}
    proc = subprocess.Popen([str(python), "-m", "uvicorn", "app.main:app", "--port", str(port)],
                            cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            urllib.request.urlopen(f"{url}/health", timeout=1)
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("MarkLayer server did not start")
    yield url
    proc.kill()


@pytest.fixture
def node_mod(tmp_path, monkeypatch, server):
    """Import the custom node as ComfyUI would, with a stub folder_paths."""
    fp = types.ModuleType("folder_paths")
    fp.get_output_directory = lambda: str(tmp_path)

    def get_save_image_path(prefix, output_dir, w=0, h=0):
        return output_dir, prefix, 1, "", prefix

    fp.get_save_image_path = get_save_image_path
    monkeypatch.setitem(sys.modules, "folder_paths", fp)
    monkeypatch.setenv("MARKLAYER_API_URL", server)
    monkeypatch.setenv("MARKLAYER_API_KEY", SECRET_KEY)  # sent as a header, ignored by the local server

    for name in [n for n in sys.modules if n.startswith("comfyui_marklayer")]:
        monkeypatch.delitem(sys.modules, name)  # fresh import, bound to this test's folder_paths stub
    spec = importlib.util.spec_from_file_location("comfyui_marklayer", NODE_DIR / "__init__.py",
                                                  submodule_search_locations=[str(NODE_DIR)])
    pkg = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "comfyui_marklayer", pkg)
    spec.loader.exec_module(pkg)
    return sys.modules["comfyui_marklayer.nodes"]


def photo_batch(n: int = 2, size=(640, 427)) -> torch.Tensor:
    src = Image.open(REPO / "tests" / "samples" / "photo.jpg").convert("RGB").resize(size)
    t = torch.from_numpy(__import__("numpy").asarray(src).astype("float32") / 255.0)
    return torch.stack([t] * n)


def inspect(server: str, data: bytes) -> dict:
    boundary = "xyz"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"f\"\r\n\r\n".encode()
            + data + f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"{server}/v1/inspect", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(urllib.request.urlopen(req).read())


def test_saves_marked_png_with_workflow(node_mod, server, tmp_path):
    node = node_mod.MarkLayerSaveImage()
    prompt = {"3": {"class_type": "KSampler", "inputs": {"seed": 1}}}
    out = node.save(photo_batch(2), "test", "ai_generated", "My Flux App", "png", 92,
                    prompt=prompt, extra_pnginfo={"workflow": {"nodes": []}})

    files = [tmp_path / r["filename"] for r in out["ui"]["images"]]
    assert [f.name for f in files] == ["test_00001_.png", "test_00002_.png"]
    assert out["result"][0].shape == (2, 427, 640, 3)

    data = files[0].read_bytes()
    j = inspect(server, data)
    assert j["verdict"] == "ai_generated"
    assert j["c2pa"]["valid"] and j["c2pa"]["software_agents"] == ["My Flux App"]
    assert j["watermark"]["detected"] and j["iptc"]["digital_source_type"]
    assert {"name": "ComfyUI", "source": "png:prompt/workflow"} in j["generators"]  # workflow kept
    assert SECRET_KEY.encode() not in data  # the API key never ends up in the image


def test_jpeg_ai_edited(node_mod, server, tmp_path):
    out = node_mod.MarkLayerSaveImage().save(photo_batch(1), "edit", "ai_edited", "", "jpeg", 90)
    data = (tmp_path / out["ui"]["images"][0]["filename"]).read_bytes()
    assert data[:3] == b"\xff\xd8\xff"
    j = inspect(server, data)
    assert j["verdict"] == "ai_edited" and j["watermark"]["declares"] == "ai_edited"


def test_api_errors_stop_the_workflow(node_mod, tmp_path):
    with pytest.raises(RuntimeError, match="413.*limit"):  # server started with a 1 MP cap
        node_mod.MarkLayerSaveImage().save(photo_batch(1, size=(1600, 1067)), "big")
    assert not list(tmp_path.iterdir())  # nothing unmarked was written


def test_missing_key_message(node_mod, monkeypatch):
    client = sys.modules["comfyui_marklayer.client"]
    monkeypatch.delenv("MARKLAYER_API_KEY")
    monkeypatch.delenv("MARKLAYER_API_URL")
    monkeypatch.setattr(client, "CONFIG_FILE", Path("does-not-exist.json"))
    with pytest.raises(RuntimeError, match="No MarkLayer API key"):
        node_mod.MarkLayerSaveImage().save(photo_batch(1), "nokey")


def test_widgets_have_no_key_field(node_mod):
    inputs = node_mod.MarkLayerSaveImage.INPUT_TYPES()["required"]
    assert not any("key" in name.lower() for name in inputs)
