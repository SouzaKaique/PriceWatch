"""Importação de lista de desejos (PDF/texto)."""
import io

from app.services import wishlist_import as wl

from .pdfmaker import make_pdf

KABUM = "https://www.kabum.com.br/produto/644868/monitor-gamer-lg-24-full-hd-100hz"
ML = "https://produto.mercadolivre.com.br/MLB-1234567890-monitor-lg-24ms500-_JM"
AMAZON = "https://www.amazon.com.br/Mouse-Logitech-G502-Hero/dp/B07GBZ4Q68/ref=sr_1_1?tag=x"


def favorites_pdf() -> bytes:
    """Simula a página de favoritos de uma loja impressa como PDF pelo navegador."""
    return make_pdf([{
        "texts": [
            (40, 800, 18, "Meus Favoritos"),
            (40, 770, 10, "Minha conta"),
            (60, 700, 12, "Monitor Gamer LG 24\" Full HD 100Hz IPS"),
            (60, 682, 11, "R$ 469,00"),
            (60, 664, 9, "Adicionar ao carrinho"),
            (60, 600, 12, "Mouse Gamer Logitech G502 HERO"),
            (60, 582, 11, "R$ 199,90"),
            (40, 60, 8, "Política de privacidade"),
            (500, 30, 8, "1/1"),
        ],
        "links": [
            ((55, 695, 400, 714), KABUM),
            ((55, 595, 400, 614), AMAZON),
            ((55, 660, 200, 674), "https://www.kabum.com.br/carrinho"),      # não é produto
            ((35, 765, 120, 780), "https://www.kabum.com.br/minha-conta"),   # menu
            ((35, 55, 200, 70), "https://www.kabum.com.br/institucional/privacidade"),
            ((300, 695, 380, 714), KABUM + "?utm_source=favoritos"),          # mesmo produto (imagem)
        ],
    }])


def names_only_pdf() -> bytes:
    return make_pdf([{
        "texts": [
            (40, 800, 16, "Lista de desejos - Black Friday"),
            (40, 760, 12, "Placa de Vídeo RTX 5060 8GB - até R$ 1.999,00"),
            (40, 740, 12, "SSD Kingston NV3 1TB R$ 419,90"),
            (40, 720, 12, "Headset HyperX Cloud III"),
            (40, 700, 12, ML),
            (40, 680, 12, "Cadeira"),
            (40, 40, 8, "Página 1 de 1"),
        ],
    }])


def test_url_filter_and_names_from_url():
    assert wl.is_product_url(KABUM) and wl.is_product_url(AMAZON) and wl.is_product_url(ML)
    assert not wl.is_product_url("https://www.kabum.com.br/carrinho")
    assert not wl.is_product_url("https://www.pichau.com.br/hardware")
    assert wl.is_product_url("https://www.pichau.com.br/monitor-gamer-lg-ultragear-27-ips")
    assert not wl.is_product_url("https://www.exemplo.com/produto/1")
    assert wl.name_from_url(KABUM) == "Monitor Gamer Lg 24 Full Hd 100hz"
    assert wl.name_from_url(AMAZON) == "Mouse Logitech G502 Hero"


