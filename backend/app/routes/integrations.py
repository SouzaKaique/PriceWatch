"""Status das integrações com as lojas e conexão com a API do Mercado Livre."""
from flask import Blueprint, abort, jsonify, request
from sqlalchemy import func

from ..adapters import ADAPTERS, LookupFailed
from ..adapters.http import blocked_remaining
from ..extensions import db
from ..models import Offer, PriceHistory, utcnow
from ..services import ml_auth, notify
from ..services import settings as settings_svc
from ..services.events import (
    OfferSnapshot,
    ProductSnapshot,
    detect_analysis_events,
    detect_offer_events,
    detect_product_events,
)
from ..stores import STORES

bp = Blueprint("integrations", __name__)

SAMPLE_URL = {
    "kabum": "https://www.kabum.com.br/",
    "pichau": "https://www.pichau.com.br/",
    "mercadolivre": "https://www.mercadolivre.com.br/",
    "amazon": "https://www.amazon.com.br/",
}


def _store_stats(store: str) -> dict:
    rows = db.session.execute(
        db.select(Offer.last_status, func.count(Offer.id), func.max(Offer.last_checked_at))
        .where(Offer.store == store)
        .group_by(Offer.last_status)
    ).all()
    by_status = {status or "pending": count for status, count, _ in rows}
    last_ok = db.session.scalar(
        db.select(func.max(Offer.last_checked_at)).where(Offer.store == store, Offer.last_status == "ok")
    )
    last_error = db.session.scalar(
        db.select(Offer.last_error)
        .where(Offer.store == store, Offer.last_status != "ok", Offer.last_error.is_not(None))
        .order_by(Offer.last_checked_at.desc())
        .limit(1)
    )
    return {
        "offers": sum(by_status.values()),
        "by_status": by_status,
        "last_success_at": last_ok.isoformat() + "Z" if last_ok else None,
        "last_error": last_error,
    }


@bp.get("/integrations")
def list_integrations():
    out = []
    for key, adapter in ADAPTERS.items():
        item = {
            "key": key,
            "name": STORES[key]["name"],
            "method": adapter.method,
            "limitation": getattr(adapter, "limitation", None),
            "paused_seconds": blocked_remaining(SAMPLE_URL[key]),
            "stats": _store_stats(key),
        }
        if key == "mercadolivre":
            ml = ml_auth.status()
            item["mercadolivre"] = ml
            item["state"] = (
                "connected" if ml["user_connected"] else "app_token" if ml["configured"] else "not_configured"
            )
        elif key == "kabum":
            item["state"] = "available"
        else:
            item["state"] = "limited"
        out.append(item)
    return jsonify(out)


@bp.post("/integrations/mercadolivre/authorize")
def ml_authorize():
    try:
        return jsonify({"url": ml_auth.authorization_url()})
    except LookupFailed as err:
        return jsonify({"error": err.code, "message": err.message}), 400


@bp.post("/integrations/mercadolivre/connect")
def ml_connect():
    data = request.get_json(silent=True) or {}
    code = data.get("code") if isinstance(data.get("code"), str) else ""
    if not code.strip():
        return jsonify({"error": "validation", "fields": {"code": "Cole o código ou a URL de retorno."}}), 422
    try:
        ml_auth.connect(code)
    except LookupFailed as err:
        return jsonify({"error": err.code, "message": err.message}), 400
    return jsonify(ml_auth.status())


@bp.post("/integrations/mercadolivre/test")
def ml_test():
    """Obtém um token para validar as credenciais (não consulta produtos)."""
    try:
        ml_auth.access_token(force_refresh=True)
    except LookupFailed as err:
        return jsonify({"ok": False, "message": err.message, **ml_auth.status()})
    return jsonify({"ok": True, "message": "Credenciais aceitas pelo Mercado Livre.", **ml_auth.status()})


@bp.post("/integrations/mercadolivre/disconnect")
def ml_disconnect():
    ml_auth.disconnect()
    return jsonify(ml_auth.status())


@bp.post("/offers/<int:offer_id>/manual-price")
def manual_price(offer_id: int):
    """Registra um preço visto pelo usuário (lojas sem integração automática).

    Fica identificado como "informado manualmente" no histórico e na interface.
    """
    offer = db.session.get(Offer, offer_id) or abort(404, "Oferta não encontrada.")
    data = request.get_json(silent=True) or {}
    price = data.get("price_cents")
    available = data.get("available", True)
    errors = {}
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
        errors["price_cents"] = "Informe um preço válido."
    if available is not None and not isinstance(available, bool):
        errors["available"] = "Valor inválido."
    if errors:
        return jsonify({"error": "validation", "fields": errors}), 422

    now = utcnow()
    cfg = settings_svc.get_all()
    p_before, o_before = ProductSnapshot.of(offer.product), OfferSnapshot.of(offer)
    if offer.current_price_cents is not None and offer.current_price_cents != price:
        offer.previous_price_cents = offer.current_price_cents
    offer.current_price_cents = price
    offer.installment_price_cents = None
    offer.list_price_cents = None
    offer.available = available
    offer.price_source = "manual"
    offer.history.append(PriceHistory(price_cents=price, available=available, source="manual", checked_at=now))
    detect_offer_events(offer.product, offer, o_before, cfg, source="manual")
    detect_product_events(offer.product, p_before, source="manual")
    detect_analysis_events(offer.product, offer, source="manual")
    db.session.commit()
    notify.dispatch_soon()
    return jsonify(offer.to_dict())
