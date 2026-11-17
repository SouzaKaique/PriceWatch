"""Registro das lojas suportadas e detecção da loja a partir da URL."""
from urllib.parse import urlparse

STORES: dict[str, dict] = {
    "kabum": {"name": "KaBuM!", "domains": ["kabum.com.br"]},
    "pichau": {"name": "Pichau", "domains": ["pichau.com.br"]},
    "mercadolivre": {
        "name": "Mercado Livre",
        "domains": ["mercadolivre.com.br", "mercadolivre.com", "mercadolibre.com"],
    },
    "amazon": {"name": "Amazon Brasil", "domains": ["amazon.com.br", "amzn.to"]},
}


def detect_store(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for key, info in STORES.items():
        if any(host == d or host.endswith("." + d) for d in info["domains"]):
            return key
    return None


def is_valid_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme in {"http", "https"} and bool(p.hostname)


def store_list() -> list[dict]:
    return [{"key": k, "name": v["name"], "domains": v["domains"]} for k, v in STORES.items()]
