"""Build and sign the native Desk Assistant APK for the Anbernic RG406H."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ANDROID_DIR = BASE_DIR / "android"
MANIFEST_PATH = ANDROID_DIR / "AndroidManifest.xml"
RES_DIR = ANDROID_DIR / "res"
SRC_DIR = ANDROID_DIR / "src"
BUILD_DIR = ANDROID_DIR / "build"
DIST_DIR = BASE_DIR / "dist"
FINAL_APK_PATH = DIST_DIR / "desk-assistant-rg406h.apk"
DEBUG_KEYSTORE_PATH = BASE_DIR / "certs" / "debug.keystore"


@dataclass(frozen=True)
class AndroidToolchain:
    """Resolved paths of the JDK and Android SDK required for the build."""

    java_home: Path
    javac_bin: Path
    keytool_bin: Path
    sdk_root: Path
    android_jar: Path
    platform_name: str
    build_tools_dir: Path
    aapt2_bin: Path
    d8_bin: Path
    zipalign_bin: Path
    apksigner_bin: Path


def _version_sort_key(name: str) -> tuple[int, ...]:
    """Extract numeric components to sort versions (e.g. 34.0.0 > 33.0.2)."""
    nums = re.findall(r"\d+", name)
    return tuple(int(n) for n in nums) if nums else (0,)


def _is_valid_java_home(candidate: Path) -> bool:
    """Check that the directory has a working javac and keytool."""
    return (candidate / "bin" / "javac").is_file() and (candidate / "bin" / "keytool").is_file()


def find_java_home() -> Path | None:
    """Locate a JDK (preferably OpenJDK 17) installed on macOS."""
    candidates: list[Path] = []
    env_java = os.environ.get("JAVA_HOME")
    if env_java:
        candidates.append(Path(env_java))

    candidates.extend(
        [
            Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
            Path("/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
            Path("/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
            Path("/usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
        ]
    )

    jvm_root = Path("/Library/Java/JavaVirtualMachines")
    if jvm_root.is_dir():
        jvm_homes = sorted(
            (p / "Contents" / "Home" for p in jvm_root.iterdir() if p.is_dir()),
            key=lambda p: _version_sort_key(p.parent.parent.name),
            reverse=True,
        )
        candidates.extend(jvm_homes)

    for candidate in candidates:
        if _is_valid_java_home(candidate):
            return candidate
    return None


def find_android_sdk() -> Path | None:
    """Locate the Android SDK root directory."""
    candidates: list[Path] = []
    for env_key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        val = os.environ.get(env_key)
        if val:
            candidates.append(Path(val))

    candidates.extend(
        [
            Path("/opt/homebrew/share/android-commandlinetools"),
            Path.home() / "Library" / "Android" / "sdk",
            Path("/usr/local/share/android-commandlinetools"),
        ]
    )

    for candidate in candidates:
        if candidate.is_dir() and (
            (candidate / "platforms").is_dir() or (candidate / "cmdline-tools").is_dir()
        ):
            return candidate
    return None


def _find_android_platform(sdk_root: Path) -> tuple[str, Path] | None:
    """Locate `android.jar`, preferring `android-34` or the newest available version."""
    platforms_dir = sdk_root / "platforms"
    if not platforms_dir.is_dir():
        return None

    preferred = platforms_dir / "android-34" / "android.jar"
    if preferred.is_file():
        return "android-34", preferred

    candidates = sorted(
        (p for p in platforms_dir.iterdir() if p.is_dir() and (p / "android.jar").is_file()),
        key=lambda p: _version_sort_key(p.name),
        reverse=True,
    )
    if not candidates:
        return None
    return candidates[0].name, candidates[0] / "android.jar"


def _find_build_tools(sdk_root: Path) -> Path | None:
    """Locate the newest `build-tools/` folder containing all the build binaries."""
    bt_root = sdk_root / "build-tools"
    if not bt_root.is_dir():
        return None

    required = ("aapt2", "d8", "zipalign", "apksigner")
    candidates = sorted(
        (p for p in bt_root.iterdir() if p.is_dir()),
        key=lambda p: _version_sort_key(p.name),
        reverse=True,
    )
    for candidate in candidates:
        if all((candidate / tool).is_file() for tool in required):
            return candidate
    return None


def discover_toolchain() -> AndroidToolchain:
    """Discover and validate the whole JDK + Android SDK toolchain before the build."""
    java_home = find_java_home()
    if java_home is None:
        raise RuntimeError(
            "JDK not found. Install it with: brew install openjdk@17"
        )

    sdk_root = find_android_sdk()
    if sdk_root is None:
        raise RuntimeError(
            "Android SDK not found in /opt/homebrew/share/android-commandlinetools."
        )

    platform = _find_android_platform(sdk_root)
    if platform is None:
        raise RuntimeError(
            f"No Android platform found in {sdk_root / 'platforms'}. "
            "Install 'platforms;android-34' via sdkmanager."
        )
    platform_name, android_jar = platform

    build_tools = _find_build_tools(sdk_root)
    if build_tools is None:
        raise RuntimeError(
            f"Complete Android build-tools not found in {sdk_root / 'build-tools'}. "
            "Install 'build-tools;34.0.0' via sdkmanager."
        )

    return AndroidToolchain(
        java_home=java_home,
        javac_bin=java_home / "bin" / "javac",
        keytool_bin=java_home / "bin" / "keytool",
        sdk_root=sdk_root,
        android_jar=android_jar,
        platform_name=platform_name,
        build_tools_dir=build_tools,
        aapt2_bin=build_tools / "aapt2",
        d8_bin=build_tools / "d8",
        zipalign_bin=build_tools / "zipalign",
        apksigner_bin=build_tools / "apksigner",
    )


def _run_tool(cmd: list[str], toolchain: AndroidToolchain, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Run a toolchain command via argv (never shell=True) with JAVA_HOME set."""
    env = dict(os.environ)
    env["JAVA_HOME"] = str(toolchain.java_home)
    env["ANDROID_HOME"] = str(toolchain.sdk_root)
    env["PATH"] = f"{toolchain.java_home / 'bin'}:{env.get('PATH', '')}"

    proc = subprocess.run(
        cmd,
        shell=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        details = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(f"Failed to run {Path(cmd[0]).name}: {details}")
    return proc


def _ensure_debug_keystore(toolchain: AndroidToolchain, keystore_path: Path) -> None:
    """Generate the debug keystore at `certs/debug.keystore` if it does not exist yet."""
    if keystore_path.is_file():
        return
    keystore_path.parent.mkdir(parents=True, exist_ok=True)
    _run_tool(
        [
            str(toolchain.keytool_bin),
            "-genkeypair",
            "-v",
            "-keystore",
            str(keystore_path),
            "-storepass",
            "android",
            "-alias",
            "androiddebugkey",
            "-keypass",
            "android",
            "-keyalg",
            "RSA",
            "-keysize",
            "2048",
            "-validity",
            "10000",
            "-dname",
            "CN=Android Debug,O=Android,C=US",
        ],
        toolchain,
    )


def _append_dex_to_apk(base_apk: Path, dex_file: Path, output_apk: Path) -> None:
    """Copy the APK produced by aapt2 and add `classes.dex` at the package root."""
    if not dex_file.is_file():
        raise RuntimeError(f"classes.dex not found in {dex_file}")
    shutil.copyfile(base_apk, output_apk)
    with zipfile.ZipFile(output_apk, "a", compression=zipfile.ZIP_DEFLATED) as apk_zip:
        apk_zip.write(dex_file, arcname="classes.dex")


def build_apk(
    toolchain: AndroidToolchain | None = None,
    output_apk: Path = FINAL_APK_PATH,
) -> Path:
    """Run the whole pipeline aapt2 -> javac -> d8 -> zipalign -> apksigner."""
    if not MANIFEST_PATH.is_file():
        raise RuntimeError(f"Manifest not found: {MANIFEST_PATH}")
    if not RES_DIR.is_dir():
        raise RuntimeError(f"Resources directory not found: {RES_DIR}")
    if not SRC_DIR.is_dir():
        raise RuntimeError(f"Java sources directory not found: {SRC_DIR}")

    resolved = toolchain or discover_toolchain()

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    gen_dir = BUILD_DIR / "gen"
    classes_dir = BUILD_DIR / "classes"
    dex_dir = BUILD_DIR / "dex"
    for directory in (BUILD_DIR, gen_dir, classes_dir, dex_dir, output_apk.parent):
        directory.mkdir(parents=True, exist_ok=True)

    resources_zip = BUILD_DIR / "resources.zip"
    base_apk = BUILD_DIR / "unsigned-unaligned.apk"
    apk_with_dex = BUILD_DIR / "unsigned-with-dex.apk"
    aligned_apk = BUILD_DIR / "aligned.apk"

    # 1. Compile XML/VectorDrawable resources
    _run_tool(
        [
            str(resolved.aapt2_bin),
            "compile",
            "--dir",
            str(RES_DIR),
            "-o",
            str(resources_zip),
        ],
        resolved,
    )

    # 2. Link manifest + resources and generate R.java
    _run_tool(
        [
            str(resolved.aapt2_bin),
            "link",
            "-o",
            str(base_apk),
            "-I",
            str(resolved.android_jar),
            "--manifest",
            str(MANIFEST_PATH),
            "--java",
            str(gen_dir),
            "--min-sdk-version",
            "26",
            "--target-sdk-version",
            "34",
            "--auto-add-overlay",
            str(resources_zip),
        ],
        resolved,
    )

    # 3. Compile Java sources (pure SDK with --release 11)
    java_sources = sorted(
        [str(p) for p in SRC_DIR.rglob("*.java")]
        + [str(p) for p in gen_dir.rglob("*.java")]
    )
    if not java_sources:
        raise RuntimeError("No .java files found to compile.")

    _run_tool(
        [
            str(resolved.javac_bin),
            "--release",
            "11",
            "-classpath",
            str(resolved.android_jar),
            "-d",
            str(classes_dir),
            *java_sources,
        ],
        resolved,
    )

    # 4. Convert JVM bytecode to Dalvik/ART (classes.dex)
    class_files = sorted(str(p) for p in classes_dir.rglob("*.class"))
    if not class_files:
        raise RuntimeError("No .class files produced by javac.")

    _run_tool(
        [
            str(resolved.d8_bin),
            "--min-api",
            "26",
            "--lib",
            str(resolved.android_jar),
            "--output",
            str(dex_dir),
            *class_files,
        ],
        resolved,
    )

    # 5. Package classes.dex into the APK
    _append_dex_to_apk(base_apk, dex_dir / "classes.dex", apk_with_dex)

    # 6. Align the APK (4 bytes)
    _run_tool(
        [
            str(resolved.zipalign_bin),
            "-f",
            "-p",
            "4",
            str(apk_with_dex),
            str(aligned_apk),
        ],
        resolved,
    )

    # 7. Ensure the debug keystore and sign the APK
    _ensure_debug_keystore(resolved, DEBUG_KEYSTORE_PATH)
    _run_tool(
        [
            str(resolved.apksigner_bin),
            "sign",
            "--ks",
            str(DEBUG_KEYSTORE_PATH),
            "--ks-key-alias",
            "androiddebugkey",
            "--ks-pass",
            "pass:android",
            "--key-pass",
            "pass:android",
            "--out",
            str(output_apk),
            str(aligned_apk),
        ],
        resolved,
    )

    # 8. Verify the final APK signature
    _run_tool(
        [str(resolved.apksigner_bin), "verify", "--verbose", str(output_apk)],
        resolved,
    )

    return output_apk


def main() -> int:
    """CLI entry point to build the Desk Assistant APK."""
    try:
        toolchain = discover_toolchain()
        print(f"Using JDK:        {toolchain.java_home}")
        print(f"Using Platform:   {toolchain.platform_name} ({toolchain.android_jar})")
        print(f"Using BuildTools: {toolchain.build_tools_dir}")
        apk_path = build_apk(toolchain=toolchain)
        size_kb = apk_path.stat().st_size / 1024.0
        print(f"APK built and signed successfully: {apk_path} ({size_kb:.1f} KB)")
        return 0
    except Exception as exc:
        print(f"Error building the Android APK: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
