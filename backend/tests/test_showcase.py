"""Foto do produto, destaque de preço bom e tendência para os cards."""
from datetime import datetime, timedelta

from .test_monitor import KABUM, set_kabum_price


def test_check_fills_product_photo_and_empty_fields(client, fake_web):
    pid = client.post("/api/products", json={"name": "Meu monitor", "offers": [{"url": KABUM}]}).get_json()["id"]
    p = client.get(f"/api/products/{pid}").get_json()
    assert p["image_url"] is None and p["display_image_url"] is None
    oid = p["offers"][0]["id"]
    client.post(f"/api/offers/{oid}/check")
    p = client.get(f"/api/products/{pid}").get_json()
    assert p["image_url"] == "https://images.example/644868.jpg"  # foto da loja
    assert p["brand"] == "LG" and p["category"] == "Monitores"
    assert p["name"] == "Meu monitor"  # o nome escolhido não é trocado


def test_user_photo_is_kept(client, fake_web):
    pid = client.post("/api/products", json={"name": "M", "image_url": "https://minha.foto/x.png",
                                             "offers": [{"url": KABUM}]}).get_json()["id"]
    oid = client.get(f"/api/products/{pid}").get_json()["offers"][0]["id"]
    client.post(f"/api/offers/{oid}/check")
    assert client.get(f"/api/products/{pid}").get_json()["image_url"] == "https://minha.foto/x.png"


def test_display_image_falls_back_to_offer(client, fake_web):
    from app.extensions import db
    from app.models import Offer

    pid = client.post("/api/products", json={"name": "M", "offers": [{"url": KABUM}]}).get_json()["id"]
    with client.application.app_context():
        db.session.scalars(db.select(Offer)).one().image_url = "https://loja/foto.jpg"
        db.session.commit()
    assert client.get(f"/api/products/{pid}").get_json()["display_image_url"] == "https://loja/foto.jpg"


def test_highlight_for_target_and_trend(client, fake_web):
    client.post("/api/lookup", json={"url": KABUM})
    pid = client.post("/api/products", json={"name": "M", "target_price_cents": 47000,
                                             "offers": [{"url": KABUM}]}).get_json()["id"]
    p = client.get(f"/api/products/{pid}").get_json()
    assert p["summary"]["highlight"] == {"reason": "target", "label": "Preço-alvo atingido"}
    assert p["trend"] == [46900]


def test_highlight_for_great_opportunity_with_discount(client, fake_web):
    from app.extensions import db
    from app.models import Offer, PriceHistory

    pid = client.post("/api/products", json={"name": "M", "offers": [{"url": KABUM}]}).get_json()["id"]
    with client.application.app_context():
        offer = db.session.scalars(db.select(Offer)).one()
        start = datetime.utcnow() - timedelta(days=40)
        for i in range(40):
            db.session.add(PriceHistory(offer_id=offer.id, price_cents=50000, available=True,
                                        checked_at=start + timedelta(days=i)))
        offer.current_price_cents = 50000
        db.session.commit()
    set_kabum_price(fake_web, 399.0)
    client.post("/api/monitor/run")
    s = client.get(f"/api/products/{pid}").get_json()["summary"]
    assert s["highlight"]["reason"] == "great"
    assert s["analysis"]["baseline_cents"] == 50000 and s["analysis"]["real_discount_pct"] == 20.2
    assert client.get("/api/products").get_json()[0]["trend"][-1] == 39900
