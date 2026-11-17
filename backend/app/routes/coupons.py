"""Cupons: listagem, cadastro manual, verificação pelo usuário e coleta oficial."""
from datetime import datetime, timedelta

from flask import Blueprint, abort, jsonify, request

from ..extensions import db
from ..models import Coupon, Product, utcnow
from ..services import coupons as coupons_svc
from ..services import notify
from ..stores import STORES, is_valid_url

bp = Blueprint("coupons", __name__)

VERIFICATION = {"unconfirmed", "user_confirmed", "user_failed"}
MANUAL_REFRESH_MIN_INTERVAL = timedelta(minutes=10)


@bp.get("/coupons")
def list_coupons():
    store = request.args.get("store")
    validity = request.args.get("validity", "active")
    q = db.select(Coupon).order_by(Coupon.valid_until.is_(None), Coupon.valid_until, Coupon.id)
    if store:
        q = q.where(Coupon.store == store)
    items = [c.to_dict() for c in db.session.scalars(q)]
    if validity != "all":
        items = [c for c in items if c["validity"] == validity]
    return jsonify({"coupons": items, "sources": coupons_svc.source_status()})


def _parse_date(value) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError
    # "AAAA-MM-DD" = válido até o fim do dia (horário de Brasília)
    if len(value) == 10:
        return datetime.fromisoformat(value) + timedelta(hours=23, minutes=59) + timedelta(hours=3)
    return datetime.fromisoformat(value.replace("Z", "")).replace(tzinfo=None)


def _apply(c: Coupon, data: dict, partial: bool) -> dict:
    errors: dict[str, str] = {}

    def text(field, max_len, required=False):
        if field not in data and partial:
            return
        v = data.get(field)
        if v is not None and not isinstance(v, str):
            errors[field] = "Valor inválido."
            return
        v = (v or "").strip()
        if required and not v:
            errors[field] = "Campo obrigatório."
        elif len(v) > max_len:
            errors[field] = f"Máximo de {max_len} caracteres."
        else:
            setattr(c, field, v or None)

    if "store" in data or not partial:
        if data.get("store") not in STORES:
            errors["store"] = "Escolha uma loja."
        else:
            c.store = data["store"]
    if "code" in data or not partial:
        code = (data.get("code") or "").strip().upper() if isinstance(data.get("code"), str) else ""
        if not code or len(code) > 80 or " " in code:
            errors["code"] = "Informe o código (sem espaços)."
        else:
            c.code = code
    text("description", 400)
    text("categories", 400)
    text("conditions", 5000)
    text("source", 1000, required=not partial)

    for field in ("discount_cents", "min_purchase_cents", "max_discount_cents"):
        if field in data:
            v = data[field]
            if v in (None, ""):
                setattr(c, field, None)
            elif isinstance(v, int) and not isinstance(v, bool) and v > 0:
                setattr(c, field, v)
            else:
                errors[field] = "Valor inválido."
    if "discount_percent" in data:
        v = data["discount_percent"]
        if v in (None, ""):
            c.discount_percent = None
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v < 100:
            c.discount_percent = float(v)
        else:
            errors["discount_percent"] = "Use um percentual entre 0 e 100."
    if not partial and not (c.discount_percent or c.discount_cents):
        errors["discount_percent"] = "Informe o desconto em % ou em R$."
    if c.discount_percent and c.discount_cents:
        errors["discount_cents"] = "Use desconto em % ou em R$, não ambos."

    for field in ("valid_from", "valid_until"):
        if field in data:
            try:
                setattr(c, field, _parse_date(data[field]))
            except ValueError:
                errors[field] = "Data inválida."
    if "link_url" in data:
        v = (data.get("link_url") or "").strip()
        if v and not is_valid_url(v):
            errors["link_url"] = "Link inválido."
        else:
            c.link_url = v or None
    if "verification_status" in data:
        if data["verification_status"] not in VERIFICATION:
            errors["verification_status"] = "Status inválido."
        else:
            c.verification_status = data["verification_status"]
    return errors


@bp.post("/coupons")
def create_coupon():
    c = Coupon(origin="manual", verification_status="unconfirmed")
    errors = _apply(c, request.get_json(silent=True) or {}, partial=False)
    if errors:
        return jsonify({"error": "validation", "fields": errors}), 422
    c.last_seen_at = utcnow()
    db.session.add(c)
    db.session.flush()
    coupons_svc.create_coupon_events([c.id])
    db.session.commit()
    notify.dispatch_soon()
    return jsonify(c.to_dict()), 201


@bp.patch("/coupons/<int:coupon_id>")
def update_coupon(coupon_id: int):
    c = db.session.get(Coupon, coupon_id) or abort(404, "Cupom não encontrado.")
    data = request.get_json(silent=True) or {}
    if c.origin != "manual":
        # Cupons oficiais: só o status de verificação é editável (o resto vem da loja).
        data = {k: v for k, v in data.items() if k == "verification_status"}
    errors = _apply(c, data, partial=True)
    if errors:
        db.session.rollback()
        return jsonify({"error": "validation", "fields": errors}), 422
    db.session.commit()
    return jsonify(c.to_dict())


@bp.delete("/coupons/<int:coupon_id>")
def delete_coupon(coupon_id: int):
    c = db.session.get(Coupon, coupon_id) or abort(404, "Cupom não encontrado.")
    if c.origin != "manual":
        return jsonify({"error": "forbidden", "message": "Cupons da página oficial voltam na próxima atualização; "
                        "marque como \"não funcionou\" para ocultá-lo."}), 409
    db.session.delete(c)
    db.session.commit()
    return "", 204


@bp.post("/coupons/refresh")
def refresh():
    status = coupons_svc.source_status()["kabum"]
    last = status["last_fetch_at"]
    if last and utcnow() - datetime.fromisoformat(last.rstrip("Z")) < MANUAL_REFRESH_MIN_INTERVAL:
        return jsonify({"fetched": False, "reason": "recent",
                        "message": "Atualizado há menos de 10 minutos.", **coupons_svc.source_status()})
    result = coupons_svc.refresh_official(force=True)
    notify.dispatch_soon()
    return jsonify(result)


@bp.get("/products/<int:product_id>/coupons")
def product_coupons(product_id: int):
    product = db.session.get(Product, product_id) or abort(404, "Produto não encontrado.")
    return jsonify(coupons_svc.coupons_for_product(product))
