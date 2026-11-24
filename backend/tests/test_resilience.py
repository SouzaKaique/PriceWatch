"""Falhas de lojas/rede, persistência, backups e retomada do agendador."""
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

from app.adapters import LookupFailed
from app.adapters import http as http_mod

from .conftest import KABUM_HTML

URL = "https://www.kabum.com.br/produto/1"


class Resp:
    def __init__(self, status=200, text="", url=URL, encoding="utf-8", content=None):
        self.status_code, self.url, self.encoding = status, url, encoding
        self._text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.apparent_encoding = "utf-8"

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8", errors="replace")


@pytest.fixture()
def web(monkeypatch):
    """Simula a resposta da loja na camada HTTP real (get_html de verdade)."""
    state = {"responses": [], "calls": 0, "sleeps": []}

    def get(url, timeout=None, allow_redirects=True, **kw):
        state["calls"] += 1
        r = state["responses"].pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(http_mod._session, "get", get)
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: state["sleeps"].append(s))
    http_mod.reset_state()
    return state


def test_ok_page(web):
    web["responses"] = [Resp(200, KABUM_HTML)]
    html, final = http_mod.get_html(URL, "KaBuM!")
    assert "schema.org" in html and final == URL


def test_403_blocks_and_pauses_domain(web):
    web["responses"] = [Resp(403, "denied")]
    with pytest.raises(LookupFailed) as e:
        http_mod.get_html(URL, "KaBuM!")
    assert e.value.code == "blocked" and "não contorna" in e.value.message
    # durante a pausa nem tenta de novo
    with pytest.raises(LookupFailed) as e2:
        http_mod.get_html(URL, "KaBuM!")
    assert e2.value.code == "rate_limited" and web["calls"] == 1
    assert http_mod.blocked_remaining(URL) > 1700


@pytest.mark.parametrize("status", [429, 503, 202])
def test_other_block_statuses(web, status):
    web["responses"] = [Resp(status, "x")]
    with pytest.raises(LookupFailed) as e:
        http_mod.get_html(URL, "Loja")
    assert e.value.code == "blocked"


def test_captcha_redirect_is_detected(web):
    web["responses"] = [Resp(200, "<html>verifique</html>",
                             url="https://www.mercadolivre.com.br/gz/account-verification?go=x")]
    with pytest.raises(LookupFailed) as e:
        http_mod.get_html("https://produto.mercadolivre.com.br/MLB-1", "Mercado Livre")
    assert e.value.code == "blocked"


def test_small_challenge_page_is_detected(web):
    web["responses"] = [Resp(200, "<html><title>Just a moment...</title>cf-chl</html>")]
    with pytest.raises(LookupFailed) as e:
        http_mod.get_html(URL, "Loja")
    assert e.value.code == "blocked"


def test_not_found_and_server_error(web):
    web["responses"] = [Resp(404, "nf"), Resp(500, "erro")]
    with pytest.raises(LookupFailed) as e:
        http_mod.get_html(URL, "KaBuM!")
    assert e.value.code == "not_found"
    http_mod.reset_state()
    with pytest.raises(LookupFailed) as e:
        http_mod.get_html(URL, "KaBuM!")
    assert e.value.code == "network" and "500" in e.value.message
    assert http_mod.blocked_remaining(URL) == 0  # erro do servidor não é bloqueio


def test_timeout_and_connection_error(web):
    web["responses"] = [requests.Timeout(), requests.ConnectionError()]
    for expected in ("não respondeu a tempo", "Falha de conexão"):
        http_mod.reset_state()
        with pytest.raises(LookupFailed) as e:
            http_mod.get_html(URL, "KaBuM!")
        assert e.value.code == "network" and expected in e.value.message


def test_oversized_page_is_rejected(web):
    web["responses"] = [Resp(200, content=b"x" * (http_mod.MAX_BYTES + 1))]
    with pytest.raises(LookupFailed) as e:
        http_mod.get_html(URL, "KaBuM!")
    assert e.value.code == "parse"


def test_latin1_default_is_redetected(web):
    r = Resp(200, encoding="ISO-8859-1", content="<html>Inclinação</html>".encode("utf-8"))
    web["responses"] = [r]
    html, _ = http_mod.get_html(URL, "KaBuM!")
    assert "Inclinação" in html


def test_throttle_between_requests_same_store(web):
    web["responses"] = [Resp(200, KABUM_HTML), Resp(200, KABUM_HTML)]
    http_mod.get_html(URL, "KaBuM!")
    http_mod.get_html(URL, "KaBuM!")
    assert web["sleeps"] and web["sleeps"][-1] > 4  # ~5 s entre consultas à mesma loja


def test_store_outage_does_not_break_monitor_run(client, fake_web, monkeypatch):
    """Uma loja fora do ar não derruba a rodada nem apaga dados anteriores."""
    from app.adapters import stores as stores_mod

    client.post("/api/lookup", json={"url": "https://www.kabum.com.br/produto/644868"})
    pid = client.post("/api/products", json={
        "name": "M", "offers": [{"url": "https://www.kabum.com.br/produto/644868"}]}).get_json()["id"]

    def broken(url, store_name):
        raise LookupFailed("network", f"{store_name} não respondeu a tempo.")

    monkeypatch.setattr(stores_mod, "get_html", broken)
    client.post("/api/monitor/run")
    run = client.get("/api/monitor").get_json()["runs"][0]
    assert run["status"] == "done" and run["offers_failed"] == 1
    offer = client.get(f"/api/products/{pid}").get_json()["offers"][0]
    assert offer["current_price_cents"] == 46900  # último preço real preservado
    assert offer["last_status"] == "error" and "não respondeu" in offer["last_error"]


