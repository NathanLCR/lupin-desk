"""Gera certificados TLS locais em `certs/` para HTTPS na LAN (RG406H e iPhone)."""

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
    """Verifica se o IPv4 é utilizável na LAN (ignora loopback, link-local e 0.0.0.0)."""
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
    """Detecta o IP local da máquina na LAN sem enviar tráfego externo."""
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

    # Fallback para ambientes sem rota externa (ex.: sandbox): lê `/sbin/ifconfig`.
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
                    # Prioriza faixas privadas comuns de LAN (192.168.x.x / 10.x.x.x / 172.16-31.x.x).
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
    """Localiza binário OpenSSL confiável."""
    for candidate in _OPENSSL_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return shutil.which("openssl")


def generate_certs(lan_ip: str | None = None) -> tuple[Path, Path, str, str]:
    """Gera `certs/cert.pem` e `certs/key.pem` via mkcert ou OpenSSL autoassinado."""
    if lan_ip is not None:
        cleaned_ip = lan_ip.strip()
        try:
            ipaddress.ip_address(cleaned_ip)
        except ValueError as exc:
            raise ValueError(f"IP inválido informado em --ip: '{lan_ip}'") from exc
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
            raise RuntimeError(f"mkcert falhou: {proc.stderr.strip()}")
        return CERT_FILE, KEY_FILE, resolved_ip, "mkcert"

    openssl_bin = _find_openssl()
    if not openssl_bin:
        raise RuntimeError("Nem mkcert nem openssl foram encontrados no sistema.")

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
            raise RuntimeError(f"openssl falhou: {proc.stderr.strip()}")

    return CERT_FILE, KEY_FILE, resolved_ip, "openssl"


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada CLI para gerar certificados e exibir instruções de execução."""
    parser = argparse.ArgumentParser(
        description="Gera certificados TLS locais em certs/ para acesso HTTPS na LAN."
    )
    parser.add_argument(
        "--ip",
        dest="ip",
        default=None,
        help="IP local da LAN para incluir no SAN do certificado (detectado automaticamente se omitido).",
    )
    args = parser.parse_args(argv)

    try:
        cert_path, key_path, lan_ip, method = generate_certs(lan_ip=args.ip)
    except Exception as exc:
        print(f"Erro ao gerar certificados HTTPS: {exc}", file=sys.stderr)
        return 1

    print(f"Certificados gerados com sucesso ({method}):")
    print(f"  Certificado: {cert_path}")
    print(f"  Chave:       {key_path}")
    print(f"  IP da LAN:   {lan_ip}")
    print()
    print("Subir servidor HTTP (local / túnel ADB USB):")
    print("  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000")
    print()
    print("Subir servidor HTTPS (LAN Wi-Fi para microfone/sensores no RG406H e iPhone):")
    print(
        "  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443 "
        "--ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem"
    )
    print()
    print("Túnel USB ADB para Anbernic RG406H:")
    print("  adb reverse tcp:8000 tcp:8000")
    print("  adb reverse tcp:8443 tcp:8443")
    print()
    print("URLs de acesso:")
    print("  ADB / Localhost: http://localhost:8000")
    print(f"  LAN HTTPS:       https://{lan_ip}:8443")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
