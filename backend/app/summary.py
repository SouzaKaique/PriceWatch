"""Cálculos derivados exclusivamente dos dados reais armazenados."""
from .models import Product
from .services.matching import match_hint


def product_summary(product: Product) -> dict:
    priced = [
        o for o in product.offers if o.current_price_cents is not None and o.available is not False
    ]
    best = min(priced, key=lambda o: o.current_price_cents) if priced else None
    highest = max(priced, key=lambda o: o.current_price_cents) if priced else None

    variation = None
    if best and best.previous_price_cents:
        variation = round(
            (best.current_price_cents - best.previous_price_cents) / best.previous_price_cents * 100,
            2,
        )

    target = product.target_price_cents
    last_checks = [o.last_checked_at for o in product.offers if o.last_checked_at]

    return {
        "best_price_cents": best.current_price_cents if best else None,
        "best_store": best.store if best else None,
        "best_offer_id": best.id if best else None,
        "best_url": best.url if best else None,
        "highest_price_cents": highest.current_price_cents if highest else None,
        "variation_percent": variation,
        "target_reached": bool(best and target is not None and best.current_price_cents <= target),
        "offer_count": len(product.offers),
        "priced_offer_count": len(priced),
        "stores": sorted({o.store for o in product.offers}),
        "last_checked_at": max(last_checks).isoformat() + "Z" if last_checks else None,
    }


def product_payload(product: Product, include_offers: bool = True) -> dict:
    from .services.analysis import analyze_offer, brief, product_trend

    data = product.to_dict(include_offers=include_offers)
    analyses = {o.id: analyze_offer(o) for o in product.offers}
    if include_offers:
        hints = {o.id: match_hint(product, o) for o in product.offers}
        for o in data["offers"]:
            o["match"] = hints.get(o["id"])
            o["analysis"] = brief(analyses.get(o["id"]))
    data["summary"] = product_summary(product)
    best = data["summary"]["best_offer_id"]
    data["summary"]["analysis"] = brief(analyses.get(best)) if best else None
    data["summary"]["highlight"] = highlight(data["summary"])
    data["display_image_url"] = display_image(product, best)
    data["trend"] = product_trend(product)
    return data


def display_image(product: Product, best_offer_id: int | None) -> str | None:
    """Foto do produto; sem ela, a da melhor oferta (ou de qualquer loja)."""
    if product.image_url:
        return product.image_url
    offers = sorted(product.offers, key=lambda o: o.id != best_offer_id)
    return next((o.image_url for o in offers if o.image_url), None)


HIGHLIGHT_ORDER = {"target": 0, "great": 1, "good": 2}


def highlight(summary: dict) -> dict | None:
    """Produto com preço bom de verdade → destaque no site."""
    a = summary.get("analysis") or {}
    if summary.get("target_reached"):
        return {"reason": "target", "label": "Preço-alvo atingido"}
    if a.get("classification") == "great":
        return {"reason": "great", "label": "Ótima oportunidade"}
    if a.get("classification") == "good":
        return {"reason": "good", "label": "Boa oportunidade"}
    return None
