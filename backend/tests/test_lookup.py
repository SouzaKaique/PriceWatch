from app.adapters.base import guess_model_from_title
from app.adapters.stores import ADAPTERS
from app.adapters.structured import extract, parse_availability, parse_price

from .conftest import KABUM_HTML


def test_parse_price_formats():
    assert parse_price(469) == 46900
    assert parse_price("1299.90") == 129990
    assert parse_price("1.299,90") == 129990
    assert parse_price("R$ 1.299,90") == 129990
    assert parse_price("1,299.90") == 129990
    assert parse_price("0") is None
    assert parse_price(None) is None


def test_parse_availability():
    assert parse_availability("https://schema.org/InStock") is True
    assert parse_availability("http://schema.org/OutOfStock") is False
    assert parse_availability("algo") is None


def test_extract_kabum_structured_data():
    d = extract(KABUM_HTML)
    assert d["name"].startswith("Monitor Gamer LG 24")
    assert d["brand"] == "LG"
    assert d["price_cents"] == 46900
    assert d["available"] is True
    assert d["sku"] == "644868"
    assert d["category"] == "Monitores"


def test_foreign_currency_is_not_converted():
    html = KABUM_HTML.replace('"BRL"', '"USD"')
    assert "price_cents" not in extract(html)


def test_model_from_title():
    assert guess_model_from_title('Monitor LG 24" Full HD - 24MS500-B') == "24MS500-B"
    assert guess_model_from_title("Mouse sem fio - Preto") is None


def test_ids_and_canonical_urls():
    k, a, m = ADAPTERS["kabum"], ADAPTERS["amazon"], ADAPTERS["mercadolivre"]
    assert k.canonical_url("https://www.kabum.com.br/produto/644868/monitor-x?utm=1") == (
        "https://www.kabum.com.br/produto/644868"
    )
    assert a.canonical_url("https://www.amazon.com.br/Monitor-LG/dp/B0ABCDEF12/ref=sr_1?x=1") == (
        "https://www.amazon.com.br/dp/B0ABCDEF12"
    )
    assert m.extract_id("https://produto.mercadolivre.com.br/MLB-1234567890-monitor") == "MLB1234567890"


def test_lookup_endpoint_ok(client):
    r = client.post("/api/lookup", json={"url": "https://www.kabum.com.br/produto/644868/x"})
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["url"] == "https://www.kabum.com.br/produto/644868"
    assert body["data"]["price_cents"] == 46900
    assert body["data"]["model"] == "24MS500-B"


def test_lookup_endpoint_blocked_is_reported(client):
    body = client.post("/api/lookup", json={"url": "https://www.pichau.com.br/x"}).get_json()
    assert body["status"] == "blocked"
    assert body["data"] is None
    assert "recusou" in body["message"]


def test_lookup_rejects_unsupported(client):
    assert client.post("/api/lookup", json={"url": "https://exemplo.com/x"}).status_code == 422


def test_create_uses_cached_lookup_without_new_request(client, fake_web):
    url = "https://www.kabum.com.br/produto/644868/monitor"
    client.post("/api/lookup", json={"url": url})
    assert len(fake_web["calls"]) == 1
    r = client.post(
        "/api/products",
        json={"name": "Monitor LG 24", "brand": "LG", "model": "24MS500-B", "offers": [{"url": url}]},
    )
    assert len(fake_web["calls"]) == 1  # reaproveitou o cache
    offer = r.get_json()["offers"][0]
    assert offer["url"] == "https://www.kabum.com.br/produto/644868"
    assert offer["current_price_cents"] == 46900
    assert offer["last_status"] == "ok"
    assert offer["match"]["level"] == "strong"
    hist = client.get(f"/api/offers/{offer['id']}/history").get_json()
    assert len(hist) == 1 and hist[0]["price_cents"] == 46900


def test_create_records_cached_failure(client, fake_web):
    url = "https://www.pichau.com.br/monitor-x"
    assert client.post("/api/lookup", json={"url": url}).get_json()["status"] == "blocked"
    offer = client.post("/api/products", json={"name": "M", "offers": [{"url": url}]}).get_json()["offers"][0]
    assert len(fake_web["calls"]) == 1
    assert offer["last_status"] == "blocked"
    assert offer["current_price_cents"] is None


def test_add_offer_blocked_store_records_failure(client):
    pid = client.post("/api/products", json={"name": "Monitor"}).get_json()["id"]
    r = client.post(f"/api/products/{pid}/offers", json={"url": "https://www.amazon.com.br/dp/B0ABCDEF12"})
    assert r.status_code == 201
    o = r.get_json()
    assert o["last_status"] == "blocked"
    assert o["current_price_cents"] is None
    assert o["last_error"]


def test_check_offer_records_price_change(client, fake_web):
    pid = client.post("/api/products", json={"name": "Monitor"}).get_json()["id"]
    oid = client.post(
        f"/api/products/{pid}/offers", json={"url": "https://www.kabum.com.br/produto/644868"}
    ).get_json()["id"]
    fake_web["pages"]["kabum"] = KABUM_HTML.replace('"price":469', '"price":449.9').replace(
        '"priceWithDiscount":469', '"priceWithDiscount":449.9'
    )
    o = client.post(f"/api/offers/{oid}/check").get_json()
    assert o["current_price_cents"] == 44990
    assert o["previous_price_cents"] == 46900
    assert len(client.get(f"/api/offers/{oid}/history").get_json()) == 2


def test_match_mismatch_on_different_model(client):
    pid = client.post(
        "/api/products", json={"name": "Monitor", "brand": "LG", "model": "27GS60F-B"}
    ).get_json()["id"]
    client.post(f"/api/products/{pid}/offers", json={"url": "https://www.kabum.com.br/produto/644868"})
    offer = client.get(f"/api/products/{pid}").get_json()["offers"][0]
    assert offer["match"]["level"] == "mismatch"
