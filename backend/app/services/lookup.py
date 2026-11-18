"""Consulta de produtos nas lojas e gravação do resultado nas ofertas.

Consultas feitas na tela de cadastro ficam em cache por alguns minutos; ao salvar
o produto, o backend reaproveita esse resultado (o navegador nunca envia preços).
"""
from __future__ import annotations

import threading
import time

from ..adapters import LookupFailed, ProductData, get_adapter
from ..models import Offer, PriceHistory, utcnow
from ..stores import STORES, detect_store

CACHE_TTL_SECONDS = 15 * 60
_cache: dict[str, tuple[float, ProductData]] = {}
_cache_lock = threading.Lock()


def canonical(url: str, store: str | None = None) -> str:
    adapter = get_adapter(store or detect_store(url))
    return adapter.canonical_url(url) if adapter else url.strip()


def cached(url: str, store: str | None = None) -> ProductData | None:
    key = canonical(url, store)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    return None


_failures: dict[str, tuple[float, LookupFailed]] = {}


def cached_failure(url: str, store: str | None = None) -> LookupFailed | None:
    key = canonical(url, store)
    with _cache_lock:
        hit = _failures.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    return None


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
        _failures.clear()


def lookup(url: str, use_cache: bool = True) -> ProductData:
    """Consulta a loja (ou o cache). Lança LookupFailed com mensagem clara."""
    store = detect_store(url)
    adapter = get_adapter(store)
    if adapter is None:
        raise LookupFailed("unsupported", "Loja não suportada.")
    if use_cache:
        hit = cached(url, store)
        if hit:
            return hit
    try:
        data = adapter.fetch(url)
    except LookupFailed as err:
        with _cache_lock:
            _failures[adapter.canonical_url(url)] = (time.time(), err)
        raise
    with _cache_lock:
        _failures.pop(adapter.canonical_url(url), None)
        _cache[adapter.canonical_url(url)] = (time.time(), data)
        _cache[data.url] = (time.time(), data)
    return data


def fill_product_from_store(product, data: ProductData) -> None:
    """Completa só o que estiver vazio no produto (foto, marca, modelo, categoria) com dados da loja."""
    if product is None:
        return
    for field, value in (("image_url", data.image_url), ("brand", data.brand),
                         ("model", data.model), ("category", data.category)):
        if value and not getattr(product, field):
            setattr(product, field, value[:1000] if field == "image_url" else value[:160])


def apply_to_offer(offer: Offer, data: ProductData) -> None:
    """Grava o resultado de uma consulta real na oferta e no histórico."""
    now = utcnow()
    offer.title = data.name or offer.title
    offer.store_product_id = data.store_product_id or offer.store_product_id
    offer.brand = data.brand or offer.brand
    offer.model = data.model or offer.model
    offer.mpn = data.mpn or offer.mpn
    offer.gtin = data.gtin or offer.gtin
    offer.image_url = data.image_url or offer.image_url
    fill_product_from_store(offer.product, data)

    if data.price_cents is not None:
        if offer.current_price_cents is not None and offer.current_price_cents != data.price_cents:
            offer.previous_price_cents = offer.current_price_cents
        offer.current_price_cents = data.price_cents
    offer.list_price_cents = data.list_price_cents
    offer.installment_price_cents = data.installment_price_cents
    offer.price_source = "auto"
    offer.available = data.available
    offer.last_checked_at = now
    offer.last_status = "ok"
    offer.last_error = None

    offer.history.append(
        PriceHistory(
            price_cents=data.price_cents,
            list_price_cents=data.list_price_cents,
            available=data.available,
            source="auto",
            checked_at=now,
        )
    )


def record_failure(offer: Offer, err: LookupFailed) -> None:
    offer.last_checked_at = utcnow()
    offer.last_status = err.code if err.code in {"blocked", "not_found", "rate_limited", "unsupported"} else "error"
    offer.last_error = err.message


def check_offer(offer: Offer, use_cache: bool = False) -> bool:
    """Consulta uma oferta agora e grava o resultado. Retorna True se obteve dados."""
    try:
        data = lookup(offer.url, use_cache=use_cache)
    except LookupFailed as err:
        record_failure(offer, err)
        return False
    apply_to_offer(offer, data)
    return True


def lookup_result(url: str) -> dict:
    """Resposta da API /lookup: nunca lança, sempre explica o que aconteceu."""
    store = detect_store(url)
    base = {
        "url": url,
        "store": store,
        "store_name": STORES[store]["name"] if store else None,
    }
    try:
        data = lookup(url)
    except LookupFailed as err:
        return {**base, "status": err.code, "message": err.message, "data": None}
    return {
        **base,
        "url": data.url,
        "status": "ok",
        "message": None if data.price_cents is not None else "Produto identificado, mas a loja não informou o preço.",
        "data": data.to_dict(),
    }


def seed_offer_from_cache(offer: Offer) -> None:
    """Ao cadastrar, reaproveita uma consulta recente feita na tela de cadastro."""
    data = cached(offer.url, offer.store)
    if data:
        offer.url = data.url
        apply_to_offer(offer, data)
        return
    failure = cached_failure(offer.url, offer.store)
    if failure:
        record_failure(offer, failure)


__all__ = [
    "apply_to_offer",
    "cached",
    "canonical",
    "check_offer",
    "clear_cache",
    "lookup",
    "lookup_result",
    "seed_offer_from_cache",
]
