"""Web Push (notificação do próprio PWA instalado).

- Chaves VAPID geradas localmente na primeira execução (backend/instance/vapid_private.pem,
  fora do git) — ou definidas em VAPID_PRIVATE_KEY_FILE no .env.
- O envio sai do seu computador para o serviço de push do navegador (Google, Apple,
  Mozilla) — gratuito e sem conta. Para o celular se inscrever, o app precisa estar
  aberto por HTTPS (ex.: Tailscale Serve) e, no iPhone, instalado na Tela de Início.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from flask import current_app
from py_vapid import Vapid01
from pywebpush import WebPushException, webpush

from ..extensions import db
from ..models import PushSubscription

log = logging.getLogger(__name__)


class PushError(Exception):
    pass


def _key_path() -> Path:
    custom = os.getenv("VAPID_PRIVATE_KEY_FILE", "").strip()
    return Path(custom) if custom else Path(current_app.instance_path) / "vapid_private.pem"


def _vapid() -> Vapid01:
    path = _key_path()
    if not path.exists():
        v = Vapid01()
        v.generate_keys()
        path.parent.mkdir(parents=True, exist_ok=True)
        v.save_key(str(path))
        log.info("Chaves VAPID geradas em %s", path)
    return Vapid01.from_file(str(path))


def public_key() -> str:
    """Chave pública no formato esperado pelo navegador (base64url, ponto não comprimido)."""
    raw = _vapid().public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def subject() -> str:
    # Contato exigido pelo protocolo VAPID; não precisa ser seu e-mail pessoal.
    return os.getenv("VAPID_SUBJECT", "").strip() or "mailto:pricewatch@example.com"


def subscribe(info: dict, user_agent: str | None) -> PushSubscription:
    endpoint = info.get("endpoint")
    keys = info.get("keys") or {}
    if not (isinstance(endpoint, str) and endpoint.startswith("https://") and keys.get("p256dh") and keys.get("auth")):
        raise PushError("Inscrição de push inválida.")
    sub = db.session.scalar(db.select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=endpoint)
        db.session.add(sub)
    sub.p256dh, sub.auth = keys["p256dh"], keys["auth"]
    sub.user_agent = (user_agent or "")[:300]
    db.session.commit()
    return sub


def unsubscribe(endpoint: str) -> bool:
    sub = db.session.scalar(db.select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if sub:
        db.session.delete(sub)
        db.session.commit()
    return sub is not None


def count() -> int:
    return db.session.scalar(db.select(db.func.count(PushSubscription.id))) or 0


def payload(title: str, body: str, url: str | None) -> dict:
    """Formato entendido pelo service worker do Angular (ngsw): tocar abre a oferta."""
    data: dict = {}
    if url:
        data["onActionClick"] = {"default": {"operation": "openWindow", "url": url}}
    return {
        "notification": {
            "title": f"PRICE WATCH — {title}",
            "body": body,
            "icon": "icons/icon-192x192.png",
            "badge": "icons/icon-96x96.png",
            "lang": "pt-BR",
            "data": data,
        }
    }


def send(title: str, body: str, url: str | None) -> None:
    subs = db.session.scalars(db.select(PushSubscription)).all()
    if not subs:
        raise PushError("Nenhum aparelho inscrito para Web Push.")
    key_file = str(_key_path())
    _vapid()  # garante as chaves
    data = json.dumps(payload(title, body, url), ensure_ascii=False)
    delivered, errors = 0, []
    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=data,
                vapid_private_key=key_file,
                vapid_claims={"sub": subject()},
                ttl=24 * 3600,
                timeout=15,
            )
            delivered += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                db.session.delete(sub)  # inscrição expirou/foi removida no aparelho
                errors.append("inscrição expirada removida")
            else:
                errors.append(f"HTTP {status}" if status else str(exc)[:120])
        except Exception as exc:  # noqa: BLE001 - rede etc.
            errors.append(exc.__class__.__name__)
    db.session.commit()
    if not delivered:
        raise PushError("Web Push falhou: " + "; ".join(errors))
