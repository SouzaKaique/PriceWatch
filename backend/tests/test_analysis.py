"""Cenários da análise de preços com históricos sintéticos (apenas nos testes)."""
from datetime import date, datetime, timedelta

from app.services.analysis import Point, analyze, promo_calendar, promo_context

NOW = datetime(2026, 9, 1, 15, 0)  # longe de datas promocionais (exceto quando indicado)


def series(*segments: tuple[int, int], now: datetime = NOW) -> list[Point]:
    """segments = (dias, preço em reais), do mais antigo ao mais recente; 1 ponto por dia."""
    total = sum(d for d, _ in segments)
    pts, day = [], total - 1
    for days, price in segments:
        for _ in range(days):
            pts.append(Point(now - timedelta(days=day), price * 100, "auto"))
            day -= 1
    return pts


def test_spec_example_is_possible_misleading_promotion():
    # 30 dias atrás R$ 899, 20 dias R$ 899, 10 dias R$ 1.199, hoje R$ 999 (anunciado "de 1.199")
    pts = series((20, 899), (10, 1199), (1, 999))
    a = analyze(99900, pts, list_price=119900, now=NOW)
    assert a["classification"] == "misleading"
    assert a["label"] == "Possível promoção enganosa"
    text = " ".join(a["reasons"])
    assert "R$ 899,00" in text and "R$ 1.199,00" in text
    assert a["metrics"]["baseline_cents"] == 89900
    assert a["metrics"]["announced_discount_pct"] == 16.7
    assert a["metrics"]["real_discount_pct"] < 0  # ficou mais caro que o habitual


def test_inflated_list_price_without_pump():
    pts = series((40, 500), (1, 499))
    a = analyze(49900, pts, list_price=79900, now=NOW)
    assert a["classification"] == "misleading"
    assert "preço habitual observado foi R$ 500,00" in a["reasons"][0]


def test_genuine_drop_is_great_opportunity():
    pts = series((40, 1000), (1, 820))
    a = analyze(82000, pts, list_price=100000, now=NOW)
    assert a["classification"] == "great"
    assert any("menor preço registrado" in r for r in a["reasons"])


def test_good_opportunity():
    pts = series((20, 1000), (10, 980), (1, 940))
    assert analyze(94000, pts, now=NOW)["classification"] == "good"


def test_average_and_above():
    pts = series((30, 1000), (1, 1010))
    assert analyze(101000, pts, now=NOW)["classification"] == "average"
    pts = series((30, 1000), (1, 1100))
    assert analyze(110000, pts, now=NOW)["classification"] == "above"


def test_weak_discount_announced_but_price_usual():
    pts = series((30, 1000), (1, 995))
    a = analyze(99500, pts, list_price=110000, now=NOW)  # "de" só 10% acima → não chega a enganoso
    assert a["classification"] == "weak_discount"


def test_insufficient_history_never_guesses():
    pts = series((2, 1000), (1, 700))
    a = analyze(70000, pts, list_price=120000, now=NOW)
    assert a["classification"] == "insufficient"
    assert "ainda não há histórico suficiente" in " ".join(a["reasons"])
    assert a["metrics"]["baseline_cents"] is None


def test_windows_need_enough_days():
    pts = series((10, 1000))
    w = analyze(100000, pts, now=NOW)["metrics"]["windows"]
    assert w["7"]["sufficient"] is True
    assert w["30"]["sufficient"] is False  # só 10 dias de um mês
    assert w["90"]["avg_cents"] == 100000 and w["90"]["sufficient"] is False


def test_daily_median_prevents_many_samples_from_dominating():
    pts = series((10, 1000))
    # 12 consultas no mesmo dia com um pico isolado não mudam o preço do dia
    pts += [Point(NOW - timedelta(days=5, hours=h), 150000 if h == 1 else 100000, "auto") for h in range(12)]
    assert analyze(100000, sorted(pts, key=lambda p: p.at), now=NOW)["metrics"]["windows"]["30"]["max_cents"] == 100000


def test_promo_calendar_black_friday():
    names = {n: (s, e) for n, s, e in promo_calendar(2026)}
    assert names["Black Friday"][0] <= date(2026, 11, 27) <= names["Black Friday"][1]
    ctx = promo_context(date(2026, 11, 17))
    assert ctx["name"] == "Black Friday" and ctx["days_until"] == 7


def test_above_before_black_friday_warns():
    now = datetime(2026, 11, 10, 15, 0)
    pts = series((30, 1000), (1, 1150), now=now)
    a = analyze(115000, pts, now=now)
    assert a["classification"] == "above"
    assert any("Black Friday" in r for r in a["reasons"])


def test_api_analysis_and_events(client, fake_web):
    """Integração: monitoramento gera evento de oportunidade a partir do histórico."""
    from app.extensions import db
    from app.models import Offer, PriceHistory

    from .test_monitor import set_kabum_price

    pid = client.post(
        "/api/products", json={"name": "Monitor", "offers": [{"url": "https://www.kabum.com.br/produto/644868"}]}
    ).get_json()["id"]
    with client.application.app_context():
        offer = db.session.scalars(db.select(Offer).where(Offer.product_id == pid)).one()
        start = datetime.utcnow() - timedelta(days=40)
        for i in range(40):
            db.session.add(PriceHistory(offer_id=offer.id, price_cents=46900, available=True,
                                        checked_at=start + timedelta(days=i)))
        offer.current_price_cents = 46900
        db.session.commit()

    set_kabum_price(fake_web, 379.0)  # -19%
    client.post("/api/monitor/run")
    kinds = [e["kind"] for e in client.get(f"/api/events?product_id={pid}").get_json()]
    assert "opportunity" in kinds and "price_drop" in kinds

    full = client.get(f"/api/products/{pid}/analysis").get_json()
    assert full["overall"]["classification"] == "great"
    assert full["lowest_overall"]["price_cents"] == 37900
    card = client.get(f"/api/products/{pid}").get_json()["summary"]["analysis"]
    assert card["label"] == "Ótima oportunidade"
    assert client.get("/api/stats").get_json()["opportunities"] == 1

    # A mesma classificação não gera novo evento na rodada seguinte
    client.post("/api/monitor/run")
    kinds2 = [e["kind"] for e in client.get(f"/api/events?product_id={pid}").get_json()]
    assert kinds2.count("opportunity") == 1
