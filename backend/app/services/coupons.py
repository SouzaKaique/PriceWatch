"""Cupons: coleta em fonte oficial, condições e estimativa de preço.

Fonte automática (verificada em 17/11/2026)
- KaBuM!: a página oficial https://www.kabum.com.br/hotsite/cupons/ carrega a lista a
  partir de uma planilha pública indicada no próprio script da página
  (/hotsite/cupons/js/script.js). O PRICE WATCH lê o script para descobrir esse endereço
  (se a loja mudar, acompanha) e lê a lista no máximo a cada 6 horas.
- Pichau, Mercado Livre e Amazon: sem fonte pública oficial acessível (exigem login,
  bloqueiam consultas ou usam cupons "de clicar" sem código). Cadastro manual.

Nada aqui afirma que um cupom funciona: todo cupom começa como "não confirmado".
A aplicabilidade a um produto só é afirmada quando a própria loja aponta o produto.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from ..adapters import LookupFailed
from ..adapters.http import get_html, get_text
from ..extensions import db
from ..models import Coupon, Offer, PriceEvent, Product, Setting, utcnow
from ..stores import STORES

log = logging.getLogger(__name__)

KABUM_HOTSITE = "https://www.kabum.com.br/hotsite/cupons/"
KABUM_SCRIPT = "https://www.kabum.com.br/hotsite/cupons/js/script.js"
SHEET_RE = re.compile(r"https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+/gviz/tq\?(?=['\"])")
REFRESH_EVERY = timedelta(hours=6)


# ---- Interpretação ------------------------------------------------------------

def parse_advantage(text: str | None) -> tuple[float | None, int | None]:
    """'10% OFF' → (10.0, None); 'R$50 OFF' / 'R$ 1.200 OFF' → (None, 5000 / 120000)."""
    if not text:
        return None, None
    t = text.upper().replace(" ", "")
    m = re.search(r"(\d+(?:[.,]\d+)?)%", t)
    if m:
        return float(m.group(1).replace(",", ".")), None
    m = re.search(r"R\$(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?", t)
    if m:
        reais = int(m.group(1).replace(".", ""))
        return None, reais * 100 + int(m.group(2) or 0)
    return None, None


def _parse_dt(value) -> datetime | None:
    """ISO com fuso (ex.: 2026-11-16T09:00:00-03:00) → UTC ingênuo."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=-3)))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_kabum_sheet(raw: str) -> list[dict]:
    """Resposta gviz → lista de cupons. Colunas (mesma ordem usada pelo site da loja):
    0 imagem, 1 início, 2 fim, 3 código, 4 vantagem, 5 condição, 6 link, 7 texto legal."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise LookupFailed("parse", "Formato inesperado da lista de cupons da KaBuM!.")
    try:
        rows = json.loads(raw[start : end + 1])["table"]["rows"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LookupFailed("parse", "Formato inesperado da lista de cupons da KaBuM!.") from exc

    def cell(row, i):
        c = row.get("c") or []
        v = (c[i] or {}).get("v") if i < len(c) and c[i] else None
        return v.strip() if isinstance(v, str) else v

    out = []
    for row in rows[1:]:  # a 1ª linha é o cabeçalho (o site da loja também a ignora)
        code = cell(row, 3)
        if not code or not re.fullmatch(r"[A-Za-z0-9_-]{3,40}", str(code)):
            continue  # linha vazia ou inválida
        if _parse_dt(cell(row, 2)) is None:
            continue  # sem data final legível: não dá para saber se está vigente
        pct, cents = parse_advantage(cell(row, 4))
        out.append(
            {
                "code": str(code).upper(),
                "valid_from": _parse_dt(cell(row, 1)),
                "valid_until": _parse_dt(cell(row, 2)),
                "advantage": cell(row, 4),
                "discount_percent": pct,
                "discount_cents": cents,
                "description": cell(row, 5),
                "link_url": cell(row, 6),
                "conditions": cell(row, 7),
            }
        )
    return out


# ---- Coleta -------------------------------------------------------------------

def _last_fetch() -> datetime | None:
    row = db.session.get(Setting, "coupons.kabum.last_fetch")
    return datetime.fromisoformat(row.value) if row and row.value else None


def _set_last_fetch(dt: datetime, error: str | None) -> None:
    for key, value in (("coupons.kabum.last_fetch", dt.isoformat()), ("coupons.kabum.last_error", error)):
        row = db.session.get(Setting, key)
        if row:
            row.value = value
        else:
            db.session.add(Setting(key=key, value=value))


def source_status() -> dict:
    err = db.session.get(Setting, "coupons.kabum.last_error")
    last = _last_fetch()
    return {
        "kabum": {
            "source": KABUM_HOTSITE,
            "last_fetch_at": last.isoformat() + "Z" if last else None,
            "last_error": err.value if err else None,
            "next_allowed_at": (last + REFRESH_EVERY).isoformat() + "Z" if last else None,
        }
    }


def fetch_kabum_coupons() -> list[dict]:
    script, _ = get_html(KABUM_SCRIPT, "KaBuM!")
    m = SHEET_RE.search(script)
    if not m:
        raise LookupFailed("parse", "Não encontrei a origem da lista de cupons na página oficial da KaBuM!.")
    return parse_kabum_sheet(get_text(m.group(0), "Lista de cupons da KaBuM!"))


def refresh_official(force: bool = False) -> dict:
    """Atualiza os cupons oficiais da KaBuM! (no máximo a cada 6 h, salvo `force`)."""
    now = utcnow()
    last = _last_fetch()
    if not force and last and now - last < REFRESH_EVERY:
        return {"fetched": False, "reason": "recent", **source_status()}
    try:
        items = fetch_kabum_coupons()
    except LookupFailed as err:
        _set_last_fetch(now, err.message)
        db.session.commit()
        log.warning("Cupons KaBuM!: %s", err.message)
        return {"fetched": False, "reason": "error", "message": err.message, **source_status()}

    new_ids = []
    for it in items:
        key = f"kabum:{it['code']}:{it['valid_from'].isoformat() if it['valid_from'] else ''}"
        c = db.session.scalar(db.select(Coupon).where(Coupon.external_key == key))
        is_new = c is None
        if is_new:
            c = Coupon(store="kabum", code=it["code"], origin="kabum_official", external_key=key,
                       verification_status="unconfirmed")
            db.session.add(c)
        c.description = (it["description"] or it["advantage"] or "")[:400]
        c.discount_percent = it["discount_percent"]
        c.discount_cents = it["discount_cents"]
        c.valid_from, c.valid_until = it["valid_from"], it["valid_until"]
        c.link_url = (it["link_url"] or "")[:1500] or None
        c.conditions = it["conditions"]
        c.source = f"Página oficial de cupons da KaBuM! ({KABUM_HOTSITE})"
        c.last_seen_at = now
        if is_new:
            db.session.flush()
            new_ids.append(c.id)

    _set_last_fetch(now, None)
    events = create_coupon_events(new_ids)
    db.session.commit()
    log.info("Cupons KaBuM!: %s lidos, %s novos, %s alertas.", len(items), len(new_ids), events)
    return {"fetched": True, "total": len(items), "new": len(new_ids), "events": events, **source_status()}


# ---- Aplicabilidade e estimativa -----------------------------------------------

def _kabum_product_id(url: str | None) -> str | None:
    m = re.search(r"kabum\.com\.br/produto/(\d+)", url or "")
    return m.group(1) if m else None


def _norm(s: str | None) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def applicability(coupon: Coupon, offer: Offer, product: Product) -> dict:
    """{'level': applies|possible|unknown|excluded, 'reasons': [...]}"""
    reasons: list[str] = []
    if coupon.store != offer.store:
        return {"level": "excluded", "reasons": ["Cupom de outra loja."]}
    price = offer.current_price_cents
    if coupon.min_purchase_cents and price is not None and price < coupon.min_purchase_cents:
        return {"level": "excluded", "reasons": [f"Exige compra mínima de R$ {coupon.min_purchase_cents / 100:,.2f}."
                                                 .replace(",", "X").replace(".", ",").replace("X", ".")]}

    cat = _norm(product.category)
    cond = _norm(coupon.conditions)
    if cat and cond:
        m = re.search(r"nao e valido para ([^.]*)", cond)
        if m and cat.rstrip("s") in m.group(1):
            return {"level": "excluded", "reasons": [f"As condições excluem a categoria \"{product.category}\"."]}

    linked = _kabum_product_id(coupon.link_url) if coupon.store == "kabum" else None
    offer_pid = offer.store_product_id or _kabum_product_id(offer.url)
    if linked:
        if offer_pid and linked == str(offer_pid):
            return {"level": "applies", "reasons": ["A loja indica este produto na página do cupom."]}
        return {"level": "excluded", "reasons": ["O cupom é para outro produto específico."]}

    # "em SSD selecionados", "em Processadores selecionados", "em produtos selecionados"…
    desc = _norm(coupon.description)
    target = None
    m = re.search(r"\bem (.+?) selecionad[oa]s?\b", desc)
    if m:
        target = m.group(1).strip()
    elif desc and "selecionad" not in desc and len(desc) <= 40:
        target = desc.removeprefix("em ").strip()
    generic = not target or target in {"produtos", "produto", "itens", "item", "todo o site", "todos os produtos"}
    if not generic:
        haystack = f"{cat} {_norm(product.name)}"
        stem = target.rstrip("s")
        words = [w.rstrip("s") for w in re.findall(r"[a-z0-9]{3,}", target)]
        if stem in haystack or (words and all(w in haystack for w in words)):
            reasons.append(f"Vale para \"{coupon.description.strip()}\" — combina com este produto; "
                           "confira se ele está na listagem da promoção.")
            return {"level": "possible", "reasons": reasons}
        return {"level": "excluded", "reasons": [f"Cupom para \"{coupon.description.strip()}\"."]}
    if "primeira compra" in cond:
        reasons.append("Válido apenas para a primeira compra na loja.")
    reasons.append("Não foi possível confirmar se este produto participa — confira no carrinho.")
    return {"level": "unknown", "reasons": reasons}


def estimate(coupon: Coupon, price_cents: int | None) -> int | None:
    if price_cents is None:
        return None
    if coupon.discount_percent:
        off = round(price_cents * coupon.discount_percent / 100)
        if coupon.max_discount_cents:
            off = min(off, coupon.max_discount_cents)
    elif coupon.discount_cents:
        off = coupon.discount_cents
    else:
        return None
    return max(price_cents - off, 0)


def coupons_for_product(product: Product) -> list[dict]:
    stores = {o.store for o in product.offers}
    if not stores:
        return []
    coupons = db.session.scalars(
        db.select(Coupon).where(Coupon.store.in_(stores)).order_by(Coupon.valid_until.is_(None), Coupon.valid_until)
    ).all()
    out = []
    for c in coupons:
        if c.validity() != "active" or c.verification_status == "user_failed":
            continue
        per_offer = []
        for o in product.offers:
            if o.store != c.store:
                continue
            ap = applicability(c, o, product)
            if ap["level"] == "excluded":
                continue
            per_offer.append({"offer_id": o.id, "store": o.store, "applicability": ap,
                              "price_cents": o.current_price_cents,
                              "estimated_cents": estimate(c, o.current_price_cents)})
        if per_offer:
            out.append({"coupon": c.to_dict(), "offers": per_offer})
    rank = {"applies": 0, "possible": 1, "unknown": 2}
    out.sort(key=lambda x: min(rank[o["applicability"]["level"]] for o in x["offers"]))
    return out


def create_coupon_events(coupon_ids: list[int], product_ids: list[int] | None = None) -> int:
    """Alerta só quando o cupom se aplica (ou provavelmente se aplica) a um produto monitorado."""
    if not coupon_ids:
        return 0
    count = 0
    q = db.select(Product).where(Product.active.is_(True))
    if product_ids is not None:
        q = q.where(Product.id.in_(product_ids))
    products = db.session.scalars(q).all()
    for cid in coupon_ids:
        c = db.session.get(Coupon, cid)
        if c is None or c.validity() != "active":
            continue
        for p in products:
            for o in p.offers:
                if o.store != c.store:
                    continue
                ap = applicability(c, o, p)
                if ap["level"] not in ("applies", "possible"):
                    continue
                est = estimate(c, o.current_price_cents)
                store = STORES.get(c.store, {}).get("name", c.store)
                price_txt = (
                    " — estimativa " + f"R$ {est / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    if est is not None else ""
                )
                db.session.add(PriceEvent(
                    kind="coupon_available", product_id=p.id, offer_id=o.id, store=c.store,
                    old_price_cents=o.current_price_cents, new_price_cents=est,
                    message=(f"{p.name}: cupom {c.code} ({c.description or 'desconto'}) na {store}"
                             f"{price_txt}. Cupom não confirmado — "
                             + ("a loja indica este produto." if ap["level"] == "applies" else "confira a listagem.")),
                ))
                count += 1
    return count


def events_for_new_product(product: Product) -> int:
    """Produto recém-cadastrado: avisa sobre cupons ativos que já se aplicam a ele."""
    stores = {o.store for o in product.offers}
    ids = [
        c.id
        for c in db.session.scalars(db.select(Coupon).where(Coupon.store.in_(stores)))
        if c.validity() == "active" and c.verification_status != "user_failed"
    ]
    return create_coupon_events(ids, [product.id])
