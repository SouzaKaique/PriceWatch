r"""Prepara o PRICE WATCH para ser aberto pelo celular no Wi-Fi de casa (HTTPS próprio).

    .venv\Scripts\python configurar_wifi.py            # configura (ou renova o certificado)
    .venv\Scripts\python configurar_wifi.py --desfazer # volta a aceitar só este computador

O que faz:
  1. Gera (uma vez) a autoridade certificadora local e o certificado do servidor
     para os IPs deste PC na rede (backend/instance/certs/).
  2. Atualiza o backend/.env (com backup em .env.bak): HOST=0.0.0.0, HTTPS e uma
     chave de acesso (obrigatória quando o app fica visível na rede).
Depois reinicie o backend e siga o passo a passo em http://<IP-do-PC>:5001 no celular.
"""
import argparse
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from app.services import lan  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ip", action="append", default=[], help="IP extra a incluir no certificado")
    parser.add_argument("--desfazer", action="store_true", help="volta HOST=127.0.0.1 e desliga o HTTPS")
    parser.add_argument("--env", default=str(BASE / ".env"), help=argparse.SUPPRESS)
    parser.add_argument("--instance", default=os.getenv("PRICEWATCH_INSTANCE_DIR") or str(BASE / "instance"),
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    env_path = Path(args.env)
    paths = lan.CertPaths(Path(args.instance) / "certs")

    if args.desfazer:
        lan.update_env(env_path, {"HOST": "127.0.0.1", "HTTPS_CERT_FILE": "", "HTTPS_KEY_FILE": ""})
        print("Pronto: o PRICE WATCH volta a aceitar só este computador (http://localhost:5000).")
        print("Reinicie o backend. A chave de acesso e os certificados foram mantidos.")
        return 0

    ips = list(dict.fromkeys(lan.lan_ips() + args.ip))
    if not ips:
        print("Não encontrei um IP de rede local neste PC. Conecte-se ao Wi-Fi/cabo e tente de novo,")
        print("ou informe manualmente: configurar_wifi.py --ip 192.168.0.10")
        return 1
    host = lan.hostname()
    _, _, created = lan.ensure_ca(paths)
    lan.issue_server_cert(paths, ips, [f"{host}.local", host])

    current = lan.read_env(env_path)
    key = current.get("API_ACCESS_KEY") or lan.new_access_key()
    port = current.get("HTTPS_PORT") or "5443"
    backup = lan.update_env(env_path, {
        "HOST": "0.0.0.0",
        "HTTPS_CERT_FILE": "instance/certs/server.crt" if Path(args.instance) == BASE / "instance"
        else str(paths.server_cert),
        "HTTPS_KEY_FILE": "instance/certs/server.key" if Path(args.instance) == BASE / "instance"
        else str(paths.server_key),
        "API_ACCESS_KEY": key,
    })

    line = "─" * 64
    print(line)
    print("PRICE WATCH pronto para o Wi-Fi de casa")
    print(line)
    print(f"Certificado da CA: {'criado agora' if created else 'reaproveitado (o celular não precisa reinstalar)'}")
    print(f"Certificado do servidor: IPs {', '.join(ips)} · nome {host}.local · válido por {lan.SERVER_DAYS} dias")
    if backup:
        print(f".env atualizado (backup em {backup.name})")
    print()
    print("1) Reinicie o backend (feche e abra de novo, ou scripts\\parar-backend.ps1 + iniciar-backend.bat).")
    print("   Se o Windows perguntar sobre o Firewall, permita em REDES PRIVADAS.")
    print(f"2) No celular, no mesmo Wi-Fi, abra:  http://{ips[0]}:5001")
    print("   e siga o passo a passo para instalar o certificado.")
    print(f"3) Depois abra o app em:              https://{ips[0]}:{port}")
    print("   (neste computador continue usando http://localhost:5000, sem aviso de certificado)")
    print(f"4) Chave de acesso (digite no celular quando pedir):  {key}")
    print(line)
    print("Dica: reserve o IP deste PC no roteador (DHCP fixo). Se o IP mudar, rode este script de novo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
