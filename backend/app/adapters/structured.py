"""Extrai dados de produto publicados pela própria loja na página:
JSON-LD (schema.org/Product), OpenGraph e microdados. É o mesmo conteúdo
que as lojas disponibilizam para buscadores.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

IN_STOCK = {"instock", "limitedavailability", "onlineonly", "preorder", "presale", "instoreonly"}
OUT_OF_STOCK = {"outofstock", "soldout", "discontinued", "backorder"}


def parse_price(value) -> int | None:
    """Converte "1299.90", 1299.9, "1.299,90" ou "R$ 1.299,90" em centavos."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        d = Decimal(str(value))
    else:
        s = re.sub(r"[^\d.,]", "", str(value))
        if not s:
            return None
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            d = Decimal(s)
        except InvalidOperation:
            return None
    if d <= 0:
        return None
    return int((d * 100).quantize(Decimal("1")))


def parse_availability(value) -> bool | None:
    if not value:
        return None
    key = str(value).rsplit("/", 1)[-1].lower()
    if key in IN_STOCK:
        return True
    if key in OUT_OF_STOCK:
        return False
    return None


def _iter_jsonld(soup: BeautifulSoup):
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, dict):
                if "@graph" in item and isinstance(item["@graph"], list):
                    stack.extend(item["@graph"])
                yield item
            elif isinstance(item, list):
                stack.extend(item)


def _types(item: dict) -> set[str]:
    t = item.get("@type")
    return {x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


def _text(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _image(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl")
    return _text(value)


def _offer_fields(offers) -> dict:
    if isinstance(offers, list):
        candidates = [o for o in offers if isinstance(o, dict)]
        priced = [o for o in candidates if parse_price(o.get("price") or o.get("lowPrice"))]
        offers = min(priced, key=lambda o: parse_price(o.get("price") or o.get("lowPrice"))) if priced else (candidates[0] if candidates else None)
    if not isinstance(offers, dict):
        return {}
    price = parse_price(offers.get("price"))
    if price is None:
        price = parse_price(offers.get("lowPrice"))
    if price is None and isinstance(offers.get("priceSpecification"), dict):
        price = parse_price(offers["priceSpecification"].get("price"))
    currency = (offers.get("priceCurrency") or "BRL").upper()
    if currency != "BRL":
        price = None  # nunca converter moeda por estimativa
    return {"price_cents": price, "available": parse_availability(offers.get("availability"))}


def extract(html: str) -> dict:
    """Retorna um dicionário com os campos encontrados (ausentes = não informados)."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {}
    breadcrumb: list[str] = []
    variations: list[str] = []

    for item in _iter_jsonld(soup):
        types = _types(item)
        if "breadcrumblist" in types and not breadcrumb:
            elements = sorted(
                (e for e in item.get("itemListElement", []) if isinstance(e, dict)),
                key=lambda e: e.get("position", 0),
            )
            breadcrumb = [n for n in (_text(e.get("name") or e.get("item")) for e in elements) if n]
        if "productgroup" in types:
            for v in item.get("hasVariant") or []:
                if isinstance(v, dict) and _text(v.get("name")):
                    variations.append(_text(v.get("name")))
        if ("product" in types or "productgroup" in types) and "name" not in out:
            out.update(
                {
                    "name": _text(item.get("name")),
                    "brand": _text(item.get("brand")),
                    "model": _text(item.get("model")),
                    "mpn": _text(item.get("mpn")),
                    "gtin": _text(
                        item.get("gtin13") or item.get("gtin") or item.get("gtin14") or item.get("gtin12") or item.get("ean")
                    ),
                    "sku": _text(item.get("sku") or item.get("productID")),
                    "image_url": _image(item.get("image")),
                    "category": _text(item.get("category")),
                }
            )
            out.update(_offer_fields(item.get("offers")))
            if "productgroup" in types and out.get("price_cents") is None:
                for v in item.get("hasVariant") or []:
                    if isinstance(v, dict):
                        f = _offer_fields(v.get("offers"))
                        if f.get("price_cents"):
                            out.update(f)
                            break

    def meta(*names: str) -> str | None:
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n}) or soup.find("meta", attrs={"itemprop": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    # OpenGraph / microdados como complemento
    out["name"] = out.get("name") or meta("og:title", "twitter:title")
    out["image_url"] = out.get("image_url") or meta("og:image", "twitter:image")
    if out.get("price_cents") is None:
        currency = (meta("product:price:currency", "og:price:currency", "priceCurrency") or "BRL").upper()
        if currency == "BRL":
            out["price_cents"] = parse_price(meta("product:price:amount", "og:price:amount", "price"))
    if out.get("available") is None:
        out["available"] = parse_availability(meta("product:availability", "og:availability", "availability"))

    if not out.get("category") and len(breadcrumb) >= 3:
        # [Início, Departamento, Categoria, ...] → usa a categoria principal
        out["category"] = breadcrumb[2]
    if variations:
        out["variations"] = variations[:20]
    return {k: v for k, v in out.items() if v not in (None, "", [])}
