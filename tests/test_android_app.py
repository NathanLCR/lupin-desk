"""Testes para o projeto Android nativo do Desk Assistant e script de build do APK."""

from __future__ import annotations

import ast
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_android_apk

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

MANIFEST_PATH = ROOT / "android" / "AndroidManifest.xml"
STRINGS_PATH = ROOT / "android" / "res" / "values" / "strings.xml"
STYLES_PATH = ROOT / "android" / "res" / "values" / "styles.xml"
ICON_PATH = ROOT / "android" / "res" / "drawable" / "ic_launcher.xml"
MAIN_ACTIVITY_PATH = (
    ROOT / "android" / "src" / "com" / "nathanlucio" / "deskassistant" / "MainActivity.java"
)
BUILD_SCRIPT_PATH = ROOT / "scripts" / "build_android_apk.py"
GITIGNORE_PATH = ROOT / ".gitignore"


def test_gitignore_preserves_rules_and_ignores_android_artifacts() -> None:
    """Garante que `.gitignore` mantém as regras base e ignora `dist/` e `android/build/`."""
    lines = {line.strip() for line in GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()}
    expected = {
        ".env",
        ".venv/",
        "certs/",
        "data/*.db",
        "data/*.db-shm",
        "data/*.db-wal",
        "dist/",
        "android/build/",
    }
    assert expected.issubset(lines)


def test_android_manifest_structure() -> None:
    """Valida pacote, SDK, permissões, features e activity do AndroidManifest.xml."""
    tree = ET.parse(MANIFEST_PATH)
    root = tree.getroot()

    assert root.tag == "manifest"
    assert root.attrib["package"] == "com.nathanlucio.deskassistant"
    assert root.attrib[f"{ANDROID_NS}versionCode"] == "1"
    assert root.attrib[f"{ANDROID_NS}versionName"] == "1.0"

    uses_sdk = root.find("uses-sdk")
    assert uses_sdk is not None
    assert uses_sdk.attrib[f"{ANDROID_NS}minSdkVersion"] == "26"
    assert uses_sdk.attrib[f"{ANDROID_NS}targetSdkVersion"] == "34"

    perms = {el.attrib[f"{ANDROID_NS}name"] for el in root.findall("uses-permission")}
    assert perms == {
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.RECORD_AUDIO",
        "android.permission.MODIFY_AUDIO_SETTINGS",
        "android.permission.VIBRATE",
        "android.permission.WAKE_LOCK",
    }

    features = {
        el.attrib[f"{ANDROID_NS}name"]: el.attrib[f"{ANDROID_NS}required"]
        for el in root.findall("uses-feature")
    }
    assert features["android.hardware.microphone"] == "false"
    assert features["android.hardware.gamepad"] == "false"

    app = root.find("application")
    assert app is not None
    assert app.attrib[f"{ANDROID_NS}label"] == "@string/app_name"
    assert app.attrib[f"{ANDROID_NS}icon"] == "@drawable/ic_launcher"
    assert app.attrib[f"{ANDROID_NS}theme"] == "@style/AppTheme"
    assert app.attrib[f"{ANDROID_NS}usesCleartextTraffic"] == "true"
    assert app.attrib[f"{ANDROID_NS}hardwareAccelerated"] == "true"

    activity = app.find("activity")
    assert activity is not None
    assert activity.attrib[f"{ANDROID_NS}name"] == ".MainActivity"
    assert activity.attrib[f"{ANDROID_NS}exported"] == "true"
    assert activity.attrib[f"{ANDROID_NS}screenOrientation"] == "sensorLandscape"
    assert activity.attrib[f"{ANDROID_NS}launchMode"] == "singleTask"
    config_changes = set(activity.attrib[f"{ANDROID_NS}configChanges"].split("|"))
    assert {
        "orientation",
        "screenSize",
        "screenLayout",
        "keyboard",
        "keyboardHidden",
        "navigation",
    }.issubset(config_changes)

    intent_filter = activity.find("intent-filter")
    assert intent_filter is not None
    actions = {el.attrib[f"{ANDROID_NS}name"] for el in intent_filter.findall("action")}
    categories = {el.attrib[f"{ANDROID_NS}name"] for el in intent_filter.findall("category")}
    assert "android.intent.action.MAIN" in actions
    assert "android.intent.category.LAUNCHER" in categories


def test_android_resources_xml() -> None:
    """Valida strings.xml, styles.xml e ícone vetorial ic_launcher.xml."""
    strings_root = ET.parse(STRINGS_PATH).getroot()
    strings_map = {el.attrib["name"]: el.text for el in strings_root.findall("string")}
    assert strings_map["app_name"] == "Desk Assistant"

    styles_root = ET.parse(STYLES_PATH).getroot()
    style_el = styles_root.find("style")
    assert style_el is not None
    assert style_el.attrib["name"] == "AppTheme"
    assert style_el.attrib["parent"] == "@android:style/Theme.Black.NoTitleBar.Fullscreen"
    style_items = {el.attrib["name"]: el.text for el in style_el.findall("item")}
    assert style_items.get("android:colorBackground") == "#000000"

    icon_root = ET.parse(ICON_PATH).getroot()
    assert icon_root.tag == "vector"
    fill_colors = {
        (el.attrib.get(f"{ANDROID_NS}fillColor") or "").upper()
        for el in icon_root.findall("path")
    }
    assert "#000000" in fill_colors
    assert "#00F0FF" in fill_colors


