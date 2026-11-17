import pytest

from app.adapters import stores as stores_mod
from app.services import ml_auth

ITEM = {
    "id": "MLB1234567890",
    "title": "Monitor Gamer LG UltraGear 27GS60F-B 27\" IPS 180Hz",
    "price": 849.0,
    "original_price": 999.0,
    "currency_id": "BRL",
    "status": "active",
    "available_quantity": 5,
    "category_id": "MLB99245",
    "permalink": "https://produto.mercadolivre.com.br/MLB-1234567890-monitor-lg",
    "pictures": [{"secure_url": "https://http2.mlstatic.com/x.jpg"}],
    "attributes": [
        {"id": "BRAND", "value_name": "LG"},
        {"id": "MODEL", "value_name": "27GS60F-B"},
        {"id": "GTIN", "value_name": "7893299900000"},
    ],
}


@pytest.fixture()
def ml_api(monkeypatch):
    """Simula a API oficial do Mercado Livre."""
    monkeypatch.setenv("ML_CLIENT_ID", "123")
    monkeypatch.setenv("ML_CLIENT_SECRET", "segredo")
    monkeypatch.setenv("ML_REDIRECT_URI", "https://exemplo.com/retorno")
    state = {"token_calls": [], "api_calls": [], "item_status": 200, "valid_token": "tok-1"}

    def fake_post_form(url, data, store_name):
        state["token_calls"].append(dict(data))
        if data["grant_type"] == "authorization_code" and data["code"] != "CODE-OK":
            return 400, {"message": "invalid_grant"}
        n = len(state["token_calls"])
        state["valid_token"] = f"tok-{n}"
        return 200, {"access_token": f"tok-{n}", "expires_in": 21600, "refresh_token": f"ref-{n}"}

    def fake_get_json(url, store_name, headers=None, params=None):
        state["api_calls"].append(url)
        if headers.get("Authorization") != f"Bearer {state['valid_token']}":
            return 401, {"message": "invalid token"}
        if url.endswith("/items/MLB1234567890"):
            return state["item_status"], ITEM if state["item_status"] == 200 else {"message": "x"}
        if url.endswith("/categories/MLB99245"):
            return 200, {"name": "Monitores"}
        if url.endswith("/products/MLB22222222"):
            return 200, {"name": "Monitor LG 27GS60F-B", "status": "active", "pictures": [],
                         "attributes": [{"id": "BRAND", "value_name": "LG"}],
                         "buy_box_winner": {"price": 829.9, "original_price": None}}
        return 404, {"message": "not found"}

    monkeypatch.setattr(ml_auth, "post_form", fake_post_form)
    monkeypatch.setattr(stores_mod, "get_json", fake_get_json)
    stores_mod.MercadoLivreAdapter._categories.clear()
    return state


def test_kabum_prices_from_page(client):
    d = client.post("/api/lookup", json={"url": "https://www.kabum.com.br/produto/644868"}).get_json()["data"]
    assert d["price_cents"] == 46900
    assert d["installment_price_cents"] == 52111
    assert d["list_price_cents"] == 60667


def test_ml_ids_from_urls():
    a = stores_mod.ADAPTERS["mercadolivre"]
    assert a.ids("https://produto.mercadolivre.com.br/MLB-1234567890-monitor-_JM") == ("MLB1234567890", None)
    assert a.ids("https://www.mercadolivre.com.br/monitor-lg/p/MLB22222222") == (None, "MLB22222222")
    assert a.ids("https://www.mercadolivre.com.br/monitor/p/MLB22222222?wid=MLB1234567890") == (
        "MLB1234567890",
        "MLB22222222",
    )


def test_ml_item_via_official_api(client, ml_api):
    r = client.post("/api/lookup", json={"url": "https://produto.mercadolivre.com.br/MLB-1234567890-x"})
    d = r.get_json()["data"]
    assert d["source"] == "API oficial do Mercado Livre"
    assert d["price_cents"] == 84900
    assert d["list_price_cents"] == 99900
    assert d["brand"] == "LG" and d["model"] == "27GS60F-B" and d["gtin"] == "7893299900000"
    assert d["category"] == "Monitores"
    assert d["available"] is True
    assert ml_api["token_calls"][0]["grant_type"] == "client_credentials"


