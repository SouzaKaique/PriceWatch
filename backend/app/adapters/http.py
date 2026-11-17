"""Cliente HTTP compartilhado e respeitoso com as lojas.

- Uma requisição por vez por domínio, com intervalo mínimo entre elas.
- Se a loja bloquear (403/429/página de verificação), o domínio entra em pausa
  e NENHUMA tentativa de contornar a proteção é feita.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from urllib.parse import urlparse

import requests

from .base import LookupFailed

log = logging.getLogger(__name__)

USER_AGENT = os.getenv(
    "HTTP_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36",
)
TIMEOUT = 20
MIN_INTERVAL_SECONDS = float(os.getenv("HTTP_MIN_INTERVAL_SECONDS", "5"))
BLOCK_COOLDOWN_SECONDS = int(os.getenv("HTTP_BLOCK_COOLDOWN_SECONDS", "1800"))
MAX_BYTES = 5 * 1024 * 1024

# Sinais de páginas anti-robô. Ao detectá-los, apenas desistimos.
CHALLENGE_MARKERS = (
    "account-verification",
    "suspicious-traffic",
    "validatecaptcha",
    "/errors/validatecaptcha",
    "captcha",
    "cf-chl",
    "challenge-platform",
    "just a moment...",
)

_session = requests.Session()
_session.headers.update(
    {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
    }
)

_lock = threading.Lock()
_last_request: dict[str, float] = {}
_blocked_until: dict[str, float] = {}


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    parts = host.split(".")
    return ".".join(parts[-3:]) if host.endswith(".com.br") else ".".join(parts[-2:])


def blocked_remaining(url: str) -> int:
    return max(0, int(_blocked_until.get(_domain(url), 0) - time.time()))


def _mark_blocked(domain: str) -> None:
    _blocked_until[domain] = time.time() + BLOCK_COOLDOWN_SECONDS
    log.warning("Domínio %s bloqueou a consulta; pausa de %ss", domain, BLOCK_COOLDOWN_SECONDS)


def reset_state() -> None:
    """Usado nos testes."""
    _last_request.clear()
    _blocked_until.clear()


API_MIN_INTERVAL_SECONDS = 1.0


def get_json(
    url: str,
    store_name: str,
    headers: dict | None = None,
    params: dict | None = None,
) -> tuple[int, dict | list | None]:
    """GET em API oficial (JSON). Retorna (status, corpo). Não trata 401/403 —
    quem chama decide (ex.: renovar token)."""
    domain = _domain(url)
    with _lock:
        elapsed = time.time() - _last_request.get(domain, 0)
        if elapsed < API_MIN_INTERVAL_SECONDS:
            time.sleep(API_MIN_INTERVAL_SECONDS - elapsed)
        _last_request[domain] = time.time()
    try:
        resp = _session.get(
            url, headers={"Accept": "application/json", **(headers or {})}, params=params, timeout=TIMEOUT
        )
    except requests.Timeout as exc:
        raise LookupFailed("network", f"A API da {store_name} não respondeu a tempo.") from exc
    except requests.RequestException as exc:
        raise LookupFailed("network", f"Falha de conexão com a API da {store_name}.") from exc
    if resp.status_code == 429:
        raise LookupFailed("rate_limited", f"A API da {store_name} pediu para reduzir as consultas (429).")
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, body


def get_text(url: str, source_name: str) -> str:
    """GET simples de texto (ex.: arquivos públicos indicados pela loja), com limite por domínio."""
    domain = _domain(url)
    if blocked_remaining(url):
        raise LookupFailed("rate_limited", f"{source_name} em pausa após bloqueio recente.")
    with _lock:
        elapsed = time.time() - _last_request.get(domain, 0)
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        _last_request[domain] = time.time()
    try:
        resp = _session.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise LookupFailed("network", f"Falha de conexão com {source_name}.") from exc
    if resp.status_code in (403, 429):
        _mark_blocked(domain)
        raise LookupFailed("blocked", f"{source_name} recusou a consulta (HTTP {resp.status_code}).")
    if resp.status_code >= 400:
        raise LookupFailed("network", f"{source_name} respondeu com erro HTTP {resp.status_code}.")
    if len(resp.content) > MAX_BYTES:
        raise LookupFailed("parse", "Resposta grande demais.")
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


def post_form(url: str, data: dict, store_name: str) -> tuple[int, dict | None]:
    try:
        resp = _session.post(url, data=data, headers={"Accept": "application/json"}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise LookupFailed("network", f"Falha de conexão com {store_name}.") from exc
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, None


def get_html(url: str, store_name: str) -> tuple[str, str]:
    """Baixa uma página. Retorna (html, url_final)."""
    domain = _domain(url)
    wait = blocked_remaining(url)
    if wait:
        raise LookupFailed(
            "rate_limited",
            f"{store_name} bloqueou consultas recentes. Nova tentativa liberada em "
            f"{wait // 60 + 1} min.",
        )

    with _lock:
        elapsed = time.time() - _last_request.get(domain, 0)
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        _last_request[domain] = time.time()

    try:
        resp = _session.get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.Timeout as exc:
        raise LookupFailed("network", f"{store_name} não respondeu a tempo.") from exc
    except requests.RequestException as exc:
        raise LookupFailed("network", f"Falha de conexão com {store_name}.") from exc

    final_url = resp.url
    if resp.status_code == 404:
        raise LookupFailed("not_found", f"Produto não encontrado na {store_name} (404).")
    if resp.status_code in (403, 429, 202, 503):
        _mark_blocked(domain)
        raise LookupFailed(
            "blocked",
            f"{store_name} recusou a consulta automática (HTTP {resp.status_code}, proteção "
            "anti-robô). O PRICE WATCH não contorna essas proteções.",
        )
    if resp.status_code >= 400:
        raise LookupFailed("network", f"{store_name} respondeu com erro HTTP {resp.status_code}.")

    if len(resp.content) > MAX_BYTES:
        raise LookupFailed("parse", "Página grande demais para ser analisada.")

    if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    html = resp.text

    lowered_url = final_url.lower()
    head = html[:20000].lower()
    if any(m in lowered_url for m in CHALLENGE_MARKERS) or (
        len(html) < 60000 and any(m in head for m in CHALLENGE_MARKERS[2:])
    ):
        _mark_blocked(domain)
        raise LookupFailed(
            "blocked",
            f"{store_name} exibiu uma verificação anti-robô. O PRICE WATCH não contorna "
            "essas proteções.",
        )
    return html, final_url
