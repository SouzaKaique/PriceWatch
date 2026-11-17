from flask import Blueprint, current_app, jsonify
from sqlalchemy import func, text

from .. import scheduler
from ..services import maintenance
from ..extensions import db
from ..models import Offer, Product
from ..stores import store_list
from ..services.analysis import analyze_offer
from ..summary import product_summary

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    """Verifica se a API e o banco SQLite estão respondendo."""
    try:
        db.session.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Falha no banco")
        database = f"erro: {exc.__class__.__name__}"

    integ = maintenance.integrity()
    if database == "ok" and integ.get("ok") is False:
        database = "erro de integridade — restaure um backup (veja o README)"
    return jsonify(
        {
            "status": "ok" if database == "ok" else "degraded",
            "app": "PRICE WATCH",
            "version": current_app.config["APP_VERSION"],
            "database": database,
            "check_interval_minutes": current_app.config["CHECK_INTERVAL_MINUTES"],
        }
    )


@bp.get("/stores")
def stores():
    return jsonify(store_list())


@bp.get("/stats")
def stats():
    """Indicadores do dashboard — todos calculados a partir de dados reais do banco."""
    products = db.session.scalars(db.select(Product)).all()
    active = [p for p in products if p.active]
    summaries = [(p, product_summary(p)) for p in active]

    target_reached = sum(1 for _, s in summaries if s["target_reached"])

    # Oportunidades: produtos cuja melhor oferta está classificada como ótima/boa.
    opportunities = 0
    for p, s in summaries:
        best = next((o for o in p.offers if o.id == s["best_offer_id"]), None)
        if best and analyze_offer(best)["classification"] in ("great", "good"):
            opportunities += 1

    # Maior redução: maior queda entre preço anterior e atual registrada em uma oferta.
    biggest_drop = None
    for p in active:
        for o in p.offers:
            if o.previous_price_cents and o.current_price_cents is not None:
                drop = o.previous_price_cents - o.current_price_cents
                if drop > 0 and (biggest_drop is None or drop > biggest_drop["amount_cents"]):
                    biggest_drop = {
                        "amount_cents": drop,
                        "percent": round(drop / o.previous_price_cents * 100, 2),
                        "product_id": p.id,
                        "product_name": p.name,
                        "store": o.store,
                    }

    # Economia potencial: soma, por produto, da diferença entre a oferta mais cara e a mais barata.
    savings = sum(
        s["highest_price_cents"] - s["best_price_cents"]
        for _, s in summaries
        if s["priced_offer_count"] >= 2
    )

    last_check = db.session.scalar(db.select(func.max(Offer.last_checked_at)))
    sched = scheduler.status()
    stores_count = db.session.scalar(db.select(func.count(func.distinct(Offer.store))))
    offers_count = db.session.scalar(db.select(func.count(Offer.id)))

    return jsonify(
        {
            "products": len(active),
            "products_total": len(products),
            "stores": stores_count or 0,
            "offers": offers_count or 0,
            "priced_offers": sum(s["priced_offer_count"] for _, s in summaries),
            "target_reached": target_reached,
            "opportunities": opportunities,
            "biggest_drop": biggest_drop,
            "potential_savings_cents": savings,
            "last_check_at": last_check.isoformat() + "Z" if last_check else None,
            "scheduler_active": sched["scheduler_active"] and not sched["paused"],
            "next_check_at": sched["next_run_at"],
            "monitor_running": sched["running"],
        }
    )


@bp.get("/diagnostics")
def diagnostics():
    """Verificações de saúde com orientação do que fazer (tela Sistema)."""
    from ..services import diagnostics as diag

    items = diag.run()
    worst = "error" if any(i["status"] == "error" for i in items) else (
        "warn" if any(i["status"] == "warn" for i in items) else "ok")
    return jsonify({"status": worst, "items": items})
