"""Indica se uma oferta parece ser o mesmo produto cadastrado.

É apenas uma sugestão baseada em marca, modelo, código do fabricante e EAN.
A decisão final é sempre do usuário (campo `match_confirmed`).
"""
from __future__ import annotations

import re

from ..models import Offer, Product


def _norm(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def match_hint(product: Product, offer: Offer) -> dict:
    if offer.last_status != "ok" and not offer.title:
        return {"level": "unknown", "reasons": ["Oferta ainda não consultada."]}

    reasons: list[str] = []
    title = _norm(offer.title)
    p_code, p_model, p_brand = _norm(product.manufacturer_code), _norm(product.model), _norm(product.brand)
    o_codes = {c for c in (_norm(offer.mpn), _norm(offer.model)) if c}

    if p_brand and offer.brand and _norm(offer.brand) != p_brand and p_brand not in title:
        return {"level": "mismatch", "reasons": [f"Marca diferente: {offer.brand} × {product.brand}."]}

    strong = False
    for label, code in (("Código do fabricante", p_code), ("Modelo", p_model)):
        if len(code) < 4:
            continue
        if code in o_codes:
            reasons.append(f"{label} idêntico.")
            strong = True
        elif code in title:
            reasons.append(f"{label} encontrado no título da oferta.")
            strong = True

    if strong:
        return {"level": "strong", "reasons": reasons}

    if (p_code or p_model) and o_codes:
        return {
            "level": "mismatch",
            "reasons": [f"Modelo da oferta ({offer.mpn or offer.model}) difere do cadastrado."],
        }

    if p_brand and (p_brand == _norm(offer.brand) or p_brand in title):
        return {"level": "possible", "reasons": ["Mesma marca; modelo não pôde ser comparado."]}
    return {"level": "unknown", "reasons": ["Dados insuficientes para comparar — confira manualmente."]}
