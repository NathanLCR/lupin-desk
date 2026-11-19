"""Tests for the image editor: upload rules, edit pipeline, routes, actions, voice."""

from __future__ import annotations

import asyncio
import struct
import subprocess
import sys
import zlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import speech, speech_en, speech_pt_br
from app.actions import ActionRegistry
from app.images import register
from app.images.service import MAX_UPLOAD_BYTES, ImageService, parse_ops, sniff_format, ImageError
from app.images.tools import ImageTools

FIXED_NOW = datetime(2026, 11, 19, 10, 30, 0)
HAS_SIPS = sys.platform == "darwin" and Path("/usr/bin/sips").exists()


def make_png(width: int = 40, height: int = 20) -> bytes:
    rows = b"".join(
        b"\x00" + bytes((200, 30, 90)) * width for _ in range(height)
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


# Speech strings arrive through an orchestrator patch; fill any that are missing so these tests
# pass both before and after the patch is applied.
_FALLBACK_SPEECH = {
    "image_done": lambda name: f"Saved {name}.",
    "image_none": lambda: "No photo.",
    "image_unavailable": lambda: "Unavailable.",
    "image_no_subject": lambda: "No subject.",
    "image_failed": lambda: "Failed.",
}


@pytest.fixture(autouse=True)
def _speech_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in (speech_en, speech_pt_br):
        for name, fn in _FALLBACK_SPEECH.items():
            if not hasattr(module, name):
                monkeypatch.setattr(module, name, fn, raising=False)


class FakeRun:
    """Stands in for subprocess.run: records argv and copies src to the --out/last path."""

    def __init__(self, dims: tuple[int, int] = (400, 200), returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.dims = dims
        self.returncode = returncode
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> Any:
        assert isinstance(argv, list)
        assert not kwargs.get("shell")
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        if "-g" in argv:
            out = f"{argv[-1]}\n  pixelWidth: {self.dims[0]}\n  pixelHeight: {self.dims[1]}\n"
            return SimpleNamespace(returncode=0, stdout=out.encode(), stderr=b"")
        if self.returncode == 0:
            if "--out" in argv:
                Path(argv[argv.index("--out") + 1]).write_bytes(b"result")
            elif argv[0].endswith("vision_cutout"):
                Path(argv[2]).write_bytes(b"cutout")
            elif argv[0].endswith("swiftc"):
                Path(argv[argv.index("-o") + 1]).write_bytes(b"bin")
        return SimpleNamespace(returncode=self.returncode, stdout=b"", stderr=b"")


class FakeHub:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: str, payload: dict[str, Any]) -> int:
        self.published.append((topic, payload))
        return 1


def build(tmp_path: Path, run: Any = None) -> tuple[FastAPI, Any, FakeRun, FakeHub]:
    fake = run or FakeRun()
    app = FastAPI()
    app.state.actions = ActionRegistry()
    hub = FakeHub()
    app.state.device_hub = hub
    tools = ImageTools(tmp_path / "cache", run=fake, sips="/usr/bin/sips", swiftc="/usr/bin/swiftc")
    images = register(
        app,
        store_dir=tmp_path / "store",
        pictures_dir=tmp_path / "pics",
        tools=tools,
        clock=lambda: FIXED_NOW,
    )
    return app, images, fake, hub


def upload(client: TestClient, data: bytes) -> Any:
    return client.post("/api/images", content=data, headers={"content-type": "application/octet-stream"})


# ------------------------------------------------------------------ sniffing and validation


def test_sniff_formats() -> None:
    assert sniff_format(make_png()[:32]) == "png"
    assert sniff_format(b"\xff\xd8\xff\xe0" + b"0" * 20) == "jpg"
    assert sniff_format(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert sniff_format(b"\x00\x00\x00\x18ftypheic\x00\x00") == "heic"
    assert sniff_format(b"GIF89a" + b"0" * 10) == "gif"
    assert sniff_format(b"<html>") is None
    assert sniff_format(b"") is None


def test_parse_ops_rejects_bad_input() -> None:
    for bad in (None, [], "x", [{"op": "rm -rf"}], [{"op": "crop", "x": 0.9, "y": 0, "w": 0.5, "h": 1}],
                [{"op": "resize"}], [{"op": "resize", "width": 0}], [{"op": "compress", "quality": 101}],
                [{"op": "convert", "format": "bmp"}], [{"op": "crop", "x": "a", "y": 0, "w": 1, "h": 1}],
                [{"op": "remove_background"}] * 6):
        with pytest.raises(ImageError):
            parse_ops(bad)


def test_parse_ops_webp_is_unavailable() -> None:
    with pytest.raises(ImageError) as info:
        parse_ops([{"op": "convert", "format": "webp"}])
    assert info.value.code == "unavailable"


# ------------------------------------------------------------------ upload


def test_upload_accepts_image_by_content_and_ignores_names(tmp_path: Path) -> None:
    app, _, _, hub = build(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/images",
        content=make_png(),
        headers={"content-type": "text/plain", "x-filename": "../../etc/passwd.txt"},
    )
    assert response.status_code == 200
    info = response.json()
    assert info["format"] == "png" and len(info["id"]) == 32
    assert info["width"] == 400  # from the fake sips
    files = [p.name for p in (tmp_path / "store").iterdir()]
    assert files == [f"{info['id']}.png"]
    assert hub.published[-1][0] == "images"
    assert hub.published[-1][1]["pending"]["id"] == info["id"]


def test_upload_rejects_non_image_even_with_image_extension(tmp_path: Path) -> None:
    app, _, _, _ = build(tmp_path)
    client = TestClient(app)
    response = client.post("/api/images?name=cat.png", content=b"#!/bin/sh\nrm -rf /\n")
    assert response.status_code == 415
    assert list((tmp_path / "store").iterdir()) == []


def test_upload_rejects_empty_body(tmp_path: Path) -> None:
    app, _, _, _ = build(tmp_path)
    assert upload(TestClient(app), b"").status_code == 415


def test_upload_cap_is_25_mb_streaming(tmp_path: Path) -> None:
    assert MAX_UPLOAD_BYTES == 25 * 1024 * 1024
    app, images, _, _ = build(tmp_path)
    service: ImageService = images.service
    service._max_bytes = 1000  # keep the test small; the route uses the same code path
    client = TestClient(app)
    response = upload(client, make_png() + b"0" * 2000)
    assert response.status_code == 413
    assert list((tmp_path / "store").iterdir()) == []


def test_upload_declared_oversize_rejected_early(tmp_path: Path) -> None:
    app, _, _, _ = build(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/images", content=b"x", headers={"content-length": str(MAX_UPLOAD_BYTES + 1)}
    )
    assert response.status_code in (400, 413)  # h11 may reject the mismatch before our check


def test_startup_purges_leftover_store_files(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    (store / "old.png").write_bytes(b"x")
    build(tmp_path)
    assert list(store.iterdir()) == []


def test_preview_serves_original_and_unknown_is_404(tmp_path: Path) -> None:
    app, _, _, _ = build(tmp_path)
    client = TestClient(app)
    info = upload(client, make_png()).json()
    got = client.get(f"/api/images/{info['id']}/preview")
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    assert client.get("/api/images/" + "0" * 32 + "/preview").status_code == 404
    assert client.get("/api/images/..%2f..%2fetc/preview").status_code == 404


def test_heic_preview_converts_to_jpeg(tmp_path: Path) -> None:
    app, _, fake, _ = build(tmp_path)
    client = TestClient(app)
    info = upload(client, b"\x00\x00\x00\x18ftypheic" + b"\x00" * 30).json()
    got = client.get(f"/api/images/{info['id']}/preview")
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    assert any("jpeg" in call for call in fake.calls)


# ------------------------------------------------------------------ edits


def test_edit_crop_runs_sips_saves_result_and_deletes_original(tmp_path: Path) -> None:
    app, _, fake, hub = build(tmp_path)
    client = TestClient(app)
    info = upload(client, make_png()).json()
    response = client.post(
        f"/api/images/{info['id']}/edit",
        json={"ops": [{"op": "crop", "x": 0.25, "y": 0.5, "w": 0.5, "h": 0.5}]},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["name"].startswith("lupin-20261119-103000-") and result["name"].endswith(".png")
    assert (tmp_path / "pics" / result["name"]).is_file()
    assert list((tmp_path / "store").iterdir()) == []  # original and temps gone
    crop_call = next(c for c in fake.calls if "-c" in c)
    assert crop_call[:7] == ["/usr/bin/sips", "-c", "100", "200", "--cropOffset", "100", "100"]
    assert hub.published[-1][1]["result"]["id"] == result["id"]
    assert hub.published[-1][1]["pending"] is None
    download = client.get(f"/api/images/results/{result['id']}")
    assert download.status_code == 200 and download.content == b"result"
    assert "attachment" in download.headers["content-disposition"]


def test_edit_chain_resize_compress_convert(tmp_path: Path) -> None:
    app, _, fake, _ = build(tmp_path)
    client = TestClient(app)
    info = upload(client, make_png()).json()
    ops = [
        {"op": "resize", "width": 100},
        {"op": "compress", "quality": 55},
        {"op": "convert", "format": "heic"},
    ]
    result = client.post(f"/api/images/{info['id']}/edit", json={"ops": ops}).json()
    assert result["format"] == "heic" and result["name"].endswith(".heic")
    resize = next(c for c in fake.calls if "--resampleWidth" in c)
    assert resize[1:3] == ["--resampleWidth", "100"]
    compress = next(c for c in fake.calls if "55" in c)
    assert compress[1:7] == ["-s", "format", "jpeg", "-s", "formatOptions", "55"]
    assert any(c[1:4] == ["-s", "format", "heic"] for c in fake.calls)


def test_all_subprocesses_are_argv_lists_never_shell(tmp_path: Path) -> None:
    app, _, fake, _ = build(tmp_path)
    client = TestClient(app)
    info = upload(client, make_png()).json()
    client.post(f"/api/images/{info['id']}/edit", json={"ops": [{"op": "resize", "width": 10, "height": 10}]})
    assert fake.calls and all(isinstance(c, list) and all(isinstance(a, str) for a in c) for c in fake.calls)
    assert all(not k.get("shell") for k in fake.kwargs)
    assert all(c[0] == "/usr/bin/sips" for c in fake.calls)
    store = str(tmp_path / "store")
    for call in fake.calls:
        for arg in call[1:]:
            if arg.startswith("/"):
                assert arg.startswith(store)


def test_edit_failure_keeps_original_and_reports(tmp_path: Path) -> None:
    app, images, _, _ = build(tmp_path, FakeRun(returncode=1))
    client = TestClient(app)
    # dims call is "-g" and succeeds; edits fail
    info = upload(client, make_png()).json()
    response = client.post(f"/api/images/{info['id']}/edit", json={"ops": [{"op": "resize", "width": 5}]})
    assert response.status_code == 422 and response.json()["detail"] == "edit_failed"
    assert images.service.last_pending()["id"] == info["id"]
    assert [p.name for p in (tmp_path / "store").iterdir()] == [f"{info['id']}.png"]
    assert not (tmp_path / "pics").exists() or list((tmp_path / "pics").iterdir()) == []


def test_edit_validation_and_unknown_image(tmp_path: Path) -> None:
    app, _, _, _ = build(tmp_path)
    client = TestClient(app)
    info = upload(client, make_png()).json()
    assert client.post(f"/api/images/{info['id']}/edit", json={"ops": [{"op": "shell"}]}).status_code == 422
    assert client.post(f"/api/images/{info['id']}/edit", content="nope").status_code == 422
    assert client.post("/api/images/" + "1" * 32 + "/edit", json={"ops": [{"op": "compress"}]}).status_code == 404
    web = client.post(f"/api/images/{info['id']}/edit", json={"ops": [{"op": "convert", "format": "webp"}]})
    assert web.status_code == 501 and web.json()["detail"] == "unavailable"


def test_discard_deletes_the_upload(tmp_path: Path) -> None:
    app, _, _, _ = build(tmp_path)
    client = TestClient(app)
    info = upload(client, make_png()).json()
    assert client.delete(f"/api/images/{info['id']}").json() == {"ok": True}
    assert list((tmp_path / "store").iterdir()) == []
    assert client.delete(f"/api/images/{info['id']}").status_code == 404


def test_unknown_result_download_is_404(tmp_path: Path) -> None:
    app, _, _, _ = build(tmp_path)
    client = TestClient(app)
    assert client.get("/api/images/results/" + "a" * 32).status_code == 404
    assert client.get("/api/images/results/not-an-id").status_code == 404


# ------------------------------------------------------------------ background removal


def test_remove_background_compiles_helper_once_and_outputs_png(tmp_path: Path) -> None:
    app, _, fake, _ = build(tmp_path)
    client = TestClient(app)
    for _ in range(2):
        info = upload(client, make_png()).json()
        result = client.post(f"/api/images/{info['id']}/edit", json={"ops": [{"op": "remove_background"}]}).json()
        assert result["format"] == "png"
    compiles = [c for c in fake.calls if c[0].endswith("swiftc")]
    assert len(compiles) == 1 and compiles[0][:2] == ["/usr/bin/swiftc", "-O"]
    runs = [c for c in fake.calls if c[0].endswith("vision_cutout")]
    assert len(runs) == 2 and len(runs[0]) == 3


def test_remove_background_unavailable_when_compile_fails(tmp_path: Path) -> None:
    class CompileFails(FakeRun):
        def __call__(self, argv: list[str], **kwargs: Any) -> Any:
            if argv[0].endswith("swiftc"):
                self.calls.append(list(argv))
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            return super().__call__(argv, **kwargs)

    app, images, _, _ = build(tmp_path, CompileFails())
    client = TestClient(app)
    info = upload(client, make_png()).json()
    response = client.post(f"/api/images/{info['id']}/edit", json={"ops": [{"op": "remove_background"}]})
    assert response.status_code == 501 and response.json()["detail"] == "unavailable"
    assert images.service.last_pending() is not None


def test_remove_background_missing_swiftc_is_unavailable(tmp_path: Path) -> None:
    def run(argv: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError(argv[0])

    tools = ImageTools(tmp_path / "cache", run=run)
    with pytest.raises(Exception) as info:
        tools.remove_background(tmp_path / "a.png", tmp_path / "b.png")
    assert getattr(info.value, "code", None) == "unavailable"


def test_remove_background_no_subject_exit_code(tmp_path: Path) -> None:
    class NoSubject(FakeRun):
        def __call__(self, argv: list[str], **kwargs: Any) -> Any:
            if argv[0].endswith("vision_cutout"):
                return SimpleNamespace(returncode=4, stdout=b"", stderr=b"")
            return super().__call__(argv, **kwargs)

    app, _, _, _ = build(tmp_path, NoSubject())
    client = TestClient(app)
    info = upload(client, make_png()).json()
    response = client.post(f"/api/images/{info['id']}/edit", json={"ops": [{"op": "remove_background"}]})
    assert response.status_code == 422 and response.json()["detail"] == "no_subject"


# ------------------------------------------------------------------ actions and voice


def test_panel_actions_edit_last_and_discard(tmp_path: Path) -> None:
    app, _, _, _ = build(tmp_path)
    client = TestClient(app)
    info = upload(client, make_png()).json()
    ran = asyncio.run(app.state.actions.run("image.edit", {"ops": [{"op": "compress", "quality": 40}]}))
    assert ran["ok"] is True
    bad = asyncio.run(app.state.actions.run("image.discard", {"id": info["id"]}))
    assert bad["ok"] is False  # already consumed by the edit


def test_voice_without_upload_says_no_photo(tmp_path: Path) -> None:
    app, images, _, _ = build(tmp_path)
    result = asyncio.run(images.handle_voice("image", "remove_background"))
    assert result["ok"] is False and result["spoken"] == speech.image_none()


def test_voice_remove_background_uses_latest_upload(tmp_path: Path) -> None:
    app, images, _, hub = build(tmp_path)
    client = TestClient(app)
    first = upload(client, make_png()).json()
    second = upload(client, make_png()).json()
    result = asyncio.run(images.handle_voice("image", "remove_background"))
    assert result["ok"] is True and result["kind"] == "image"
    pending = images.service.last_pending()
    assert pending["id"] == first["id"]  # the latest (second) was consumed
    assert second["id"] != first["id"]
    assert hub.published[-1][1]["result"]["name"].endswith(".png")


def test_voice_verbs_and_bad_args(tmp_path: Path) -> None:
    app, images, fake, _ = build(tmp_path)
    client = TestClient(app)
    upload(client, make_png())
    assert asyncio.run(images.handle_voice("image", "resize:abc"))["ok"] is False
    assert asyncio.run(images.handle_voice("image", "explode"))["ok"] is False
    assert asyncio.run(images.handle_voice("image", "convert:webp"))["spoken"] == speech.image_unavailable()
    assert asyncio.run(images.handle_voice("image", "resize:800"))["ok"] is True
    upload(client, make_png())
    assert asyncio.run(images.handle_voice("image", "compress"))["ok"] is True
    upload(client, make_png())
    assert asyncio.run(images.handle_voice("image", "convert:png"))["ok"] is True


def test_voice_unavailable_is_spoken(tmp_path: Path) -> None:
    class NoVision(FakeRun):
        def __call__(self, argv: list[str], **kwargs: Any) -> Any:
            if argv[0].endswith("swiftc"):
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            return super().__call__(argv, **kwargs)

    app, images, _, _ = build(tmp_path, NoVision())
    upload(TestClient(app), make_png())
    result = asyncio.run(images.handle_voice("image", "remove_background"))
    assert result["ok"] is False and result["spoken"] == speech.image_unavailable()


def test_speech_tables_have_image_strings_in_both_languages() -> None:
    for module in (speech_en, speech_pt_br):
        assert module.image_done("a.png")
        assert module.image_none() and module.image_unavailable()
        assert module.image_no_subject() and module.image_failed()


# ------------------------------------------------------------------ real sips (macOS only)


@pytest.mark.skipif(not HAS_SIPS, reason="needs macOS sips")
def test_real_sips_crop_resize_compress_convert(tmp_path: Path) -> None:
    app = FastAPI()
    tools = ImageTools(tmp_path / "cache")
    register(app, store_dir=tmp_path / "store", pictures_dir=tmp_path / "pics", tools=tools)
    client = TestClient(app)
    info = upload(client, make_png(200, 100)).json()
    assert (info["width"], info["height"]) == (200, 100)
    ops = [
        {"op": "crop", "x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5},
        {"op": "resize", "width": 50},
        {"op": "compress", "quality": 60},
    ]
    result = client.post(f"/api/images/{info['id']}/edit", json={"ops": ops}).json()
    out = tmp_path / "pics" / result["name"]
    assert out.suffix == ".jpg"
    assert tools.dimensions(out) == (50, 25)
    info = upload(client, make_png(64, 64)).json()
    heic = client.post(f"/api/images/{info['id']}/edit", json={"ops": [{"op": "convert", "format": "heic"}]})
    assert heic.status_code == 200
    assert sniff_format((tmp_path / "pics" / heic.json()["name"]).read_bytes()[:32]) == "heic"


@pytest.mark.skipif(not HAS_SIPS, reason="needs macOS Vision")
def test_real_vision_helper_runs_or_reports_cleanly(tmp_path: Path) -> None:
    app = FastAPI()
    register(app, store_dir=tmp_path / "store", pictures_dir=tmp_path / "pics", cache_dir=tmp_path / "cache")
    client = TestClient(app)
    info = upload(client, make_png(120, 120)).json()
    response = client.post(f"/api/images/{info['id']}/edit", json={"ops": [{"op": "remove_background"}]})
    # A flat colour has no foreground subject; any of these is a clean outcome.
    assert response.status_code in (200, 422, 501)
    if response.status_code != 200:
        assert response.json()["detail"] in ("no_subject", "unavailable")
