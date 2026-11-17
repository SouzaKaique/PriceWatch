"""Autenticação na API oficial do Mercado Livre (OAuth 2.0).

Credenciais do app ficam no .env (ML_CLIENT_ID, ML_CLIENT_SECRET, ML_REDIRECT_URI).
Tokens ficam no banco local (tabela settings) e nunca são enviados ao frontend.

Dois modos, tentados nesta ordem:
1. Conta autorizada (authorization_code + PKCE): o usuário autoriza uma vez e o
   refresh token é renovado automaticamente.
2. Token de aplicação (client_credentials): só com as credenciais do app.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse

from ..adapters.base import LookupFailed
from ..adapters.http import post_form
from ..extensions import db
from ..models import Setting

TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
STORE = "Mercado Livre"

_lock = threading.Lock()


def _cfg() -> tuple[str, str, str]:
    return (
        os.getenv("ML_CLIENT_ID", "").strip(),
        os.getenv("ML_CLIENT_SECRET", "").strip(),
        os.getenv("ML_REDIRECT_URI", "").strip(),
    )


def is_configured() -> bool:
    cid, secret, _ = _cfg()
    return bool(cid and secret)


def _get(key: str) -> str | None:
    row = db.session.get(Setting, key)
    return row.value if row else None


def _set(key: str, value: str | None) -> None:
    row = db.session.get(Setting, key)
    if value is None:
        if row:
            db.session.delete(row)
        return
    if row:
        row.value = value
    else:
        db.session.add(Setting(key=key, value=value))


def status() -> dict:
    _, _, redirect = _cfg()
    return {
        "configured": is_configured(),
        "redirect_uri_configured": bool(redirect),
        "user_connected": bool(_get("ml_refresh_token")),
        "mode": _get("ml_token_mode"),
        "last_error": _get("ml_last_error"),
    }


# ---- Autorização da conta (authorization_code + PKCE) ------------------------

def authorization_url() -> str:
    cid, _, redirect = _cfg()
    if not cid or not redirect:
        raise LookupFailed("unsupported", "Defina ML_CLIENT_ID e ML_REDIRECT_URI no .env.")
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    _set("ml_pkce_verifier", verifier)
    _set("ml_oauth_state", state)
    db.session.commit()
    return AUTH_URL + "?" + urlencode(
        {
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": redirect,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )


def _extract_code(code_or_url: str) -> tuple[str, str | None]:
    text = code_or_url.strip()
    if text.startswith("http"):
        qs = parse_qs(urlparse(text).query)
        code = (qs.get("code") or [""])[0]
        return code, (qs.get("state") or [None])[0]
    return text, None


def connect(code_or_url: str) -> None:
    """Troca o código de autorização (ou a URL de retorno colada) por tokens."""
    cid, secret, redirect = _cfg()
    if not (cid and secret and redirect):
        raise LookupFailed("unsupported", "Configure ML_CLIENT_ID, ML_CLIENT_SECRET e ML_REDIRECT_URI no .env.")
    code, state = _extract_code(code_or_url)
    if not code:
        raise LookupFailed("parse", "Não encontrei o parâmetro 'code' no texto colado.")
    expected = _get("ml_oauth_state")
    if state and expected and state != expected:
        raise LookupFailed("parse", "A autorização não corresponde à última solicitação. Gere um novo link.")
    data = {
        "grant_type": "authorization_code",
        "client_id": cid,
        "client_secret": secret,
        "code": code,
        "redirect_uri": redirect,
    }
    verifier = _get("ml_pkce_verifier")
    if verifier:
        data["code_verifier"] = verifier
    status_code, body = post_form(TOKEN_URL, data, STORE)
    if status_code != 200 or not body or "access_token" not in body:
        msg = (body or {}).get("message") or (body or {}).get("error") or f"HTTP {status_code}"
        raise LookupFailed("blocked", f"O Mercado Livre recusou a autorização: {msg}.")
    _store_tokens(body, mode="user")
    _set("ml_pkce_verifier", None)
    _set("ml_oauth_state", None)
    db.session.commit()


def disconnect() -> None:
    for k in ("ml_access_token", "ml_access_expires", "ml_refresh_token", "ml_token_mode", "ml_last_error"):
        _set(k, None)
    db.session.commit()


# ---- Tokens ------------------------------------------------------------------

def _store_tokens(body: dict, mode: str) -> None:
    _set("ml_access_token", body["access_token"])
    _set("ml_access_expires", str(int(time.time()) + int(body.get("expires_in", 21600)) - 300))
    if body.get("refresh_token"):
        _set("ml_refresh_token", body["refresh_token"])  # o ML devolve um novo a cada renovação
    _set("ml_token_mode", mode)
    _set("ml_last_error", None)


def _request_token() -> None:
    cid, secret, _ = _cfg()
    refresh = _get("ml_refresh_token")
    if refresh:
        data = {"grant_type": "refresh_token", "client_id": cid, "client_secret": secret, "refresh_token": refresh}
        mode = "user"
    else:
        data = {"grant_type": "client_credentials", "client_id": cid, "client_secret": secret}
        mode = "app"
    status_code, body = post_form(TOKEN_URL, data, STORE)
    if status_code != 200 or not body or "access_token" not in body:
        msg = (body or {}).get("message") or (body or {}).get("error") or f"HTTP {status_code}"
        if mode == "user" and status_code in (400, 401):
            _set("ml_refresh_token", None)  # refresh inválido/expirado: precisa autorizar de novo
        _set("ml_last_error", f"Falha ao obter token ({mode}): {msg}")
        db.session.commit()
        raise LookupFailed("blocked", f"O Mercado Livre recusou as credenciais: {msg}.")
    _store_tokens(body, mode)
    db.session.commit()


def access_token(force_refresh: bool = False) -> str:
    if not is_configured():
        raise LookupFailed(
            "unsupported",
            "Integração oficial do Mercado Livre não configurada (ML_CLIENT_ID/ML_CLIENT_SECRET no .env).",
        )
    with _lock:
        token = _get("ml_access_token")
        expires = int(_get("ml_access_expires") or 0)
        if force_refresh or not token or time.time() >= expires:
            _request_token()
            token = _get("ml_access_token")
        return token or ""


def record_error(message: str | None) -> None:
    _set("ml_last_error", message)
    db.session.commit()
