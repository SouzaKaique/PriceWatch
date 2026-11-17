from app.services.coupons import parse_advantage

from .conftest import DEFAULT_COUPONS, gviz

KABUM = "https://www.kabum.com.br/produto/644868"


def test_parse_advantage():
    assert parse_advantage("10% OFF") == (10.0, None)
    assert parse_advantage("10% OFF ") == (10.0, None)
    assert parse_advantage("R$50 OFF") == (None, 5000)
    assert parse_advantage("R$ 1.200 OFF") == (None, 120000)
    assert parse_advantage("Frete grátis") == (None, None)


def _product(client, category="Monitores", offers=(KABUM,)):
    # consulta antes para a oferta já ter preço (R$ 469,00 à vista)
    for u in offers:
        client.post("/api/lookup", json={"url": u})
    body = {"name": "Monitor LG", "category": category, "offers": [{"url": u} for u in offers]}
    return client.post("/api/products", json=body).get_json()["id"]


def test_refresh_official_and_list(client, fake_web):
    r = client.post("/api/coupons/refresh").get_json()
    assert r["fetched"] is True and r["total"] == 4 and r["new"] == 4
    active = client.get("/api/coupons").get_json()["coupons"]
    codes = {c["code"] for c in active}
    assert codes == {"MONITOR50", "TONOKABUM", "SSD10"}  # VELHO expirou
    assert all(c["verification_status"] == "unconfirmed" for c in active)
    assert all("página oficial" in c["source"].lower() for c in active)
    expired = client.get("/api/coupons?validity=expired").get_json()["coupons"]
    assert [c["code"] for c in expired] == ["VELHO"]

    # segunda atualização logo depois é recusada (respeita a loja)
    assert client.post("/api/coupons/refresh").get_json()["fetched"] is False


def test_refresh_does_not_duplicate(client, fake_web):
    from app.services import coupons as svc

    with client.application.app_context():
        svc.refresh_official(force=True)
        fake_web["pages"]["coupons"] = gviz(DEFAULT_COUPONS[:2])
        res = svc.refresh_official(force=True)
    assert res["new"] == 0
    assert len(client.get("/api/coupons?validity=all").get_json()["coupons"]) == 4


def test_product_coupons_applicability_and_estimate(client, fake_web):
    pid = _product(client)
    client.post("/api/coupons/refresh")
    items = client.get(f"/api/products/{pid}/coupons").get_json()
    by_code = {i["coupon"]["code"]: i["offers"][0] for i in items}
    # Cupom que a loja vincula ao próprio produto
    assert by_code["MONITOR50"]["applicability"]["level"] == "applies"
    assert by_code["MONITOR50"]["estimated_cents"] == 46900 - 5000
    # Cupom genérico (primeira compra): aplicabilidade não confirmada
    assert by_code["TONOKABUM"]["applicability"]["level"] == "unknown"
    assert by_code["TONOKABUM"]["estimated_cents"] == round(46900 * 0.95)
    assert any("primeira compra" in r.lower() for r in by_code["TONOKABUM"]["applicability"]["reasons"])
    # Cupom de "SSD selecionados" não aparece para um monitor
    assert "SSD10" not in by_code
    # Ordenação: o que se aplica vem primeiro
    assert items[0]["coupon"]["code"] == "MONITOR50"


def test_category_exclusion_from_legal_text(client, fake_web):
    pid = _product(client, category="Processadores")
    client.post("/api/coupons/refresh")
    codes = {i["coupon"]["code"] for i in client.get(f"/api/products/{pid}/coupons").get_json()}
    assert "TONOKABUM" not in codes  # texto legal exclui Processadores
    assert "MONITOR50" in codes  # a loja aponta este produto específico → vale independentemente da categoria


def test_coupon_event_only_when_relevant(client, fake_web):
    pid = _product(client)
    client.post("/api/coupons/refresh")
    ev = [e for e in client.get(f"/api/events?product_id={pid}").get_json() if e["kind"] == "coupon_available"]
    assert len(ev) == 1 and "MONITOR50" in ev[0]["message"] and "não confirmado" in ev[0]["message"]


def test_manual_coupon_crud_and_verification(client, fake_web):
    pid = _product(client, offers=("https://www.pichau.com.br/monitor",))
    bad = client.post("/api/coupons", json={"store": "pichau", "code": "X Y"})
    assert bad.status_code == 422 and {"code", "source", "discount_percent"} <= set(bad.get_json()["fields"])
    c = client.post("/api/coupons", json={
        "store": "pichau", "code": "pichau10", "discount_percent": 10, "min_purchase_cents": 100000,
        "valid_until": "2099-12-31", "source": "E-mail oficial da Pichau",
    }).get_json()
    assert c["code"] == "PICHAU10" and c["verification_status"] == "unconfirmed" and c["validity"] == "active"
    # Pichau sem preço consultado → o cupom aparece, mas sem estimativa
    item = client.get(f"/api/products/{pid}/coupons").get_json()[0]
    assert item["offers"][0]["estimated_cents"] is None

    ok = client.patch(f"/api/coupons/{c['id']}", json={"verification_status": "user_confirmed"}).get_json()
    assert ok["verification_status"] == "user_confirmed"
    client.patch(f"/api/coupons/{c['id']}", json={"verification_status": "user_failed"})
    assert client.get(f"/api/products/{pid}/coupons").get_json() == []  # não funcionou → some do produto
    assert client.delete(f"/api/coupons/{c['id']}").status_code == 204


def test_official_coupon_is_read_only(client, fake_web):
    client.post("/api/coupons/refresh")
    c = client.get("/api/coupons").get_json()["coupons"][0]
    r = client.patch(f"/api/coupons/{c['id']}", json={"code": "OUTRO", "verification_status": "user_confirmed"})
    assert r.get_json()["code"] == c["code"] and r.get_json()["verification_status"] == "user_confirmed"
    assert client.delete(f"/api/coupons/{c['id']}").status_code == 409


def test_min_purchase_excludes(client, fake_web):
    pid = _product(client)
    client.post("/api/coupons", json={"store": "kabum", "code": "GRANDE", "discount_cents": 10000,
                                      "min_purchase_cents": 200000, "source": "teste"})
    codes = {i["coupon"]["code"] for i in client.get(f"/api/products/{pid}/coupons").get_json()}
    assert "GRANDE" not in codes  # produto custa R$ 469,00 < mínimo R$ 2.000,00


def test_category_specific_coupon_matches_product(client, fake_web):
    pid = _product(client, category="Armazenamento")
    with client.application.app_context():
        from app.extensions import db
        from app.models import Product

        db.session.get(Product, pid).name = "SSD Kingston NV3 1TB"
        db.session.commit()
    client.post("/api/coupons/refresh")
    items = {i["coupon"]["code"]: i["offers"][0] for i in client.get(f"/api/products/{pid}/coupons").get_json()}
    assert items["SSD10"]["applicability"]["level"] == "possible"


def test_new_product_gets_event_for_existing_coupon(client, fake_web):
    client.post("/api/coupons/refresh")  # cupons já conhecidos antes do produto
    pid = _product(client)
    ev = [e for e in client.get(f"/api/events?product_id={pid}").get_json() if e["kind"] == "coupon_available"]
    assert [("MONITOR50" in e["message"]) for e in ev] == [True]
