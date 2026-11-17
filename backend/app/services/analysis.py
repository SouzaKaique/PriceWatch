"""Inteligência de preços: compara o preço atual com o histórico REALMENTE coletado.

Princípios
- Só usa preços efetivamente registrados (consultas automáticas ou informados pelo
  usuário). Nada anterior ao início do monitoramento é estimado.
- Sem dados suficientes, a classificação é "dados insuficientes" — nunca um palpite.
- "Possível promoção enganosa" só aparece com evidência concreta, explicada em texto.

Como funciona
- Os preços são agregados por dia (mediana do dia, fuso de Brasília), para que um
  dia com muitas consultas não pese mais que outro.
- Preço habitual (linha de base) = mediana diária de 90 dias excluindo os últimos 7
  (ou, com menos histórico, 30 dias excluindo os últimos 3). Excluir os dias recentes
  impede que uma alta artificial recente "contamine" a referência.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from ..extensions import db
from ..models import Offer, PriceHistory, Product

TZ = ZoneInfo("America/Sao_Paulo")
WINDOWS = (7, 30, 90, 180)
# mínimo de dias com dados para cada janela ser considerada
MIN_DAYS = {7: 3, 30: 7, 90: 20, 180: 40}

# Limiares (frações)
GREAT_BELOW_BASELINE = 0.85  # 15% abaixo do habitual
GOOD_BELOW_BASELINE = 0.95  # 5% abaixo
RECORD_GREAT_BELOW_BASELINE = 0.90  # menor preço registrado + 10% abaixo do habitual
AVERAGE_BAND = 0.05  # ±5% = dentro da média
PUMP_MIN_RISE = 0.10  # alta de 10%+ sobre o habitual antes da "promoção"
INFLATED_LIST_PRICE = 0.10  # preço "de" 10%+ acima do habitual observado
STILL_AT_BASELINE = 0.98  # preço atual >= 98% do habitual = não ficou realmente mais barato
MEANINGFUL_ANNOUNCED = 0.05  # desconto anunciado a partir de 5%

LABELS = {
    "great": ("Ótima oportunidade", "green"),
    "good": ("Boa oportunidade", "green"),
    "average": ("Preço dentro da média", "muted"),
    "above": ("Acima do preço habitual", "orange"),
    "weak_discount": ("Desconto pouco vantajoso", "orange"),
    "misleading": ("Possível promoção enganosa", "red"),
    "insufficient": ("Dados insuficientes", "muted"),
}


# ---- Calendário promocional (Brasil) ----------------------------------------

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def promo_calendar(year: int) -> list[tuple[str, date, date]]:
    """(nome, início, fim) das principais datas promocionais do varejo brasileiro."""
    bf = _last_weekday(year, 11, 4)  # última sexta de novembro
    maes = _nth_weekday(year, 5, 6, 2)  # 2º domingo de maio
    pais = _nth_weekday(year, 8, 6, 2)  # 2º domingo de agosto
    return [
        ("Dia do Consumidor", date(year, 3, 15) - timedelta(days=3), date(year, 3, 15) + timedelta(days=3)),
        ("Dia das Mães", maes - timedelta(days=10), maes),
        ("Dia dos Pais", pais - timedelta(days=10), pais),
        ("Dia das Crianças", date(year, 10, 5), date(year, 10, 12)),
        ("Black Friday", bf - timedelta(days=3), bf + timedelta(days=3)),  # até a Cyber Monday
        ("Natal", date(year, 12, 10), date(year, 12, 24)),
    ]


def promo_context(today: date, lookahead_days: int = 45) -> dict | None:
    """Data promocional em andamento ou nos próximos `lookahead_days` dias."""
    events = promo_calendar(today.year) + promo_calendar(today.year + 1)
    for name, start, end in sorted(events, key=lambda e: e[1]):
        if start <= today <= end:
            return {"name": name, "start": start.isoformat(), "end": end.isoformat(), "days_until": 0, "ongoing": True}
        if today < start <= today + timedelta(days=lookahead_days):
            return {
                "name": name,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "days_until": (start - today).days,
                "ongoing": False,
            }
    return None


# ---- Agregação ----------------------------------------------------------------

@dataclass
class Point:
    at: datetime  # UTC ingênuo (como no banco)
    price: int
    source: str


def _local_day(dt: datetime) -> date:
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ).date()


def daily(points: list[Point]) -> list[tuple[date, int]]:
    days: dict[date, list[int]] = {}
    for p in points:
        days.setdefault(_local_day(p.at), []).append(p.price)
    return [(d, int(median(v))) for d, v in sorted(days.items())]


def window_stats(days: list[tuple[date, int]], today: date, window: int) -> dict:
    sel = [(d, p) for d, p in days if d > today - timedelta(days=window)]
    prices = [p for _, p in sel]
    sufficient = len(sel) >= MIN_DAYS[window] and bool(sel) and sel[0][0] <= today - timedelta(days=window // 2)
    return {
        "days_with_data": len(sel),
        "sufficient": sufficient,
        "avg_cents": int(sum(prices) / len(prices)) if prices else None,
        "min_cents": min(prices) if prices else None,
        "max_cents": max(prices) if prices else None,
    }


def baseline(days: list[tuple[date, int]], today: date) -> tuple[int | None, str | None]:
    for window, exclude, min_days in ((90, 7, 7), (30, 3, 5)):
        sel = [p for d, p in days if today - timedelta(days=window) < d <= today - timedelta(days=exclude)]
        if len(sel) >= min_days:
            return int(median(sel)), f"mediana de {window} dias, sem os últimos {exclude}"
    return None, None


# ---- Análise ------------------------------------------------------------------

def _brl(c: int | None) -> str:
    if c is None:
        return "—"
    return "R$ " + f"{c / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%".replace(".", ",")


def offer_points(offer_id: int) -> list[Point]:
    rows = db.session.execute(
        db.select(PriceHistory.checked_at, PriceHistory.price_cents, PriceHistory.source)
        .where(PriceHistory.offer_id == offer_id, PriceHistory.price_cents.is_not(None))
        .order_by(PriceHistory.checked_at, PriceHistory.id)
    ).all()
    return [Point(at, price, source or "auto") for at, price, source in rows]


def analyze(
    current: int | None,
    points: list[Point],
    list_price: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Analisa uma série de preços. `current` é o preço atual da oferta."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    today = _local_day(now)
    days = daily(points)
    windows = {str(w): window_stats(days, today, w) for w in WINDOWS}
    base, base_desc = baseline(days, today)
    promo = promo_context(today)

    prev_points = points[:-1] if points and points[-1].price == current else points
    lowest = min(points, key=lambda p: p.price) if points else None
    lowest_before = min((p.price for p in prev_points), default=None)
    highest = max((p.price for p in points), default=None)
    first = points[0].at if points else None
    span_days = (today - _local_day(first)).days + 1 if first else 0

    announced = (list_price - current) / list_price if list_price and current and list_price > current else None
    real = (base - current) / base if base and current else None

    metrics = {
        "current_cents": current,
        "baseline_cents": base,
        "baseline_method": base_desc,
        "lowest": (
            {"price_cents": lowest.price, "at": lowest.at.isoformat() + "Z", "source": lowest.source} if lowest else None
        ),
        "highest_cents": highest,
        "windows": windows,
        "announced_list_price_cents": list_price if announced else None,
        "announced_discount_pct": round(announced * 100, 1) if announced else None,
        "real_discount_pct": round(real * 100, 1) if real is not None else None,
        "monitored_days": span_days,
        "days_with_data": len(days),
    }
    result = {"metrics": metrics, "promo_context": promo}

    def done(key: str, reasons: list[str]) -> dict:
        label, tone = LABELS[key]
        return {**result, "classification": key, "label": label, "tone": tone, "reasons": reasons}

    if current is None:
        return done("insufficient", ["Ainda não há preço atual para esta oferta."])

    if base is None:
        reasons = [
            f"O histórico tem {len(days)} dia(s) com preço registrado; a comparação com o preço "
            "habitual fica disponível a partir de 5 a 7 dias de monitoramento.",
        ]
        if announced and announced >= MEANINGFUL_ANNOUNCED:
            reasons.append(
                f"A loja anuncia {_pct(announced)} de desconto sobre {_brl(list_price)}, mas ainda não há "
                "histórico suficiente para confirmar se esse preço anterior era praticado."
            )
        return done("insufficient", reasons)

    reasons: list[str] = []

    # 1) Indícios de promoção enganosa (exige evidência no histórico)
    misleading: list[str] = []
    if announced and list_price > base * (1 + INFLATED_LIST_PRICE) and current >= base * STILL_AT_BASELINE:
        misleading.append(
            f"A loja anuncia {_brl(list_price)} como preço anterior ({_pct(announced)} de desconto), mas o preço "
            f"habitual observado foi {_brl(base)}. A redução real é de {_pct(max(real, 0))}."
            if real and real > 0
            else f"A loja anuncia {_brl(list_price)} como preço anterior ({_pct(announced)} de desconto), mas o "
            f"preço habitual observado foi {_brl(base)} — o preço atual não está abaixo dele."
        )
    recent = [(d, p) for d, p in days if today - timedelta(days=30) < d < today]
    if recent:
        peak_day, peak = max(recent, key=lambda x: x[1])
        if peak >= base * (1 + PUMP_MIN_RISE) and current < peak * 0.97 and current >= base * STILL_AT_BASELINE:
            text = (
                f"O preço subiu de {_brl(base)} (habitual) para {_brl(peak)} em {peak_day.strftime('%d/%m')} "
                f"e depois \"caiu\" para {_brl(current)} — ainda "
                + ("acima do" if current > base * 1.02 else "no nível do")
                + " preço habitual. Padrão de aumento seguido de redução."
            )
            if promo:
                text += f" A alta ocorreu perto da {promo['name']}."
            misleading.append(text)
    if misleading:
        return done("misleading", misleading)

    # 2) Oportunidades
    is_record = lowest_before is not None and current < lowest_before and span_days >= 7
    record_text = (
        f"{_brl(current)} é o menor preço registrado desde o início do monitoramento "
        f"(anterior: {_brl(lowest_before)})."
    )
    # Recorde só vira "ótima" se também for uma redução relevante sobre o habitual.
    if current <= base * GREAT_BELOW_BASELINE or (is_record and current <= base * RECORD_GREAT_BELOW_BASELINE):
        if is_record:
            reasons.append(record_text)
        reasons.append(f"Está {_pct(real)} abaixo do preço habitual ({_brl(base)}).")
        return done("great", reasons)
    if current <= base * GOOD_BELOW_BASELINE:
        reasons = [f"Está {_pct(real)} abaixo do preço habitual ({_brl(base)})."]
        if is_record:
            reasons.insert(0, record_text)
        return done("good", reasons)

    # 3) Desconto anunciado que não se traduz em preço menor
    week_ago = [p for d, p in days if today - timedelta(days=8) < d <= today - timedelta(days=1)]
    recent_drop = week_ago and max(week_ago) > current * 1.05
    if (announced and announced >= MEANINGFUL_ANNOUNCED) or recent_drop:
        if announced and announced >= MEANINGFUL_ANNOUNCED:
            reasons.append(
                f"A loja anuncia {_pct(announced)} de desconto, mas em relação ao preço habitual "
                f"({_brl(base)}) "
                + (f"a redução real é de apenas {_pct(real)}." if real > 0 else "não há redução real.")
            )
        else:
            reasons.append(
                f"O preço caiu nos últimos dias, mas voltou apenas ao nível habitual ({_brl(base)})."
            )
        return done("weak_discount", reasons)

    # 4) Média / acima
    if current > base * (1 + AVERAGE_BAND):
        reasons.append(f"Está {_pct(-real)} acima do preço habitual ({_brl(base)}).")
        if promo and not promo["ongoing"]:
            reasons.append(
                f"Faltam {promo['days_until']} dias para a {promo['name']}: aumentos nesse período "
                "podem servir de base para \"descontos\" depois — compare com o habitual."
            )
        return done("above", reasons)
    reasons = [f"Está próximo do preço habitual ({_brl(base)})."]
    if is_record:
        reasons.append(record_text + " A diferença, porém, é pequena.")
    return done("average", reasons)


def analyze_offer(offer: Offer, now: datetime | None = None) -> dict:
    return analyze(offer.current_price_cents, offer_points(offer.id), offer.list_price_cents, now)


def analyze_product(product: Product, now: datetime | None = None) -> dict:
    """Análise por oferta + resumo do produto (baseado na oferta de menor preço)."""
    from ..summary import product_summary

    per_offer = {o.id: analyze_offer(o, now) for o in product.offers}
    best_id = product_summary(product)["best_offer_id"]
    lowest_all = None
    for o in product.offers:
        lo = per_offer[o.id]["metrics"]["lowest"]
        if lo and (lowest_all is None or lo["price_cents"] < lowest_all["price_cents"]):
            lowest_all = {**lo, "store": o.store}
    return {
        "best_offer_id": best_id,
        "overall": per_offer.get(best_id) if best_id else None,
        "lowest_overall": lowest_all,
        "offers": {str(k): v for k, v in per_offer.items()},
        "promo_context": promo_context(_local_day(now or datetime.now(timezone.utc).replace(tzinfo=None))),
    }


def brief(analysis: dict | None) -> dict | None:
    """Versão curta para cards/listas."""
    if not analysis:
        return None
    return {
        "classification": analysis["classification"],
        "label": analysis["label"],
        "tone": analysis["tone"],
        "headline": analysis["reasons"][0] if analysis["reasons"] else None,
    }
