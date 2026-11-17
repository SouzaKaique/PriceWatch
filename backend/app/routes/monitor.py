"""Monitoramento: status, execução manual, configurações, eventos e histórico."""
from datetime import timedelta

from flask import Blueprint, abort, jsonify, request

from .. import scheduler
from ..extensions import db
from ..models import MonitorRun, Offer, PriceEvent, PriceHistory, Product, utcnow
from ..services import settings as settings_svc
from ..services.analysis import analyze_product

bp = Blueprint("monitor", __name__)


@bp.get("/monitor")
def monitor_status():
    runs = db.session.scalars(db.select(MonitorRun).order_by(MonitorRun.started_at.desc()).limit(10)).all()
    cfg = settings_svc.get_all()
    return jsonify(
        {
            **scheduler.status(),
            "enabled": cfg["monitor_enabled"],
            "interval_minutes": cfg["check_interval_minutes"],
            "runs": [r.to_dict() for r in runs],
        }
    )


@bp.post("/monitor/run")
def monitor_run():
    started = scheduler.run_now()
    if not started:
        return jsonify({"started": False, "message": "Já existe uma verificação em andamento."}), 409
    return jsonify({"started": True}), 202


@bp.get("/settings")
def get_settings():
    return jsonify(settings_svc.get_all())


@bp.patch("/settings")
def patch_settings():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "validation", "fields": {"_": "Corpo inválido."}}), 422
    clean, errors = settings_svc.validate(data)
    if errors:
        return jsonify({"error": "validation", "fields": errors}), 422
    cfg = settings_svc.update(clean)
    scheduler.apply_settings(cfg)
    return jsonify(cfg)


@bp.get("/events")
def list_events():
    limit = min(max(request.args.get("limit", 30, type=int), 1), 200)
    q = db.select(PriceEvent).order_by(PriceEvent.created_at.desc(), PriceEvent.id.desc()).limit(limit)
    product_id = request.args.get("product_id", type=int)
    if product_id:
        q = q.where(PriceEvent.product_id == product_id)
    return jsonify([e.to_dict() for e in db.session.scalars(q)])


@bp.get("/products/<int:product_id>/history")
def product_history(product_id: int):
    """Séries de preço por oferta. `days=0` (ou ausente) retorna tudo."""
    product = db.session.get(Product, product_id) or abort(404, "Produto não encontrado.")
    days = request.args.get("days", 0, type=int)
    since = utcnow() - timedelta(days=days) if days > 0 else None

    series = []
    for offer in product.offers:
        q = db.select(PriceHistory).where(PriceHistory.offer_id == offer.id)
        if since:
            q = q.where(PriceHistory.checked_at >= since)
        points = db.session.scalars(q.order_by(PriceHistory.checked_at, PriceHistory.id)).all()
        series.append(
            {
                "offer_id": offer.id,
                "store": offer.store,
                "points": [
                    {
                        "t": p.checked_at.isoformat() + "Z",
                        "price_cents": p.price_cents,
                        "available": p.available,
                        "source": p.source or "auto",
                    }
                    for p in points
                ],
            }
        )
    first = db.session.scalar(
        db.select(PriceHistory.checked_at)
        .join(Offer, Offer.id == PriceHistory.offer_id)
        .where(Offer.product_id == product.id)
        .order_by(PriceHistory.checked_at)
        .limit(1)
    )
    return jsonify(
        {
            "product_id": product.id,
            "target_price_cents": product.target_price_cents,
            "days": days,
            "monitoring_since": first.isoformat() + "Z" if first else None,
            "series": series,
        }
    )


@bp.get("/products/<int:product_id>/analysis")
def product_analysis(product_id: int):
    """Análise completa: preço habitual, médias 7/30/90/180, menor registrado, classificação."""
    product = db.session.get(Product, product_id) or abort(404, "Produto não encontrado.")
    return jsonify(analyze_product(product))
