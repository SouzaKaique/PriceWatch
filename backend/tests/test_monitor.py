import time

from app.adapters import http as http_mod

from .conftest import KABUM_HTML

KABUM = "https://www.kabum.com.br/produto/644868"


def set_kabum_price(fake_web, price: float, available: bool = True):
    html = KABUM_HTML.replace('"price":469', f'"price":{price}').replace(
        '"priceWithDiscount":469', f'"priceWithDiscount":{price}'
    )
    if not available:
        html = html.replace("schema.org/InStock", "schema.org/OutOfStock").replace(
            '"available":true', '"available":false'
        )
    fake_web["pages"]["kabum"] = html


def run(client):
    r = client.post("/api/monitor/run")
    assert r.status_code == 202
    return client.get("/api/monitor").get_json()["runs"][0]


def events(client, pid=None):
    url = "/api/events?limit=100" + (f"&product_id={pid}" if pid else "")
    # alertas de cupom têm testes próprios (test_coupons.py)
    return [e["kind"] for e in client.get(url).get_json() if e["kind"] != "coupon_available"]


def make_product(client, target=None, offers=(KABUM,)):
    body = {"name": "Monitor LG", "offers": [{"url": u} for u in offers]}
    if target:
        body["target_price_cents"] = target
    return client.post("/api/products", json=body).get_json()["id"]


def test_run_records_history_and_stats(client, fake_web):
    pid = make_product(client)
    r = run(client)
    assert r["status"] == "done" and r["offers_checked"] == 1 and r["offers_ok"] == 1
    hist = client.get(f"/api/products/{pid}/history?days=30").get_json()
    assert hist["series"][0]["store"] == "kabum"
    assert [p["price_cents"] for p in hist["series"][0]["points"]] == [46900]
    assert hist["monitoring_since"]


def test_relevant_drop_and_increase(client, fake_web):
    pid = make_product(client)
    run(client)  # 469,00
    set_kabum_price(fake_web, 468.0)  # -0,2% → oscilação irrelevante
    run(client)
    assert events(client, pid) == []
    set_kabum_price(fake_web, 429.9)
    r = run(client)
    assert r["events"] == 1 and events(client, pid) == ["price_drop"]
    set_kabum_price(fake_web, 469.0)
    run(client)
    assert events(client, pid)[0] == "price_increase"


def test_target_reached_only_once(client, fake_web):
    pid = make_product(client, target=45000)
    run(client)
    set_kabum_price(fake_web, 449.0)
    run(client)
    set_kabum_price(fake_web, 439.0)
    run(client)
    kinds = events(client, pid)
    assert kinds.count("target_reached") == 1
    msg = client.get(f"/api/events?product_id={pid}").get_json()
    assert any("preço-alvo" in e["message"] for e in msg)


def test_stock_transitions(client, fake_web):
    pid = make_product(client)
    run(client)
    set_kabum_price(fake_web, 469, available=False)
    run(client)
    set_kabum_price(fake_web, 469, available=True)
    run(client)
    assert events(client, pid)[:2] == ["back_in_stock", "out_of_stock"]


def test_lowest_ever_needs_history(client, fake_web):
    pid = make_product(client)
    for price in (469, 489, 479):
        set_kabum_price(fake_web, price)
        run(client)
    set_kabum_price(fake_web, 419.9)
    run(client)
    assert "lowest_ever" in events(client, pid)


def test_paused_product_and_blocked_store_are_skipped(client, fake_web):
    pid = make_product(client, offers=(KABUM, "https://www.pichau.com.br/monitor"))
    http_mod._blocked_until["pichau.com.br"] = time.time() + 600
    r = run(client)
    assert r["offers_checked"] == 1 and r["offers_skipped"] == 1
    client.patch(f"/api/products/{pid}", json={"active": False})
    r = run(client)
    assert r["offers_checked"] == 0


def test_better_store_event_with_manual_price(client, fake_web):
    pid = make_product(client, offers=(KABUM, "https://www.pichau.com.br/monitor"))
    run(client)
    pichau = next(o for o in client.get(f"/api/products/{pid}").get_json()["offers"] if o["store"] == "pichau")
    client.post(f"/api/offers/{pichau['id']}/manual-price", json={"price_cents": 45990})
    ev = client.get(f"/api/events?product_id={pid}").get_json()
    assert ev[0]["kind"] == "better_store" and ev[0]["source"] == "manual"


def test_check_now_endpoint_creates_events(client, fake_web):
    pid = make_product(client)
    oid = client.get(f"/api/products/{pid}").get_json()["offers"][0]["id"]
    client.post(f"/api/offers/{oid}/check")  # primeiro preço: 469,00
    set_kabum_price(fake_web, 399.0)
    client.post(f"/api/offers/{oid}/check")
    assert events(client, pid) == ["price_drop"]


def test_settings_validation_and_update(client):
    assert client.get("/api/settings").get_json()["check_interval_minutes"] == 120
    bad = client.patch("/api/settings", json={"check_interval_minutes": 5})
    assert bad.status_code == 422
    ok = client.patch("/api/settings", json={"check_interval_minutes": 180, "min_change_percent": 5})
    assert ok.get_json()["check_interval_minutes"] == 180
    assert client.get("/api/monitor").get_json()["interval_minutes"] == 180