def test_main_activity_requirements_and_ssl_guard() -> None:
    """Valida API pura Android SDK, WebView, ponte JS e checagem estrita de SSL local."""
    source = MAIN_ACTIVITY_PATH.read_text(encoding="utf-8")

    imports = re.findall(r"^\s*import\s+([^;]+);", source, flags=re.MULTILINE)
    assert imports, "MainActivity.java precisa declarar imports"
    for imp in imports:
        assert imp.startswith(("android.", "java.")), f"Import não permitido fora do SDK: {imp}"

    required_tokens = [
        "FLAG_KEEP_SCREEN_ON",
        "SYSTEM_UI_FLAG_IMMERSIVE_STICKY",
        "WindowInsetsController",
        "Manifest.permission.RECORD_AUDIO",
        "setJavaScriptEnabled(true)",
        "setDomStorageEnabled(true)",
        "setDatabaseEnabled(true)",
        "setMediaPlaybackRequiresUserGesture(false)",
        "setUseWideViewPort(true)",
        "setLoadWithOverviewMode(true)",
        "MIXED_CONTENT_COMPATIBILITY_MODE",
        "http://localhost:8000",
        "https://192.168.0.125:8443",
        "PermissionRequest.RESOURCE_AUDIO_CAPTURE",
        "addJavascriptInterface",
        '"AndroidBridge"',
        "dispatchKeyEvent",
    ]
    for token in required_tokens:
        assert token in source, f"Elemento obrigatório ausente em MainActivity.java: {token}"

    for method in (
        "isNativeApp()",
        "vibrate(int ms)",
        "getServerUrl()",
        "setServerUrl(String url)",
        "reloadApp()",
        "openServerMenu()",
    ):
        assert method in source, f"Método ausente no AndroidBridge: {method}"

    ssl_block_match = re.search(
        r"public void onReceivedSslError\s*\([^)]*\)\s*\{(.*?)\n\s{8}\}",
        source,
        flags=re.DOTALL,
    )
    assert ssl_block_match is not None, "onReceivedSslError não encontrado"
    ssl_block = ssl_block_match.group(1)
    assert "isPrivateOrLocalHost(" in ssl_block
    assert "handler.proceed();" in ssl_block
    assert "handler.cancel();" in ssl_block
    # Nunca permite `handler.proceed()` fora de condicional estrita
    assert source.count("handler.proceed()") == 1


def test_build_script_uses_no_shell_true_and_discovers_mocked_toolchain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Garante que o script de build nunca usa shell=True e descobre o toolchain."""
    build_src = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(build_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            assert isinstance(node.value, ast.Constant) and node.value.value is False

    fake_jdk = tmp_path / "jdk"
    (fake_jdk / "bin").mkdir(parents=True)
    for tool in ("javac", "keytool"):
        (fake_jdk / "bin" / tool).write_text("#!/bin/sh\n", encoding="utf-8")

    fake_sdk = tmp_path / "sdk"
    (fake_sdk / "platforms" / "android-34").mkdir(parents=True)
    (fake_sdk / "platforms" / "android-34" / "android.jar").write_bytes(b"jar")
    bt_dir = fake_sdk / "build-tools" / "34.0.0"
    bt_dir.mkdir(parents=True)
    for tool in ("aapt2", "d8", "zipalign", "apksigner"):
        (bt_dir / tool).write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setenv("JAVA_HOME", str(fake_jdk))
    monkeypatch.setenv("ANDROID_HOME", str(fake_sdk))

    toolchain = build_android_apk.discover_toolchain()
    assert toolchain.java_home == fake_jdk
    assert toolchain.sdk_root == fake_sdk
    assert toolchain.platform_name == "android-34"
    assert toolchain.build_tools_dir == bt_dir


def test_real_apk_build_when_toolchain_installed() -> None:
    """Compila e valida `dist/desk-assistant-rg406h.apk` quando JDK e SDK 34 estão prontos."""
    try:
        toolchain = build_android_apk.discover_toolchain()
    except RuntimeError as exc:
        pytest.skip(f"Toolchain Android ainda não disponível neste host: {exc}")

    apk_path = build_android_apk.build_apk(toolchain=toolchain)
    assert apk_path.is_file()
    assert apk_path == ROOT / "dist" / "desk-assistant-rg406h.apk"
    assert apk_path.stat().st_size > 4096

    with zipfile.ZipFile(apk_path, "r") as zf:
        names = set(zf.namelist())
    assert {"AndroidManifest.xml", "classes.dex", "resources.arsc"}.issubset(names)
