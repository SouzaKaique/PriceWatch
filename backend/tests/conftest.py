import pytest

from app import create_app
from app.adapters import LookupFailed, http as http_mod
from app.adapters import stores as stores_mod
from app.config import Config
from app.services import lookup as lookup_svc

# Página sintética no formato publicado pela KaBuM (JSON-LD schema.org).
KABUM_HTML = """<!doctype html><html><head>
<meta property="og:title" content="Monitor Gamer LG 24 Full HD - 24MS500-B">
<script type="application/ld+json">{
 "@context":"https://schema.org","@type":"Product",
 "name":"Monitor Gamer LG 24\\" Full HD, 100Hz, IPS - 24MS500-B",
 "image":"https://images.example/644868.jpg","sku":"644868",
 "brand":{"@type":"Brand","name":"LG"},
 "offers":{"@type":"Offer","priceCurrency":"BRL","price":469,
           "availability":"https://schema.org/InStock"}}</script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"BreadcrumbList",
 "itemListElement":[{"@type":"ListItem","position":1,"name":"Início"},
 {"@type":"ListItem","position":2,"name":"Computadores"},
 {"@type":"ListItem","position":3,"name":"Monitores"},
 {"@type":"ListItem","position":4,"name":"Código 644868"}]}</script>
<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"product":{
 "available":true,"prices":{"oldPrice":606.67,"price":521.11,"priceWithDiscount":469}}}}}</script>
</head><body></body></html>"""


KABUM_SCRIPT_JS = """fetch('https://docs.google.com/spreadsheets/d/TESTE123/gviz/tq?')
  .then(r => r.text()); fetch('https://docs.google.com/spreadsheets/d/TESTE123/gviz/tq?gid=1')"""


def gviz(rows: list[list]) -> str:
    import json

    header = ["Imagem", "Data inicial", "Data final", "Cupom", "Desconto", "Condição", "Link", "Texto", "Cron"]
    table = {"rows": [{"c": [{"v": v} for v in r]} for r in [header] + rows]}
    return "/*O_o*/ google.visualization.Query.setResponse(" + json.dumps(
        {"version": "0.6", "status": "ok", "table": table}
    ) + ");"


DEFAULT_COUPONS = [
    ["img", "2026-01-01T00:00:00-03:00", "2099-12-31T23:59:00-03:00", "MONITOR50", "R$50 OFF",
     "em Monitor selecionado ", "https://www.kabum.com.br/produto/644868/monitor", "Válido 1 cupom por CPF.", "Não"],
    ["img", "2026-01-01T00:00:00-03:00", "2099-12-31T23:59:00-03:00", "TONOKABUM", "5% OFF",
     "em produtos selecionados ", "https://www.kabum.com.br/",
     "Cupom válido para a PRIMEIRA COMPRA. Este cupom não é válido para Serviços Digitais, Processadores, "
     "Placas de Vídeo e Notebooks.", "Não"],
    ["img", "2026-01-01T00:00:00-03:00", "2099-12-31T23:59:00-03:00", "SSD10", "10% OFF",
     "em SSD selecionados ", "https://www.kabum.com.br/promocao/CP1SSD10", "Texto.", "Não"],
    ["img", "2020-01-01T00:00:00-03:00", "2020-01-02T00:00:00-03:00", "VELHO", "10% OFF",
     "em produtos selecionados", "https://www.kabum.com.br/", "Texto.", "Não"],
]


class TestConfig(Config):
    TESTING = True
    FRONTEND_DIST = "__sem_build__"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    API_ACCESS_KEY = ""


@pytest.fixture()
def fake_web(monkeypatch):
    """Substitui o acesso à internet: KaBuM responde, demais lojas bloqueiam."""
    pages = {"kabum": KABUM_HTML, "coupons": gviz(DEFAULT_COUPONS)}
    calls: list[str] = []

    def fake_get_html(url, store_name):
        calls.append(url)
        if url.endswith("/hotsite/cupons/js/script.js"):
            return KABUM_SCRIPT_JS, url
        if "kabum" in url:
            return pages["kabum"], url
        raise LookupFailed("blocked", f"{store_name} recusou a consulta automática (teste).")

    def fake_get_text(url, source_name):
        calls.append(url)
        assert url == "https://docs.google.com/spreadsheets/d/TESTE123/gviz/tq?"
        return pages["coupons"]

    from app.services import coupons as coupons_mod

    monkeypatch.setattr(stores_mod, "get_html", fake_get_html)
    monkeypatch.setattr(coupons_mod, "get_html", fake_get_html)
    monkeypatch.setattr(coupons_mod, "get_text", fake_get_text)
    lookup_svc.clear_cache()
    http_mod.reset_state()
    return {"pages": pages, "calls": calls}


@pytest.fixture(autouse=True)
def isolated_vapid(monkeypatch, tmp_path):
    # chaves VAPID dos testes ficam numa pasta temporária, nunca em backend/instance
    monkeypatch.setenv("VAPID_PRIVATE_KEY_FILE", str(tmp_path / "vapid_test.pem"))


@pytest.fixture(autouse=True)
def no_ml_credentials(monkeypatch):
    # Nenhum teste usa credenciais reais nem envia mensagens de verdade.
    for k in ("ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REDIRECT_URI",
              "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "NTFY_TOPIC", "NTFY_SERVER"):
        monkeypatch.delenv(k, raising=False)
    from app.services import notify

    def blocked(*a, **kw):
        raise AssertionError("Teste tentou acessar a rede de notificações sem simulação.")

    monkeypatch.setattr(notify._http, "post", blocked)
    from app.services import webpush as webpush_mod

    monkeypatch.setattr(webpush_mod, "webpush", blocked)


@pytest.fixture()
def client(fake_web):
    app = create_app(TestConfig)
    with app.test_client() as c:
        c.application = app
        yield c
