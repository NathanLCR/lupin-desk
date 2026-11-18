"""Generate local TLS certificates in `certs/` for HTTPS on the LAN (RG406H and iPhone)."""

from __future__ import annotations

import argparse
import ipaddress
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CERTS_DIR = BASE_DIR / "certs"
CERT_FILE = CERTS_DIR / "cert.pem"
KEY_FILE = CERTS_DIR / "key.pem"

_OPENSSL_CANDIDATES = (
    "/opt/homebrew/bin/openssl",
    "/usr/local/bin/openssl",
    "/usr/bin/openssl",
)
_IFCONFIG_BIN = "/sbin/ifconfig"
_INET_RE = re.compile(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})\b")


def _is_usable_lan_ip(candidate: str) -> bool:
    """Check whether the IPv4 address is usable on the LAN (ignores loopback, link-local and 0.0.0.0)."""
    cleaned = (candidate or "").strip()
    if not cleaned:
        return False
    if cleaned.startswith("127.") or cleaned.startswith("169.254.") or cleaned == "0.0.0.0":
        return False
    try:
        addr = ipaddress.IPv4Address(cleaned)
    except ValueError:
        return False
    return not addr.is_loopback and not addr.is_link_local and not addr.is_unspecified


def detect_lan_ip() -> str:
    """Detect the machine's local LAN IP without sending external traffic."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        if _is_usable_lan_ip(ip):
            return ip
    except OSError:
        pass
    finally:
        sock.close()

    # Fallback for environments with no external route (e.g. sandbox): read `/sbin/ifconfig`.
    if Path(_IFCONFIG_BIN).exists():
        try:
            proc = subprocess.run(
                [_IFCONFIG_BIN],
                shell=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout:
                candidates = [
                    ip for ip in _INET_RE.findall(proc.stdout) if _is_usable_lan_ip(ip)
                ]
                if candidates:
                    # Prefer common private LAN ranges (192.168.x.x / 10.x.x.x / 172.16-31.x.x).
                    private_first = [
                        ip for ip in candidates if ipaddress.IPv4Address(ip).is_private
                    ]
                    return private_first[0] if private_first else candidates[0]
        except Exception:
            pass

    try:
        hostname_ip = socket.gethostbyname(socket.gethostname())
        if _is_usable_lan_ip(hostname_ip):
            return hostname_ip
    except OSError:
        pass

    return "127.0.0.1"


def _find_openssl() -> str | None:
    """Locate a trusted OpenSSL binary."""
    for candidate in _OPENSSL_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return shutil.which("openssl")


def generate_certs(lan_ip: str | None = None) -> tuple[Path, Path, str, str]:
    """Generate `certs/cert.pem` and `certs/key.pem` via mkcert or self-signed OpenSSL."""
    if lan_ip is not None:
        cleaned_ip = lan_ip.strip()
        try:
            ipaddress.ip_address(cleaned_ip)
        except ValueError as exc:
            raise ValueError(f"Invalid IP given in --ip: '{lan_ip}'") from exc
        resolved_ip = cleaned_ip
    else:
        resolved_ip = detect_lan_ip()

    CERTS_DIR.mkdir(parents=True, exist_ok=True)

    mkcert_bin = shutil.which("mkcert")
    if mkcert_bin:
        hosts = ["localhost", "127.0.0.1"]
        if resolved_ip not in hosts:
            hosts.append(resolved_ip)
        proc = subprocess.run(
            [
                mkcert_bin,
                "-cert-file",
                str(CERT_FILE),
                "-key-file",
                str(KEY_FILE),
                *hosts,
            ],
            shell=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"mkcert failed: {proc.stderr.strip()}")
        return CERT_FILE, KEY_FILE, resolved_ip, "mkcert"

    openssl_bin = _find_openssl()
    if not openssl_bin:
        raise RuntimeError("Neither mkcert nor openssl was found on the system.")

    san_entries = ["DNS:localhost", "IP:127.0.0.1"]
    if resolved_ip not in {"127.0.0.1", "localhost"}:
        san_entries.append(f"IP:{resolved_ip}")
    san_value = ",".join(san_entries)

    openssl_cfg = (
        "[req]\n"
        "default_bits = 2048\n"
        "prompt = no\n"
        "default_md = sha256\n"
        "distinguished_name = dn\n"
        "x509_extensions = v3_req\n\n"
        "[dn]\n"
        "CN = desk-assistant.local\n\n"
        "[v3_req]\n"
        "basicConstraints = CA:FALSE\n"
        "keyUsage = digitalSignature, keyEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        f"subjectAltName = {san_value}\n"
    )

    with tempfile.NamedTemporaryFile("w", suffix=".cnf", encoding="utf-8", delete=True) as cfg_file:
        cfg_file.write(openssl_cfg)
        cfg_file.flush()
        proc = subprocess.run(
            [
                openssl_bin,
                "req",
                "-x509",
                "-nodes",
                "-days",
                "365",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(KEY_FILE),
                "-out",
                str(CERT_FILE),
                "-config",
                cfg_file.name,
                "-extensions",
                "v3_req",
            ],
            shell=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"openssl failed: {proc.stderr.strip()}")

    return CERT_FILE, KEY_FILE, resolved_ip, "openssl"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point to generate certificates and print run instructions."""
    parser = argparse.ArgumentParser(
        description="Generate local TLS certificates in certs/ for HTTPS access on the LAN."
    )
    parser.add_argument(
        "--ip",
        dest="ip",
        default=None,
        help="Local LAN IP to include in the certificate SAN (auto-detected if omitted).",
    )
    args = parser.parse_args(argv)

    try:
        cert_path, key_path, lan_ip, method = generate_certs(lan_ip=args.ip)
    except Exception as exc:
        print(f"Error generating HTTPS certificates: {exc}", file=sys.stderr)
        return 1

    print(f"Certificates generated successfully ({method}):")
    print(f"  Certificate: {cert_path}")
    print(f"  Key:         {key_path}")
    print(f"  LAN IP:      {lan_ip}")
    print()
    print("Start the HTTP server (local / USB ADB tunnel):")
    print("  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000")
    print()
    print("Start the HTTPS server (Wi-Fi LAN for microphone/sensors on the RG406H and iPhone):")
    print(
        "  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443 "
        "--ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem"
    )
    print()
    print("USB ADB tunnel for the Anbernic RG406H:")
    print("  adb reverse tcp:8000 tcp:8000")
    print("  adb reverse tcp:8443 tcp:8443")
    print()
    print("Access URLs:")
    print("  ADB / Localhost: http://localhost:8000")
    print(f"  LAN HTTPS:       https://{lan_ip}:8443")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
