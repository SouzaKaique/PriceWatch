from datetime import datetime, timedelta, timezone

import pytest

from app.services import notify

from .test_monitor import KABUM, set_kabum_price


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {"ok": True, "result": {}}

    def json(self):
        return self._body


@pytest.fixture()
def channels(monkeypatch):
    """Telegram + ntfy simulados; guarda o que seria enviado."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("NTFY_TOPIC", "pw-teste-topico-secreto")
    sent = {"telegram": [], "ntfy": [], "fail": set(), "updates": []}

    def post(url, json=None, timeout=None):
        if "api.telegram.org" in url:
            method = url.rsplit("/", 1)[-1]
            if method == "getMe":
                return FakeResp(body={"ok": True, "result": {"username": "meu_pw_bot"}})
            if method == "getUpdates":
                return FakeResp(body={"ok": True, "result": sent["updates"]})
            if "telegram" in sent["fail"]:
                return FakeResp(400, {"ok": False, "description": "Bad Request"})
            sent["telegram"].append(json)
            return FakeResp()
        if "ntfy" in sent["fail"]:
            return FakeResp(500)
        sent["ntfy"].append(json)
        return FakeResp()

    monkeypatch.setattr(notify._http, "post", post)
    return sent


def connect_telegram(client, channels):
    channels["updates"] = [
        {"message": {"chat": {"id": 999, "type": "private", "first_name": "Teste"}, "text": "/start"}}
    ]
    return client.post("/api/notifications/telegram/connect")


def product(client, target=None):
    client.post("/api/lookup", json={"url": KABUM})
    body = {"name": "Monitor LG 24", "offers": [{"url": KABUM}]}
    if target:
        body["target_price_cents"] = target
    return client.post("/api/products", json=body).get_json()["id"]


def pending(client):
    return client.get("/api/notifications/status").get_json()["pending"]


def test_status_without_channels_never_leaks_token(client):
    st = client.get("/api/notifications/status").get_json()
    assert st["channels"]["telegram"]["ready"] is False and st["channels"]["ntfy"]["ready"] is False
    assert client.post("/api/notifications/test").status_code == 400


def test_telegram_connect_flow(client, channels):
    r = client.post("/api/notifications/telegram/connect")
    assert r.status_code == 400 and "/start" in r.get_json()["message"]
    r = connect_telegram(client, channels).get_json()
    assert r["chat_name"] == "Teste" and r["channels"]["telegram"]["ready"] is True
    assert "123:abc" not in str(client.get("/api/notifications/status").get_json())


def test_target_reached_message_matches_spec(client, fake_web, channels):
    connect_telegram(client, channels)
    product(client, target=45000)
    set_kabum_price(fake_web, 449.9)
    client.post("/api/monitor/run")
    texts = [m["text"] for m in channels["telegram"]]
    target = next(t for t in texts if "Oportunidade encontrada" in t)
    assert "está custando R$ 449,90 na KaBuM!" in target
    assert "Preço desejado: R$ 450,00" in target and "O preço-alvo foi atingido!" in target
    assert "Toque para conferir a oferta" in target and "kabum.com.br/produto/644868" in target
    ntfy = next(m for m in channels["ntfy"] if "Oportunidade" in m["title"])
    assert ntfy["click"].startswith("https://www.kabum.com.br/produto/644868") and ntfy["priority"] == 4
    log = client.get("/api/notifications/log").get_json()
    assert any(entry["channel"] == "telegram" and entry["delivered"] for entry in log)
    assert pending(client) == 0


def test_disabled_kind_is_not_sent(client, fake_web, channels):
    connect_telegram(client, channels)
    client.patch(
        "/api/settings",
        json={"notify_kinds": {"price_drop": False, "lowest_ever": False, "coupon_available": False}},
    )
    product(client)
    set_kabum_price(fake_web, 399.0)
    client.post("/api/monitor/run")
    assert not any("Queda de preço" in m["text"] for m in channels["telegram"])
    assert pending(client) == 0


def test_quiet_hours_hold_then_send(client, fake_web, channels):
    connect_telegram(client, channels)
    client.patch(
        "/api/settings",
        json={"notify_quiet_enabled": True, "notify_quiet_start": "00:00", "notify_quiet_end": "23:59"},
    )
    product(client)
    set_kabum_price(fake_web, 399.0)
    client.post("/api/monitor/run")
    assert channels["telegram"] == []
    assert pending(client) > 0
    client.patch("/api/settings", json={"notify_quiet_enabled": False})
    r = client.post("/api/notifications/dispatch").get_json()
    assert r["sent"] >= 1 and channels["telegram"]


def test_quiet_window_crossing_midnight():
    cfg = {"notify_quiet_enabled": True, "notify_quiet_start": "23:00", "notify_quiet_end": "07:00"}
    brt = timezone(timedelta(hours=-3))
    assert notify.in_quiet_hours(cfg, datetime(2026, 11, 17, 23, 30, tzinfo=brt))
    assert notify.in_quiet_hours(cfg, datetime(2026, 11, 18, 6, 59, tzinfo=brt))
    assert not notify.in_quiet_hours(cfg, datetime(2026, 11, 18, 7, 0, tzinfo=brt))


def test_rate_limit_per_hour(client, fake_web, channels):
    connect_telegram(client, channels)
    client.patch("/api/settings", json={"notify_max_per_hour": 1})
    product(client)
    for price in (399.0, 449.0):  # duas alterações relevantes
        set_kabum_price(fake_web, price)
        client.post("/api/monitor/run")
    log = client.get("/api/notifications/log").get_json()
    sent_events = {entry["event_id"] for entry in log if entry["delivered"]}
    assert len(sent_events) == 1
    assert pending(client) >= 1


def test_failed_channel_retries_then_gives_up(client, fake_web, channels):
    connect_telegram(client, channels)
    channels["fail"] |= {"telegram", "ntfy"}
    product(client)
    set_kabum_price(fake_web, 399.0)
    client.post("/api/monitor/run")
    assert pending(client) >= 1
    for _ in range(3):
        client.post("/api/notifications/dispatch")
    assert pending(client) == 0
    errors = [e["error"] for e in client.get("/api/notifications/log?limit=100").get_json() if e["error"]]
    assert any("Telegram recusou" in e for e in errors) and any("ntfy" in e for e in errors)


def test_old_events_are_not_blasted_when_channel_configured_later(client, fake_web, channels, monkeypatch):
    from app.extensions import db
    from app.models import PriceEvent

    monkeypatch.delenv("NTFY_TOPIC")  # nenhum canal pronto ainda
    product(client)
    set_kabum_price(fake_web, 399.0)
    client.post("/api/monitor/run")  # sem canal pronto ainda: fica pendente
    with client.application.app_context():
        for ev in db.session.scalars(db.select(PriceEvent)):
            ev.created_at -= timedelta(days=2)
        db.session.commit()
    assert pending(client) >= 1
    monkeypatch.setenv("NTFY_TOPIC", "pw-teste-topico-secreto")
    connect_telegram(client, channels)
    client.post("/api/notifications/dispatch")
    assert channels["telegram"] == [] and channels["ntfy"] == []
    assert pending(client) == 0


def test_send_test_message(client, channels):
    connect_telegram(client, channels)
    r = client.post("/api/notifications/test").get_json()["results"]
    assert r == {"telegram": {"ok": True}, "ntfy": {"ok": True}}
    assert "Teste de notificação" in channels["telegram"][0]["text"]
