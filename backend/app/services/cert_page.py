"""Página simples (HTTP, porta 5001) para o celular baixar o certificado da CA local.

Só serve duas coisas públicas: as instruções e o certificado da CA (que não é segredo).
Nenhum dado do app, nenhuma API. Fica ligada apenas no modo Wi-Fi (HTTPS + rede).
"""
from __future__ import annotations

import html
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger(__name__)

PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRICE WATCH — certificado</title>
<style>
 body{{margin:0;background:#0b1120;color:#e6ebf5;font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
 main{{max-width:34rem;margin:0 auto;padding:24px 16px 48px}}
 h1{{font-size:1.3rem;letter-spacing:.08em}} h1 span{{color:#a3e635}}
 .card{{background:#131c2e;border:1px solid #26324a;border-radius:14px;padding:16px 18px;margin:14px 0}}
 h2{{font-size:1rem;margin:0 0 6px}} ol{{padding-left:1.2rem;margin:6px 0}} li{{margin:4px 0}}
 a.btn{{display:block;text-align:center;background:#3b82f6;color:#fff;text-decoration:none;
       padding:12px;border-radius:10px;font-weight:600;margin:10px 0}}
 a.btn.alt{{background:transparent;border:1px solid #3b82f6;color:#e6ebf5}}
 code{{background:#0b1120;border:1px solid #26324a;border-radius:6px;padding:1px 6px}}
 small{{color:#8a96ad}}
</style></head><body><main>
<h1><span>∿</span> PRICE WATCH</h1>
<p>Para abrir o app com segurança (HTTPS) e receber notificações, instale uma vez o certificado
deste computador. Ele só vale para o seu PRICE WATCH.</p>
<a class="btn" href="/pricewatch-ca.crt">1. Baixar o certificado</a>
<div class="card"><h2>iPhone / iPad</h2><ol>
 <li>Toque em <b>Baixar o certificado</b> e em <b>Permitir</b>.</li>
 <li>Abra <b>Ajustes → Perfil Transferido</b> → <b>Instalar</b>.</li>
 <li><b>Ajustes → Geral → Sobre → Ajustes de Confiança de Certificados</b> → ative
     <b>PRICE WATCH Local CA</b>.</li>
 <li>Abra o app abaixo no <b>Safari</b> → <b>Compartilhar → Adicionar à Tela de Início</b>.</li>
 <li>Abra pelo ícone criado → <b>Alertas → Ativar neste aparelho</b>.</li>
</ol><small>Notificações no iPhone exigem iOS 16.4 ou mais recente.</small></div>
<div class="card"><h2>Android</h2><ol>
 <li>Toque em <b>Baixar o certificado</b>.</li>
 <li><b>Configurações → Segurança → Mais configurações → Instalar da memória →
     Certificado de CA</b> (o caminho varia por fabricante; procure por "certificado CA").</li>
 <li>Abra o app abaixo no <b>Chrome</b> → menu → <b>Instalar app</b>.</li>
 <li>No app: <b>Alertas → Ativar neste aparelho</b>.</li>
</ol></div>
<a class="btn alt" href="{app_url}">2. Abrir o PRICE WATCH ({app_host})</a>
<p><small>Quando o app pedir a <b>chave de acesso</b>, use a que aparece no computador
(arquivo <code>backend/.env</code>, linha <code>API_ACCESS_KEY</code>).</small></p>
</main></body></html>"""


def make_handler(ca_cert: Path, app_port: int):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PriceWatchCert"

        def log_message(self, fmt, *args):  # silencioso (vai para o log só em nível debug)
            log.debug("cert-page: " + fmt, *args)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/pricewatch-ca.crt" and ca_cert.exists():
                data = ca_cert.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-x509-ca-cert")
                self.send_header("Content-Disposition", 'attachment; filename="pricewatch-ca.crt"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path in ("/", "/index.html"):
                host = (self.headers.get("Host") or "").split(":")[0] or "localhost"
                host = html.escape(host, quote=True)
                url = f"https://{host}:{app_port}/"
                body = PAGE.format(app_url=url, app_host=f"{host}:{app_port}").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)

    return Handler


def start(host: str, port: int, ca_cert: Path, app_port: int) -> ThreadingHTTPServer | None:
    try:
        server = ThreadingHTTPServer((host, port), make_handler(ca_cert, app_port))
    except OSError as exc:
        log.warning("Página do certificado não iniciou na porta %s: %s", port, exc)
        return None
    threading.Thread(target=server.serve_forever, name="cert-page", daemon=True).start()
    log.info("Página do certificado em http://%s:%s/", host, port)
    return server
