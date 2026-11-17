"""Detecção de mudanças relevantes a partir de consultas reais.

Cada evento representa uma *transição* (ex.: indisponível → disponível, alvo
não atingido → atingido), então o mesmo fato não se repete a cada consulta.
Oscilações pequenas (abaixo dos limites configurados) são ignoradas.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..extensions import db
from ..models import Offer, PriceEvent, PriceHistory, Product
from ..stores import STORES
from ..summary import product_summary

MIN_HISTORY_FOR_LOWEST = 3  # pontos anteriores necessários para afirmar "menor preço registrado"


def brl(cents: int | None) -> str:
    if cents is None:
        return "—"
    s = f"{cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def store_name(key: str | None) -> str:
    return STORES.get(key or "", {}).get("name", key or "")


@dataclass
class OfferSnapshot:
    price: int | None
    available: bool | None

    @classmethod
    def of(cls, offer: Offer) -> OfferSnapshot:
        return cls(offer.current_price_cents, offer.available)


@dataclass
class ProductSnapshot:
    best_price: int | None
    best_store: str | None
    best_offer_id: int | None
    target_reached: bool

    @classmethod
    def of(cls, product: Product) -> ProductSnapshot:
        s = product_summary(product)
        return cls(s["best_price_cents"], s["best_store"], s["best_offer_id"], s["target_reached"])


def _event(product: Product, offer: Offer | None, kind: str, old, new, message: str, source: str) -> PriceEvent:
    ev = PriceEvent(
        kind=kind,
        product_id=product.id,
        offer_id=offer.id if offer else None,
        store=offer.store if offer else None,
        old_price_cents=old,
        new_price_cents=new,
        message=message,
        source=source,
    )
    db.session.add(ev)
    return ev


def is_relevant_change(old: int, new: int, cfg: dict) -> bool:
    diff = abs(new - old)
    return diff >= cfg["min_change_cents"] and diff / old * 100 >= cfg["min_change_percent"]


def detect_offer_events(
    product: Product, offer: Offer, before: OfferSnapshot, cfg: dict, source: str = "auto"
) -> list[PriceEvent]:
    events: list[PriceEvent] = []
    name, st = product.name, store_name(offer.store)
    old, new = before.price, offer.current_price_cents
    tag = " (preço informado por você)" if source == "manual" else ""

    if old and new and old != new and is_relevant_change(old, new, cfg):
        pct = (new - old) / old * 100
        if new < old:
            events.append(_event(product, offer, "price_drop", old, new,
                f"{name}: caiu de {brl(old)} para {brl(new)} na {st} ({pct:.1f}%){tag}.", source))
            previous = [
                p for (p,) in db.session.execute(
                    db.select(PriceHistory.price_cents).where(
                        PriceHistory.offer_id == offer.id,
                        PriceHistory.price_cents.is_not(None),
                    ).order_by(PriceHistory.checked_at.desc(), PriceHistory.id.desc()).offset(1)
                ).all()
            ]
            if len(previous) >= MIN_HISTORY_FOR_LOWEST and new < min(previous):
                events.append(_event(product, offer, "lowest_ever", min(previous), new,
                    f"{name}: {brl(new)} é o menor preço registrado na {st} "
                    f"desde o início do monitoramento{tag}.", source))
        else:
            events.append(_event(product, offer, "price_increase", old, new,
                f"{name}: subiu de {brl(old)} para {brl(new)} na {st} (+{pct:.1f}%){tag}.", source))

    if before.available is False and offer.available is True:
        events.append(_event(product, offer, "back_in_stock", None, new,
            f"{name} voltou ao estoque na {st}" + (f" por {brl(new)}" if new else "") + f"{tag}.", source))
    elif before.available is True and offer.available is False:
        events.append(_event(product, offer, "out_of_stock", old, None,
            f"{name} ficou indisponível na {st}{tag}.", source))
    return events


def detect_product_events(product: Product, before: ProductSnapshot, source: str = "auto") -> list[PriceEvent]:
    events: list[PriceEvent] = []
    after = ProductSnapshot.of(product)
    offer = db.session.get(Offer, after.best_offer_id) if after.best_offer_id else None

    if after.target_reached and not before.target_reached and offer:
        events.append(_event(product, offer, "target_reached", product.target_price_cents, after.best_price,
            f"{product.name}: {brl(after.best_price)} na {store_name(after.best_store)} — "
            f"preço-alvo de {brl(product.target_price_cents)} atingido!", source))

    if (
        offer
        and before.best_store
        and after.best_store != before.best_store
        and before.best_price is not None
        and after.best_price is not None
        and after.best_price < before.best_price
    ):
        events.append(_event(product, offer, "better_store", before.best_price, after.best_price,
            f"{product.name}: melhor oferta agora na {store_name(after.best_store)} por "
            f"{brl(after.best_price)} (antes {brl(before.best_price)} na {store_name(before.best_store)}).",
            source))
    return events


def detect_analysis_events(product: Product, offer: Offer, source: str = "auto") -> list[PriceEvent]:
    """Eventos a partir da análise de preços: nova oportunidade ou possível promoção enganosa.

    Só dispara na transição (a classificação anterior fica salva na oferta).
    """
    from .analysis import analyze_offer

    db.session.flush()  # garante que o ponto recém-gravado entre na análise
    a = analyze_offer(offer)
    new, old = a["classification"], offer.last_classification
    offer.last_classification = new
    events: list[PriceEvent] = []
    if new == old:
        return events
    st = store_name(offer.store)
    if new == "great":
        events.append(_event(product, offer, "opportunity", a["metrics"]["baseline_cents"],
            offer.current_price_cents,
            f"{product.name}: ótima oportunidade na {st} por {brl(offer.current_price_cents)}. "
            + a["reasons"][-1], source))
    elif new == "misleading":
        events.append(_event(product, offer, "misleading_promo", a["metrics"]["baseline_cents"],
            offer.current_price_cents,
            f"{product.name} na {st}: possível promoção enganosa. " + a["reasons"][0], source))
    return events
