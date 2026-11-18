"""Importação de lista de desejos: analisar (PDF ou texto) e importar em lote."""
from flask import Blueprint, jsonify, request

from ..extensions import db
from ..models import Offer, Product
from ..services import notify
from ..services import wishlist_import as wl
from .products import build_product, save_new_product

bp = Blueprint("importer", __name__)

MAX_IMPORT = 300


def _existing_map(items: list[wl.Item]) -> dict[str, dict]:
    urls = {wl.lookup_svc.canonical(u) for it in items for u in it.urls}
    if not urls:
        return {}
    rows = db.session.execute(
        db.select(Offer.url, Product.id, Product.name).join(Product, Product.id == Offer.product_id)
        .where(Offer.url.in_(urls))
    ).all()
    return {url: {"product_id": pid, "name": name} for url, pid, name in rows}


@bp.post("/import/parse")
def parse():
    """Lê um PDF (campo 'file') ou texto (JSON {"text": ...}) e devolve itens para revisão."""
    try:
        if "file" in request.files:
            f = request.files["file"]
            data = f.read(wl.MAX_BYTES + 1)
            items, stats = wl.parse_pdf(data)
            source = {"type": "pdf", "name": (f.filename or "lista.pdf")[:120]}
        else:
            body = request.get_json(silent=True) or {}
            text = body.get("text") if isinstance(body.get("text"), str) else ""
            if not text.strip():
                return jsonify({"error": "validation", "message": "Envie um PDF ou cole o texto da lista."}), 422
            if len(text) > 500_000:
                return jsonify({"error": "validation", "message": "Texto grande demais."}), 422
            items = wl.parse_text(text)
            stats = {"pages": None, "links": None, "product_links": None, "has_text": True}
            source = {"type": "text", "name": "texto colado"}
    except wl.ImportError_ as err:
        return jsonify({"error": "import", "message": str(err)}), 422

    names = {wl._norm(n) for n in db.session.scalars(db.select(Product.name))}
    preview = wl.build_preview(items, _existing_map(items), names)
    warnings = []
    if not preview:
        warnings.append("Não encontrei produtos nesta lista. Confira se o PDF tem os nomes ou links dos "
                        "produtos (páginas de produto da KaBuM!, Pichau, Mercado Livre ou Amazon).")
    if len(items) > wl.MAX_ITEMS:
        warnings.append(f"A lista tem {len(items)} itens; mostrando os primeiros {wl.MAX_ITEMS}.")
    return jsonify({
        "source": source,
        "stats": {**stats, "items": len(preview),
                  "with_links": sum(1 for i in preview if i["urls"]),
                  "already_monitored": sum(1 for i in preview if "Já monitorado." in i["warnings"]
                                         or "Já existe um produto com este nome." in i["warnings"])},
        "items": preview,
        "warnings": warnings,
    })


@bp.post("/products/import")
def import_products():
    """Cria vários produtos de uma vez. Cada item é validado como no cadastro normal;
    links que já estão em outro produto são ignorados (sem duplicar)."""
    body = request.get_json(silent=True) or {}
    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({"error": "validation", "message": "Nenhum item para importar."}), 422
    if len(raw_items) > MAX_IMPORT:
        return jsonify({"error": "validation", "message": f"Máximo de {MAX_IMPORT} itens por vez."}), 422

    created, skipped, errors = [], [], []
    for idx, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            errors.append({"index": idx, "name": None, "fields": {"_": "Formato inválido."}})
            continue
        data = dict(raw)
        # descarta links já monitorados em outro produto
        offers, dup = [], []
        for o in data.get("offers") or []:
            url = o.get("url") if isinstance(o, dict) else None
            if isinstance(url, str) and db.session.scalar(
                db.select(Offer.id).where(Offer.url == wl.lookup_svc.canonical(url.strip()))
            ):
                dup.append(url)
            else:
                offers.append(o)
        if dup and not offers:
            skipped.append({"index": idx, "name": data.get("name"), "reason": "Já monitorado."})
            continue
        data["offers"] = offers
        product, errs = build_product(data)
        if errs:
            errors.append({"index": idx, "name": data.get("name"), "fields": errs})
            continue
        save_new_product(product)
        created.append({"index": idx, "id": product.id, "name": product.name,
                        "offers": len(product.offers), "ignored_links": dup})
    db.session.commit()
    if created:
        notify.dispatch_soon()
    status = 201 if created else 422
    return jsonify({"created": created, "skipped": skipped, "errors": errors}), status
