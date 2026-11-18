"""Ponto de entrada do backend: python run.py

Inicia a API e o agendador do monitoramento. Logs também vão para
backend/instance/pricewatch.log (útil quando roda em segundo plano).
"""
import atexit
import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import create_app, scheduler
from app.startup import LOCAL_HOSTS, backend_path, startup_problems

app = create_app()

log_file = Path(app.instance_path) / "pricewatch.log"
handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(handler)

def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port)) == 0


if __name__ == "__main__":
    # Uma instância só: uma segunda cópia não pode mexer no agendador/banco da primeira.
    if port_in_use(app.config["HOST"], app.config["PORT"]):
        msg = (f"PRICE WATCH já está rodando (porta {app.config['PORT']} ocupada). "
               "Use scripts/parar-backend.ps1 para encerrar a instância atual.")
        logging.getLogger("pricewatch").error(msg)
        print(msg, file=sys.stderr)
        sys.exit(1)

    # PID para scripts\parar-backend.ps1
    pid_file = Path(app.instance_path) / "pricewatch.pid"
    pid_file.write_text(str(os.getpid()))
    atexit.register(lambda: pid_file.unlink(missing_ok=True))

    problems = startup_problems(app.config)
    if problems:
        for p in problems:
            logging.getLogger("pricewatch").error(p)
            print(p, file=sys.stderr)
        sys.exit(2)

    cfg = app.config
    if cfg["SCHEDULER_ENABLED"]:
        scheduler.start(app)

    if cfg["HTTPS_CERT_FILE"]:
        # Modo Wi-Fi: o PC continua em http://localhost (sem aviso de certificado) e a rede
        # recebe um servidor HTTPS separado, com o certificado local.
        import threading

        from werkzeug.serving import make_server

        ssl_context = (str(backend_path(cfg["HTTPS_CERT_FILE"])), str(backend_path(cfg["HTTPS_KEY_FILE"])))
        https_server = make_server(cfg["HOST"], cfg["HTTPS_PORT"], app, threaded=True, ssl_context=ssl_context)
        threading.Thread(target=https_server.serve_forever, name="https", daemon=True).start()
        logging.getLogger("pricewatch").info("HTTPS para o celular em https://%s:%s", cfg["HOST"], cfg["HTTPS_PORT"])
        if cfg["HOST"] not in LOCAL_HOSTS:
            from app.services import cert_page

            cert_page.start(cfg["HOST"], cfg["CERT_PAGE_PORT"],
                            Path(app.instance_path) / "certs" / "pricewatch-ca.crt", cfg["HTTPS_PORT"])
        local_host = "127.0.0.1"
    else:
        local_host = cfg["HOST"]

    app.run(
        host=local_host,
        port=cfg["PORT"],
        debug=cfg["DEBUG"],
        use_reloader=False,  # evita iniciar o agendador duas vezes
        threaded=True,
    )
