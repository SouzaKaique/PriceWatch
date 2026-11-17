from app.extensions import db
from app.models import Offer


def _create(client, **extra):
    body = {"name": "Monitor LG UltraGear 27", "brand": "LG", "target_price_cents": 75000}
    body.update(extra)
    return client.post("/api/products", json=body)


def test_health(client):
    assert client.get("/api/health").get_json()["database"] == "ok"


def test_create_requires_name(client):
    r = client.post("/api/products", json={"brand": "LG"})
    assert r.status_code == 422
    assert "name" in r.get_json()["fields"]


def test_create_with_offers_detects_store(client):
    r = _create(
        client,
        offers=[
            {"url": "https://www.kabum.com.br/produto/123/monitor"},
            {"url": "https://produto.mercadolivre.com.br/MLB-1"},
        ],
    )
    assert r.status_code == 201
    data = r.get_json()
    assert sorted(o["store"] for o in data["offers"]) == ["kabum", "mercadolivre"]
    assert all(o["current_price_cents"] is None for o in data["offers"])  # nenhum preço inventado
    assert data["summary"]["best_price_cents"] is None


def test_unsupported_store_rejected(client):
    r = _create(client, offers=[{"url": "https://www.exemplo.com/x"}])
    assert r.status_code == 422
    assert "offers.0.store" in r.get_json()["fields"]


def test_update_and_delete(client):
    pid = _create(client).get_json()["id"]
    r = client.patch(f"/api/products/{pid}", json={"target_price_cents": 70000, "active": False})
    assert r.get_json()["target_price_cents"] == 70000
    assert r.get_json()["active"] is False
    assert client.patch(f"/api/products/{pid}", json={"name": ""}).status_code == 422
    assert client.delete(f"/api/products/{pid}").status_code == 204
    assert client.get(f"/api/products/{pid}").status_code == 404


def test_duplicate_offer_rejected(client):
    pid = _create(client).get_json()["id"]
    url = "https://www.pichau.com.br/monitor"
    assert client.post(f"/api/products/{pid}/offers", json={"url": url}).status_code == 201
    assert client.post(f"/api/products/{pid}/offers", json={"url": url}).status_code == 422


def test_summary_and_stats_use_real_offer_prices(client):
    pid = _create(
        client,
        offers=[
            {"url": "https://www.kabum.com.br/p/1"},
            {"url": "https://www.amazon.com.br/dp/B0"},
        ],
    ).get_json()["id"]
    # Simula o que a Fase 4/5 fará: uma consulta real gravando preços.
    with client.application.app_context():
        offers = db.session.scalars(db.select(Offer).where(Offer.product_id == pid)).all()
        offers[0].current_price_cents, offers[0].previous_price_cents = 74990, 89900
        offers[1].current_price_cents = 91900
        db.session.commit()

    s = client.get(f"/api/products/{pid}").get_json()["summary"]
    assert s["best_price_cents"] == 74990
    assert s["target_reached"] is True
    stats = client.get("/api/stats").get_json()
    assert stats["target_reached"] == 1
    assert stats["potential_savings_cents"] == 91900 - 74990
    assert stats["biggest_drop"]["amount_cents"] == 89900 - 74990