def test_ml_catalog_product(client, ml_api):
    d = client.post(
        "/api/lookup", json={"url": "https://www.mercadolivre.com.br/monitor/p/MLB22222222"}
    ).get_json()["data"]
    assert d["price_cents"] == 82990
    assert d["store_product_id"] == "MLB22222222"


def test_ml_token_refreshed_on_401(client, ml_api):
    client.post("/api/lookup", json={"url": "https://produto.mercadolivre.com.br/MLB-1234567890-x"})
    ml_api["valid_token"] = "outro"  # token passa a ser rejeitado → renova
    from app.services import lookup as lookup_svc

    lookup_svc.clear_cache()
    body = client.post("/api/lookup", json={"url": "https://produto.mercadolivre.com.br/MLB-1234567890-x"}).get_json()
    assert body["status"] == "ok"
    assert len(ml_api["token_calls"]) == 2


def test_ml_forbidden_is_explained(client, ml_api):
    ml_api["item_status"] = 403
    body = client.post("/api/lookup", json={"url": "https://produto.mercadolivre.com.br/MLB-1234567890-x"}).get_json()
    assert body["status"] == "blocked"
    assert "autorize sua conta" in body["message"]


def test_ml_user_authorization_flow(client, ml_api):
    url = client.post("/api/integrations/mercadolivre/authorize").get_json()["url"]
    assert url.startswith("https://auth.mercadolivre.com.br/authorization?")
    assert "code_challenge=" in url and "client_id=123" in url
    state = url.split("state=")[1].split("&")[0]

    bad = client.post("/api/integrations/mercadolivre/connect", json={"code": "ERRADO"})
    assert bad.status_code == 400

    ok = client.post(
        "/api/integrations/mercadolivre/connect",
        json={"code": f"https://exemplo.com/retorno?code=CODE-OK&state={state}"},
    ).get_json()
    assert ok["user_connected"] is True and ok["mode"] == "user"
    exchange = ml_api["token_calls"][-1]
    assert exchange["grant_type"] == "authorization_code" and "code_verifier" in exchange

    # Status nunca expõe tokens
    integ = client.get("/api/integrations").get_json()
    ml = next(i for i in integ if i["key"] == "mercadolivre")
    assert ml["state"] == "connected"
    assert "tok-" not in str(integ) and "ref-" not in str(integ) and "segredo" not in str(integ)

    client.post("/api/integrations/mercadolivre/disconnect")
    assert client.get("/api/integrations").get_json()[2]["mercadolivre"]["user_connected"] is False


def test_integrations_without_ml_credentials(client):
    integ = {i["key"]: i for i in client.get("/api/integrations").get_json()}
    assert integ["mercadolivre"]["state"] == "not_configured"
    assert integ["kabum"]["state"] == "available"
    assert integ["amazon"]["state"] == "limited" and integ["amazon"]["limitation"]


def test_manual_price_is_labeled(client):
    pid = client.post("/api/products", json={"name": "Monitor", "target_price_cents": 90000}).get_json()["id"]
    oid = client.post(
        f"/api/products/{pid}/offers", json={"url": "https://www.pichau.com.br/monitor"}
    ).get_json()["id"]
    assert client.post(f"/api/offers/{oid}/manual-price", json={"price_cents": 0}).status_code == 422
    o = client.post(f"/api/offers/{oid}/manual-price", json={"price_cents": 89990}).get_json()
    assert o["current_price_cents"] == 89990 and o["price_source"] == "manual"
    assert o["last_status"] == "blocked"  # a limitação da loja continua visível
    hist = client.get(f"/api/offers/{oid}/history").get_json()
    assert hist[-1]["source"] == "manual"
    assert client.get(f"/api/products/{pid}").get_json()["summary"]["target_reached"] is True
