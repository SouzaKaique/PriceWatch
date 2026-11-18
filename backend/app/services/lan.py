"""Acesso pelo celular no Wi-Fi de casa, com HTTPS próprio (sem serviços externos).

Como funciona
- Gera uma autoridade certificadora LOCAL ("PRICE WATCH Local CA") e, com ela, o
  certificado do servidor para os IPs/nome deste PC na rede.
- Você instala só o certificado da CA no celular (uma vez). A chave da CA nunca sai
  do PC (backend/instance/certs/, fora do git).
- Se o IP do PC mudar, basta gerar de novo o certificado do servidor: a CA continua a
  mesma e o celular não precisa reinstalar nada.

Regras do iOS respeitadas: RSA 2048 + SHA-256, CA com basicConstraints, certificado do
servidor com SAN (IPs e nomes), serverAuth e validade ≤ 825 dias.
"""
from __future__ import annotations

import ipaddress
import re
import secrets
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_NAME = "PRICE WATCH Local CA"
CA_DAYS = 3650
SERVER_DAYS = 825  # limite aceito pelo iOS para CAs instaladas pelo usuário


@dataclass
class CertPaths:
    dir: Path

    @property
    def ca_key(self) -> Path:
        return self.dir / "ca.key"

    @property
    def ca_cert(self) -> Path:
        return self.dir / "pricewatch-ca.crt"

    @property
    def server_key(self) -> Path:
        return self.dir / "server.key"

    @property
    def server_cert(self) -> Path:
        return self.dir / "server.crt"


# ---- Rede -----------------------------------------------------------------------

def lan_ips() -> list[str]:
    """IPv4 privados deste PC (ex.: 192.168.0.10). Não envia nenhum pacote."""
    found: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # UDP não conecta de fato; só escolhe a interface
            found.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    ips = []
    for ip in found:
        addr = ipaddress.ip_address(ip)
        if addr.is_private and not addr.is_loopback and not addr.is_link_local:
            ips.append(ip)
    return sorted(ips, key=lambda i: tuple(int(p) for p in i.split(".")))


def hostname() -> str:
    return re.sub(r"[^A-Za-z0-9-]", "", socket.gethostname()).lower() or "pricewatch"


# ---- Certificados -------------------------------------------------------------------

def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _write_key(path: Path, key) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                       serialization.NoEncryption()))


def ensure_ca(paths: CertPaths) -> tuple[x509.Certificate, rsa.RSAPrivateKey, bool]:
    """Carrega a CA existente ou cria uma nova. Retorna (cert, chave, criada_agora)."""
    paths.dir.mkdir(parents=True, exist_ok=True)
    if paths.ca_key.exists() and paths.ca_cert.exists():
        key = serialization.load_pem_private_key(paths.ca_key.read_bytes(), password=None)
        cert = x509.load_pem_x509_certificate(paths.ca_cert.read_bytes())
        return cert, key, False
    key = _new_key()
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PRICE WATCH (uso pessoal)"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False, data_encipherment=False,
                                     key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_key(paths.ca_key, key)
    paths.ca_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, key, True


def issue_server_cert(paths: CertPaths, ips: list[str], names: list[str]) -> x509.Certificate:
    ca_cert, ca_key, _ = ensure_ca(paths)
    key = _new_key()
    alt = [x509.DNSName(n) for n in dict.fromkeys(names + ["localhost"])]
    alt += [x509.IPAddress(ipaddress.ip_address(i)) for i in dict.fromkeys(ips + ["127.0.0.1"])]
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0] if names else "pricewatch")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=SERVER_DAYS))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, content_commitment=False,
                                     data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                     crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(paths.server_key, key)
    # cadeia completa (servidor + CA) ajuda alguns clientes
    paths.server_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM)
                                  + ca_cert.public_bytes(serialization.Encoding.PEM))
    return cert


def cert_info(path: Path) -> dict | None:
    if not path.exists():
        return None
    cert = x509.load_pem_x509_certificate(path.read_bytes())
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        ips = [str(i) for i in san.get_values_for_type(x509.IPAddress)]
        names = san.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        ips, names = [], []
    return {
        "ips": ips,
        "names": names,
        "expires_at": cert.not_valid_after_utc.isoformat(),
        "days_left": (cert.not_valid_after_utc - datetime.now(timezone.utc)).days,
    }


# ---- .env -----------------------------------------------------------------------------

def update_env(env_path: Path, values: dict[str, str]) -> Path | None:
    """Altera/insere chaves no .env preservando o resto. Retorna o caminho do backup."""
    backup = None
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    if env_path.exists():
        backup = env_path.with_name(env_path.name + ".bak")
        backup.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pending = dict(values)
    out = []
    for line in lines:
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in pending:
            out.append(f"{m.group(1)}={pending.pop(m.group(1))}")
        else:
            out.append(line)
    if pending:
        out.append("")
        out.append("# Acesso pelo celular no Wi-Fi (gerado por configurar_wifi.py)")
        out += [f"{k}={v}" for k, v in pending.items()]
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return backup


def read_env(env_path: Path) -> dict[str, str]:
    data = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=(.*)$", line)
            if m:
                data[m.group(1)] = m.group(2).strip()
    return data


def new_access_key() -> str:
    # fácil de digitar no celular: 4 blocos de 5 caracteres sem ambiguidades
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4))
