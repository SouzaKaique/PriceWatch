import base64
import json

import pytest

from app.services import webpush as webpush_mod

from .test_monitor import KABUM, set_kabum_price

SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {"p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
             "auth": "tBHItJI5svbpez7KI4CCXg"},
}


class FakeResponse:
    def __init__(self, status):
        self.status_code = status


@pytest.fixture()
def pushes(monkeypatch):
    sent = {"calls": [], "status": None}

    def fake_webpush(subscription_info, data, vapid_private_key, vapid_claims, ttl, timeout):
        if sent["status"]:
            raise webpush_mod.WebPushException("erro", response=FakeResponse(sent["status"]))
        sent["calls"].append({"sub": subscription_info, "data": json.loads(data), "claims": vapid_claims})

    monkeypatch.setattr(webpush_mod, "webpush", fake_webpush)
    return sent


def test_public_key_format(client):
    key = client.get("/api/push/key").get_json()["public_key"]
    raw = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
    assert len(raw) == 65 and raw[0] == 4  # ponto P-256 não comprimido
    assert client.get("/api/push/key").get_json()["public_key"] == key  # estável


def test_subscribe_validation_and_status(client):
    assert client.post("/api/push/subscribe", json={"endpoint": "http://inseguro"}).status_code == 422
    r = client.post("/api/push/subscribe", json=SUB)
    assert r.status_code == 201 and r.get_json()["channels"]["webpush"]["ready"] is True
    client.post("/api/push/subscribe", json=SUB)  # repetir não duplica
    assert client.get("/api/notifications/status").get_json()["channels"]["webpush"]["devices"] == 1
    client.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]})
    assert client.get("/api/notifications/status").get_json()["channels"]["webpush"]["ready"] is False


def test_webpush_alert_opens_offer(client, fake_web, pushes):
    client.post("/api/push/subscribe", json=SUB)
    client.post("/api/lookup", json={"url": KABUM})
    client.post("/api/products", json={"name": "Monitor LG 24", "target_price_cents": 45000,
                                       "offers": [{"url": KABUM}]})
    set_kabum_price(fake_web, 449.9)
    client.post("/api/monitor/run")
    notes = [c["data"]["notification"] for c in pushes["calls"]]
    target = next(n for n in notes if "Oportunidade encontrada" in n["title"])
    assert "R$ 449,90" in target["body"]
    action = target["data"]["onActionClick"]["default"]
    assert action == {"operation": "openWindow", "url": "https://www.kabum.com.br/produto/644868"}
    assert pushes["calls"][0]["claims"]["sub"].startswith("mailto:")


def test_expired_subscription_is_removed(client, pushes):
    client.post("/api/push/subscribe", json=SUB)
    pushes["status"] = 410
    r = client.post("/api/notifications/test").get_json()["results"]
    assert r["webpush"]["ok"] is False
    assert client.get("/api/notifications/status").get_json()["channels"]["webpush"]["devices"] == 0


def test_spa_without_build_explains(client):
    r = client.get("/produtos/1")
    assert r.status_code == 404 and "npm run build" in r.get_json()["message"]
    assert client.get("/api/health").status_code == 200


def test_spa_serves_build_and_routes(client, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "main-ABC123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "segredo.txt").write_text("não pode vazar", encoding="utf-8")
    client.application.config["FRONTEND_DIST"] = str(dist)

    r = client.get("/produtos/7")
    assert r.status_code == 200 and b"app" in r.data and r.headers["Cache-Control"] == "no-cache"
    r = client.get("/main-ABC123.js")
    assert r.status_code == 200 and "immutable" in r.headers["Cache-Control"]
    assert client.get("/inexistente.js").status_code == 404
    assert client.get("/../segredo.txt").status_code == 404
    assert client.get("/%2e%2e/segredo.txt").status_code == 404
    assert client.get("/api/rota-inexistente").status_code == 404
