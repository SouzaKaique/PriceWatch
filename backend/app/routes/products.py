"""Produtos e ofertas.

Preços só entram no banco por consultas reais às lojas (services/lookup.py);
o navegador nunca envia preços.
"""
from flask import Blueprint, abort, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Offer, PriceHistory, Product
from ..services import coupons as coupons_svc
from ..services import lookup as lookup_svc
from ..services import notify
from ..services.monitor import check_offer_with_events
from ..stores import STORES, detect_store, is_valid_url
from ..summary import product_payload

bp = Blueprint("products", __name__)

TEXT_FIELDS = {
    "name": 300,
    "brand": 120,
    "model": 160,
    "manufacturer_code": 120,
    "category": 120,
    "image_url": 1000,
    "notes": 5000,
}


def _errors(errors: dict):
    return jsonify({"error": "validation", "fields": errors}), 422


def _apply_product_fields(product: Product, data: dict, partial: bool) -> dict:
    errors: dict[str, str] = {}

    for field, max_len in TEXT_FIELDS.items():
        if field not in data:
            continue
        value = data[field]
        if value is not None and not isinstance(value, str):
            errors[field] = "Valor inválido."
            continue
        value = (value or "").strip() or None
        if value and len(value) > max_len:
            errors[field] = f"Máximo de {max_len} caracteres."
            continue
        setattr(product, field, value)

    if not partial or "name" in data:
        if not product.name:
            errors["name"] = "Informe o nome do produto."

    if product.image_url and not is_valid_url(product.image_url):
        errors["image_url"] = "URL de imagem inválida."

    if "target_price_cents" in data:
        value = data["target_price_cents"]
        if value is None or value == "":
            product.target_price_cents = None
        elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            product.target_price_cents = value
        else:
            errors["target_price_cents"] = "Preço-alvo inválido."

    if "active" in data:
        if isinstance(data["active"], bool):
            product.active = data["active"]
        else:
            errors["active"] = "Valor inválido."

    return errors


def _validate_offer(data: dict) -> tuple[dict, dict]:
    errors: dict[str, str] = {}
    url = (data.get("url") or "").strip() if isinstance(data.get("url"), str) else ""
    if not url or not is_valid_url(url):
        errors["url"] = "Informe um link válido (http/https)."
    elif len(url) > 1500:
        errors["url"] = "Link muito longo."

    store = detect_store(url) if url and not errors else None
    if not errors.get("url") and store not in STORES:
        errors["store"] = "Loja não suportada. Lojas disponíveis: " + ", ".join(
            s["name"] for s in STORES.values()
        )
    if not errors:
        url = lookup_svc.canonical(url, store)
    return {"url": url, "store": store}, errors


@bp.post("/lookup")
def lookup():
    """Identifica um produto a partir do link (consulta real à loja, com cache curto)."""
    data = request.get_json(silent=True) or {}
    url = data.get("url").strip() if isinstance(data.get("url"), str) else ""
    if not url or not is_valid_url(url) or len(url) > 1500:
        return _errors({"url": "Informe um link válido (http/https)."})
    if detect_store(url) is None:
        return _errors({"url": "Loja não suportada. Lojas disponíveis: " + ", ".join(
            s["name"] for s in STORES.values())})
    return jsonify(lookup_svc.lookup_result(url))


def _get_product(product_id: int) -> Product:
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404, "Produto não encontrado.")
    return product


@bp.get("/products")
def list_products():
    products = db.session.scalars(db.select(Product).order_by(Product.created_at.desc())).all()
    return jsonify([product_payload(p) for p in products])


@bp.post("/products")
def create_product():
    data = request.get_json(silent=True) or {}
    product = Product()
    errors = _apply_product_fields(product, data, partial=False)

    offers_in = data.get("offers") or []
    if not isinstance(offers_in, list):
        errors["offers"] = "Formato inválido."
        offers_in = []
    seen = set()
    for i, raw in enumerate(offers_in):
        clean, off_err = _validate_offer(raw if isinstance(raw, dict) else {})
        for k, v in off_err.items():
            errors[f"offers.{i}.{k}"] = v
        if not off_err:
            if clean["url"] in seen:
                errors[f"offers.{i}.url"] = "Link repetido."
                continue
            seen.add(clean["url"])
            product.offers.append(Offer(**clean))

    if errors:
        return _errors(errors)
    db.session.add(product)
    for offer in product.offers:
        lookup_svc.seed_offer_from_cache(offer)  # sem nova requisição à loja
    db.session.flush()
    coupons_svc.events_for_new_product(product)
    db.session.commit()
    notify.dispatch_soon()
    return jsonify(product_payload(product)), 201


@bp.get("/products/<int:product_id>")
def get_product(product_id: int):
    return jsonify(product_payload(_get_product(product_id)))


@bp.patch("/products/<int:product_id>")
def update_product(product_id: int):
    product = _get_product(product_id)
    errors = _apply_product_fields(product, request.get_json(silent=True) or {}, partial=True)
    if errors:
        db.session.rollback()
        return _errors(errors)
    db.session.commit()
    return jsonify(product_payload(product))


@bp.delete("/products/<int:product_id>")
def delete_product(product_id: int):
    db.session.delete(_get_product(product_id))
    db.session.commit()
    return "", 204


@bp.post("/products/<int:product_id>/offers")
def add_offer(product_id: int):
    product = _get_product(product_id)
    clean, errors = _validate_offer(request.get_json(silent=True) or {})
    if errors:
        return _errors(errors)
    if db.session.scalar(
        db.select(Offer.id).where(Offer.product_id == product.id, Offer.url == clean["url"])
    ):
        return _errors({"url": "Este link já está cadastrado neste produto."})
    offer = Offer(product_id=product.id, **clean)
    db.session.add(offer)
    lookup_svc.check_offer(offer, use_cache=True)  # consulta real; falhas ficam registradas
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _errors({"url": "Este link já está cadastrado neste produto."})
    return jsonify(offer.to_dict()), 201


@bp.post("/offers/<int:offer_id>/check")
def check_offer(offer_id: int):
    """Consulta a loja agora (respeitando o limite de requisições por domínio)."""
    offer = db.session.get(Offer, offer_id) or abort(404, "Oferta não encontrada.")
    check_offer_with_events(offer)  # mesma lógica do monitoramento (inclui eventos)
    db.session.commit()
    notify.dispatch_soon()
    return jsonify(offer.to_dict())


@bp.patch("/offers/<int:offer_id>")
def update_offer(offer_id: int):
    offer = db.session.get(Offer, offer_id) or abort(404, "Oferta não encontrada.")
    data = request.get_json(silent=True) or {}
    if "match_confirmed" in data:
        if not isinstance(data["match_confirmed"], bool):
            return _errors({"match_confirmed": "Valor inválido."})
        offer.match_confirmed = data["match_confirmed"]
    db.session.commit()
    return jsonify(offer.to_dict())


@bp.delete("/offers/<int:offer_id>")
def delete_offer(offer_id: int):
    offer = db.session.get(Offer, offer_id) or abort(404, "Oferta não encontrada.")
    db.session.delete(offer)
    db.session.commit()
    return "", 204


@bp.get("/offers/<int:offer_id>/history")
def offer_history(offer_id: int):
    db.session.get(Offer, offer_id) or abort(404, "Oferta não encontrada.")
    rows = db.session.scalars(
        db.select(PriceHistory)
        .where(PriceHistory.offer_id == offer_id)
        .order_by(PriceHistory.checked_at, PriceHistory.id)
    ).all()
    return jsonify([r.to_dict() for r in rows])