def test_unexpected_exception_in_one_offer_is_isolated(client, fake_web, monkeypatch):
    from app.services import monitor

    client.post("/api/products", json={"name": "A", "offers": [{"url": "https://www.kabum.com.br/produto/1"}]})
    client.post("/api/products", json={"name": "B", "offers": [{"url": "https://www.kabum.com.br/produto/2"}]})
    original = monitor.check_offer_with_events
    calls = {"n": 0}

    def flaky(offer, cfg=None, use_cache=False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("bug inesperado")
        return original(offer, cfg, use_cache)

    monkeypatch.setattr(monitor, "check_offer_with_events", flaky)
    client.post("/api/monitor/run")
    run = client.get("/api/monitor").get_json()["runs"][0]
    assert run["status"] == "done" and run["offers_failed"] == 1 and run["offers_ok"] == 1


# ---- Persistência, backups e reinício ---------------------------------------------

@pytest.fixture()
def file_app(tmp_path, monkeypatch):
    from app import create_app

    from .conftest import TestConfig

    class FileConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'pw.db').as_posix()}"

    app = create_app(FileConfig)
    app.instance_path = str(tmp_path / "instance")
    return app


def test_backup_and_retention(file_app):
    from app.services import maintenance

    with file_app.app_context():
        assert maintenance.check_integrity()["ok"] is True
        first = maintenance.backup()
        assert first and first.exists()
        assert maintenance.backup() is None  # recente: não duplica
        for _ in range(9):
            time.sleep(1.05)  # nomes com segundos distintos
            maintenance.backup(force=True)
        assert len(maintenance.list_backups()) == maintenance.KEEP_BACKUPS
        assert maintenance.status()["backups"] == maintenance.KEEP_BACKUPS


def test_data_survives_restart_and_interrupted_run_is_closed(file_app, tmp_path):
    from app import create_app
    from app.extensions import db
    from app.models import MonitorRun, PriceHistory, Product
    from app.services import monitor

    from .conftest import TestConfig

    with file_app.app_context():
        p = Product(name="Persistente")
        db.session.add(p)
        db.session.flush()
        db.session.add(MonitorRun(reason="scheduled", status="running"))  # PC desligou no meio
        db.session.commit()

    class FileConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = file_app.config["SQLALCHEMY_DATABASE_URI"]

    restarted = create_app(FileConfig)  # "religa o computador"
    with restarted.app_context():
        assert db.session.scalar(db.select(Product.name)) == "Persistente"
        monitor.close_interrupted_runs()
        run = db.session.scalar(db.select(MonitorRun))
        assert run.status == "failed" and "Interrompida" in run.error
        assert db.session.scalar(db.select(db.func.count(PriceHistory.id))) == 0


def test_first_run_after_downtime(file_app):
    from app import scheduler
    from app.extensions import db
    from app.models import MonitorRun, utcnow

    with file_app.app_context():
        when, reason = scheduler._first_run_at(120)
        assert reason == "startup"  # nunca rodou
        db.session.add(MonitorRun(reason="scheduled", status="done", finished_at=utcnow() - timedelta(minutes=30)))
        db.session.commit()
        when, reason = scheduler._first_run_at(120)
        assert reason == "scheduled"
        assert timedelta(minutes=85) < when - datetime.now(timezone.utc) < timedelta(minutes=95)
        db.session.add(MonitorRun(reason="scheduled", status="done", finished_at=utcnow() - timedelta(hours=9)))
        db.session.query(MonitorRun).filter(MonitorRun.finished_at > utcnow() - timedelta(hours=1)).delete()
        db.session.commit()
        when, reason = scheduler._first_run_at(120)
        assert reason == "startup" and when - datetime.now(timezone.utc) < timedelta(minutes=2)


def test_interrupted_run_does_not_postpone_catch_up(file_app):
    """PC desligado no meio da rodada: ao religar, a retomada acontece logo (não em 2 h)."""
    from app import scheduler
    from app.extensions import db
    from app.models import MonitorRun, utcnow
    from app.services import monitor

    with file_app.app_context():
        db.session.add(MonitorRun(reason="scheduled", status="done", finished_at=utcnow() - timedelta(hours=3)))
        db.session.add(MonitorRun(reason="scheduled", status="running"))
        db.session.commit()
        monitor.close_interrupted_runs()  # o que o start() faz
        when, reason = scheduler._first_run_at(120)
        assert reason == "startup" and when - datetime.now(timezone.utc) < timedelta(minutes=2)


def test_diagnostics_endpoint(client, fake_web):
    client.post("/api/products", json={"name": "M", "offers": [{"url": "https://www.pichau.com.br/x"}]})
    d = client.get("/api/diagnostics").get_json()
    keys = {i["key"]: i for i in d["items"]}
    assert keys["database"]["status"] == "ok"
    assert keys["scheduler"]["status"] == "error"  # nos testes o agendador não roda
    assert keys["notifications"]["status"] == "ok" and "opcional" in keys["notifications"]["detail"]
    assert keys["security"]["status"] == "ok"
    assert d["status"] == "error"


def test_diagnostics_flags_exposed_api_without_key(client):
    client.application.config["HOST"] = "0.0.0.0"
    items = {i["key"]: i for i in client.get("/api/diagnostics").get_json()["items"]}
    assert items["security"]["status"] == "error" and "API_ACCESS_KEY" in items["security"]["hint"]