def test_pdf_with_clickable_links_like_printed_favorites(client):
    r = client.post("/api/import/parse", data={"file": (io.BytesIO(favorites_pdf()), "favoritos.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    items = body["items"]
    names = [i["name"] for i in items]
    assert names == ["Monitor Gamer LG 24\" Full HD 100Hz IPS", "Mouse Gamer Logitech G502 HERO"]
    mon, mouse = items
    assert mon["urls"][0]["url"] == "https://www.kabum.com.br/produto/644868" and len(mon["urls"]) == 1
    assert mon["price_seen_cents"] == 46900 and mouse["price_seen_cents"] == 19990
    assert mouse["urls"][0]["url"] == "https://www.amazon.com.br/dp/B07GBZ4Q68"  # sem rastreamento
    assert all(i["checked"] for i in items)
    assert body["stats"]["product_links"] == 2 and body["stats"]["links"] == 6


def test_pdf_with_names_prices_and_target(client):
    r = client.post("/api/import/parse", data={"file": (io.BytesIO(names_only_pdf()), "lista.pdf")},
                    content_type="multipart/form-data")
    items = {i["name"]: i for i in r.get_json()["items"]}
    gpu = items["Placa de Vídeo RTX 5060 8GB"]
    assert gpu["target_price_cents"] == 199900 and gpu["price_seen_cents"] is None  # "até R$" = alvo
    ssd = items["SSD Kingston NV3 1TB"]
    assert ssd["price_seen_cents"] == 41990 and ssd["target_price_cents"] is None
    headset = items["Headset HyperX Cloud III"]
    assert headset["urls"][0]["store"] == "mercadolivre"  # link na linha de baixo vira oferta dele
    assert "Lista de desejos - Black Friday" not in items  # título
    assert "Cadeira" not in items  # curto demais
    assert all("Página" not in n for n in items)
    assert not any(i["urls"] for n, i in items.items() if n != "Headset HyperX Cloud III")
    assert all("Sem link" in " ".join(i["warnings"]) for n, i in items.items() if n != "Headset HyperX Cloud III")


def test_pasted_text_with_links(client):
    text = f"Monitor LG 24MS500\n{KABUM}\n{ML}\n\nMouse G502\n{AMAZON}\n"
    items = client.post("/api/import/parse", json={"text": text}).get_json()["items"]
    assert [i["name"] for i in items] == ["Monitor LG 24MS500", "Mouse G502"]
    assert [u["store"] for u in items[0]["urls"]] == ["kabum", "mercadolivre"]


def test_scanned_or_invalid_files_are_explained(client):
    image_only = make_pdf([{"texts": []}])
    r = client.post("/api/import/parse", data={"file": (io.BytesIO(image_only), "scan.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 422 and "digitalizada" in r.get_json()["message"]
    r = client.post("/api/import/parse", data={"file": (io.BytesIO(b"nao sou pdf"), "x.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 422 and "não parece ser um PDF" in r.get_json()["message"]
    assert client.post("/api/import/parse", json={"text": "  "}).status_code == 422


def test_already_monitored_is_flagged_and_skipped(client, fake_web):
    client.post("/api/products", json={"name": "Já tenho", "offers": [{"url": KABUM}]})
    items = client.post("/api/import/parse", data={"file": (io.BytesIO(favorites_pdf()), "f.pdf")},
                        content_type="multipart/form-data").get_json()["items"]
    mon = items[0]
    assert mon["urls"][0]["existing"]["name"] == "Já tenho" and mon["checked"] is False
    assert "Já monitorado." in mon["warnings"]


def test_bulk_import_creates_products_and_skips_duplicates(client, fake_web):
    client.post("/api/lookup", json={"url": KABUM})  # consulta feita na revisão → preço real no cadastro
    payload = {"items": [
        {"name": "Monitor LG 24", "target_price_cents": 45000, "offers": [{"url": KABUM}]},
        {"name": "Mouse G502", "offers": [{"url": AMAZON}]},
        {"name": "Headset sem link", "offers": []},
        {"name": "", "offers": []},  # inválido
    ]}
    r = client.post("/api/products/import", json=payload)
    assert r.status_code == 201
    body = r.get_json()
    assert [c["name"] for c in body["created"]] == ["Monitor LG 24", "Mouse G502", "Headset sem link"]
    assert body["errors"][0]["index"] == 3 and "name" in body["errors"][0]["fields"]
    products = {p["name"]: p for p in client.get("/api/products").get_json()}
    assert products["Monitor LG 24"]["summary"]["best_price_cents"] == 46900  # veio do cache da revisão
    assert products["Monitor LG 24"]["target_price_cents"] == 45000

    again = client.post("/api/products/import", json={"items": [payload["items"][0]]})
    assert again.status_code == 422 and again.get_json()["skipped"][0]["reason"] == "Já monitorado."
    assert len(client.get("/api/products").get_json()) == 3


def test_import_limits(client):
    assert client.post("/api/products/import", json={"items": []}).status_code == 422
    big = {"items": [{"name": f"P{i}"} for i in range(301)]}
    assert client.post("/api/products/import", json=big).status_code == 422


def test_two_column_cards_and_footer(client):
    """Cartões lado a lado (link da imagem antes do título) e rodapé legal."""
    pdf = make_pdf([{
        "texts": [
            (40, 700, 12, "Monitor LG 24MS500 IPS"), (40, 680, 12, "R$ 469,00"),
            (320, 700, 12, "Placa RTX 5060 8GB"), (320, 680, 12, "R$ 1.999,90"),
            (40, 40, 8, "Política de privacidade · Página 1 de 1"),
        ],
        "links": [
            ((40, 720, 160, 780), KABUM),               # imagem, acima do título
            ((35, 695, 260, 714), KABUM),               # título
            ((315, 695, 560, 714), "https://www.kabum.com.br/produto/999999/placa-rtx-5060"),
        ],
    }])
    items = client.post("/api/import/parse", data={"file": (io.BytesIO(pdf), "f.pdf")},
                        content_type="multipart/form-data").get_json()["items"]
    prices = {i["name"]: i["price_seen_cents"] for i in items}
    assert prices == {"Monitor LG 24MS500 IPS": 46900, "Placa RTX 5060 8GB": 199990}


def test_name_only_item_already_registered_is_not_reselected(client):
    client.post("/api/products", json={"name": "Headset HyperX Cloud III"})
    items = {i["name"]: i for i in client.post(
        "/api/import/parse", json={"text": "Headset HyperX Cloud III\nSSD Kingston NV3 1TB R$ 419,90"}
    ).get_json()["items"]}
    assert items["Headset HyperX Cloud III"]["checked"] is False
    assert "Já existe um produto com este nome." in items["Headset HyperX Cloud III"]["warnings"]
    assert items["SSD Kingston NV3 1TB"]["checked"] is True
