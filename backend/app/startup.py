"""Verificações feitas antes de o backend começar a aceitar conexões."""
from pathlib import Path

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def backend_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path(__file__).resolve().parent.parent / path


def startup_problems(config) -> list[str]:
    """Configurações inseguras ou incompletas que impedem iniciar."""
    problems = []
    exposed = config["HOST"] not in LOCAL_HOSTS
    if exposed and not config["API_ACCESS_KEY"]:
        problems.append(
            f"HOST={config['HOST']} deixa o app visível na rede, mas API_ACCESS_KEY está vazia. "
            "Defina uma chave no .env (ou rode configurar_wifi.py) ou volte HOST=127.0.0.1."
        )
    cert, key = config["HTTPS_CERT_FILE"], config["HTTPS_KEY_FILE"]
    if bool(cert) != bool(key):
        problems.append("Defina HTTPS_CERT_FILE e HTTPS_KEY_FILE juntos (ou nenhum dos dois).")
    elif cert and not (backend_path(cert).is_file() and backend_path(key).is_file()):
        problems.append("Certificado HTTPS não encontrado. Rode: .venv/Scripts/python configurar_wifi.py")
    return problems
