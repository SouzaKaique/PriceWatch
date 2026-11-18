"""Modo Wi-Fi: certificado local, .env, proteções de inicialização e chave de acesso."""
import ipaddress
import subprocess
import sys
import urllib.request
from datetime import timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509.oid import ExtendedKeyUsageOID

from app.services import cert_page, lan
from app.startup import startup_problems

BACKEND = Path(__file__).resolve().parent.parent


def load(path):
    return x509.load_pem_x509_certificate(path.read_bytes())


def test_certificates_follow_ios_rules(tmp_path):
    paths = lan.CertPaths(tmp_path / "certs")
    lan.issue_server_cert(paths, ["192.168.0.10"], ["meupc.local", "meupc"])
    ca, srv = load(paths.ca_cert), load(paths.server_cert)

    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
    assert ca.public_key().key_size >= 2048
    bc = srv.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is False
    san = srv.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address("192.168.0.10") in san.get_values_for_type(x509.IPAddress)
    assert {"meupc.local", "localhost"} <= set(san.get_values_for_type(x509.DNSName))
    eku = srv.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    assert srv.not_valid_after_utc - srv.not_valid_before_utc <= timedelta(days=lan.SERVER_DAYS + 1)
    assert srv.signature_hash_algorithm.name == "sha256"
    # assinado pela CA local
    ca.public_key().verify(srv.signature, srv.tbs_certificate_bytes, padding.PKCS1v15(), srv.signature_hash_algorithm)
    # chave da CA fica só no PC e o arquivo público não contém chave privada
    assert b"PRIVATE KEY" not in paths.ca_cert.read_bytes()


def test_reissue_keeps_same_ca(tmp_path):
    paths = lan.CertPaths(tmp_path / "certs")
    lan.issue_server_cert(paths, ["192.168.0.10"], ["pc.local"])
    first_ca = paths.ca_cert.read_bytes()
    lan.issue_server_cert(paths, ["192.168.0.77"], ["pc.local"])  # IP mudou
    assert paths.ca_cert.read_bytes() == first_ca  # celular não precisa reinstalar
    assert "192.168.0.77" in lan.cert_info(paths.server_cert)["ips"]


def test_update_env_preserves_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comentário\nSECRET_KEY=abc\nHOST=127.0.0.1\nTELEGRAM_BOT_TOKEN=\n", encoding="utf-8")
    backup = lan.update_env(env, {"HOST": "0.0.0.0", "API_ACCESS_KEY": "k"})
    text = env.read_text(encoding="utf-8")
    assert "# comentário" in text and "SECRET_KEY=abc" in text and "HOST=0.0.0.0" in text
    assert "API_ACCESS_KEY=k" in text and text.count("HOST=") == 1
    assert backup.read_text(encoding="utf-8").startswith("# comentário")


def test_access_key_is_easy_to_type():
    key = lan.new_access_key()
    blocks = key.split("-")
    assert len(blocks) == 4 and all(len(b) == 5 for b in blocks)
    assert not set(key) & set("0O1lI")


def test_configure_script_end_to_end(tmp_path):
    env = tmp_path / ".env"
    env.write_text("HOST=127.0.0.1\nPORT=5000\nAPI_ACCESS_KEY=\n", encoding="utf-8")
    inst = tmp_path / "instance"
    cmd = [sys.executable, str(BACKEND / "configurar_wifi.py"), "--env", str(env), "--instance", str(inst),
           "--ip", "192.168.50.5"]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=BACKEND)
    assert out.returncode == 0, out.stderr
    values = lan.read_env(env)
    assert values["HOST"] == "0.0.0.0" and values["HTTPS_CERT_FILE"].endswith("server.crt")
    assert len(values["API_ACCESS_KEY"]) == 23
    assert "http://" in out.stdout and ":5001" in out.stdout and values["API_ACCESS_KEY"] in out.stdout
    assert "192.168.50.5" in lan.cert_info(inst / "certs" / "server.crt")["ips"]

    # rodar de novo mantém a chave e a CA
    ca_before = (inst / "certs" / "pricewatch-ca.crt").read_bytes()
    subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=BACKEND, check=True)
    assert lan.read_env(env)["API_ACCESS_KEY"] == values["API_ACCESS_KEY"]
    assert (inst / "certs" / "pricewatch-ca.crt").read_bytes() == ca_before

    undo = subprocess.run(cmd[:2] + ["--desfazer", "--env", str(env), "--instance", str(inst)],
                          capture_output=True, text=True, encoding="utf-8", cwd=BACKEND)
    assert undo.returncode == 0 and lan.read_env(env)["HOST"] == "127.0.0.1"
    assert lan.read_env(env)["HTTPS_CERT_FILE"] == ""


def test_startup_refuses_exposed_without_key(tmp_path):
    base = {"HOST": "127.0.0.1", "API_ACCESS_KEY": "", "HTTPS_CERT_FILE": "", "HTTPS_KEY_FILE": ""}
    assert startup_problems(base) == []
    assert any("API_ACCESS_KEY" in p for p in startup_problems({**base, "HOST": "0.0.0.0"}))
    assert startup_problems({**base, "HOST": "0.0.0.0", "API_ACCESS_KEY": "k"}) == []
    missing = {**base, "HTTPS_CERT_FILE": str(tmp_path / "x.crt"), "HTTPS_KEY_FILE": str(tmp_path / "x.key")}
    assert any("configurar_wifi" in p for p in startup_problems(missing))
    assert startup_problems({**base, "HTTPS_CERT_FILE": "a.crt"})  # só um dos dois


def test_key_required_from_network_but_not_from_this_pc(client):
    client.application.config["API_ACCESS_KEY"] = "segredo"
    # o próprio PC (localhost) não precisa da chave
    assert client.get("/api/products").status_code == 200
    # celular na rede: precisa
    lan_env = {"REMOTE_ADDR": "192.168.0.20"}
    r = client.get("/api/products", environ_base=lan_env, headers={"Host": "192.168.0.10:5000"})
    assert r.status_code == 401
    ok = client.get("/api/products", environ_base=lan_env,
                    headers={"Host": "192.168.0.10:5000", "X-API-Key": "segredo"})
    assert ok.status_code == 200
    # proxy local (ex.: Tailscale Serve) com Host público também precisa
    assert client.get("/api/products", headers={"Host": "meupc.tail1234.ts.net"}).status_code == 401
    # o app em si (arquivos estáticos) carrega sem chave para poder pedir a chave
    assert client.get("/api/health", environ_base=lan_env).status_code == 200


def test_access_endpoint_local_mode(client):
    a = client.get("/api/access").get_json()
    assert a["mode"] == "local" and a["app_urls"] == [] and "access_key" not in str(a).lower().replace(
        "access_key_required", "")


def test_cert_page_serves_only_public_files(tmp_path):
    paths = lan.CertPaths(tmp_path / "certs")
    lan.ensure_ca(paths)
    server = cert_page.start("127.0.0.1", 0, paths.ca_cert, 5000)
    port = server.server_address[1]
    try:
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode("utf-8")
        assert "Baixar o certificado" in page and "https://127.0.0.1:5000/" in page
        crt = urllib.request.urlopen(f"http://127.0.0.1:{port}/pricewatch-ca.crt", timeout=5)
        assert crt.headers["Content-Type"] == "application/x-x509-ca-cert"
        assert crt.read() == paths.ca_cert.read_bytes()
        for bad in ("/ca.key", "/../ca.key", "/api/products"):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{bad}", timeout=5)
                raise AssertionError(f"{bad} deveria ser 404")
            except urllib.error.HTTPError as e:
                assert e.code == 404
    finally:
        server.shutdown()
