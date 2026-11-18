"""Configuração do backend, lida do arquivo .env (nunca versionado)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")

    # Banco SQLite local em backend/instance/pricewatch.db
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{(Path(os.getenv('PRICEWATCH_INSTANCE_DIR') or BASE_DIR / 'instance') / 'pricewatch.db').as_posix()}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Uploads (PDF da lista de desejos) até 25 MB
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024
    # Espera até 15 s se o banco estiver ocupado (API + agendador + envio de alertas em paralelo)
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 15}}

    # Rede: por padrão só aceita conexões da própria máquina.
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "5000"))
    DEBUG = _bool(os.getenv("FLASK_DEBUG"), False)

    # Origens autorizadas a chamar a API pelo navegador (frontend Angular).
    CORS_ORIGINS = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200").split(",")
        if o.strip()
    ]

    # Chave de acesso opcional. Se definida, toda requisição /api (exceto /api/health)
    # precisa do cabeçalho "X-API-Key". Útil se um dia a API for exposta além do localhost.
    API_ACCESS_KEY = os.getenv("API_ACCESS_KEY", "").strip()

    # HTTPS próprio para o celular no Wi-Fi (gerado por configurar_wifi.py). Caminhos
    # relativos partem da pasta backend/.
    HTTPS_CERT_FILE = os.getenv("HTTPS_CERT_FILE", "").strip()
    HTTPS_KEY_FILE = os.getenv("HTTPS_KEY_FILE", "").strip()
    # Porta HTTPS para o celular (o PC continua em http://localhost:PORT).
    HTTPS_PORT = int(os.getenv("HTTPS_PORT", "5443"))
    # Página para o celular baixar o certificado (só no modo Wi-Fi).
    CERT_PAGE_PORT = int(os.getenv("CERT_PAGE_PORT", "5001"))

    # Build de produção do frontend servido pelo Flask (npm run build).
    FRONTEND_DIST = os.getenv(
        "FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist" / "frontend" / "browser")
    )

    # Agendador do monitoramento (desligado nos testes).
    SCHEDULER_ENABLED = _bool(os.getenv("SCHEDULER_ENABLED"), True)

    # Intervalo padrão do monitoramento (minutos); pode ser alterado na tela Sistema.
    CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "120"))
