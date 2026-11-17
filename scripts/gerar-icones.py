"""Gera os ícones do PWA do PRICE WATCH (frontend/public/icons) com Pillow.

Uso (na raiz do projeto):
    backend\\.venv\\Scripts\\pip install -r backend\\requirements-dev.txt
    backend\\.venv\\Scripts\\python scripts\\gerar-icones.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "icons"
NAVY = (11, 17, 32, 255)
SURFACE = (19, 28, 46, 255)
LIME = (163, 230, 53, 255)
BLUE = (59, 130, 246, 255)

# Linha de "pulso" (como um gráfico de preço caindo para uma oportunidade), em coordenadas 0..1
PULSE = [(0.16, 0.50), (0.33, 0.50), (0.42, 0.30), (0.54, 0.72), (0.64, 0.42), (0.71, 0.56), (0.84, 0.56)]


def draw_icon(size: int, maskable: bool) -> Image.Image:
    scale = 4  # desenha grande e reduz (antialias)
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, s, s], fill=NAVY)  # sangra até a borda; conteúdo na zona segura (80%)
        inset, radius = 0.0, 0
        content = 0.62
    else:
        inset = s * 0.04
        radius = int(s * 0.22)
        d.rounded_rectangle([inset, inset, s - inset, s - inset], radius=radius, fill=NAVY)
        d.rounded_rectangle([inset, inset, s - inset, s - inset], radius=radius,
                            outline=SURFACE, width=max(2, int(s * 0.012)))
        content = 0.82

    off = s * (1 - content) / 2

    def pt(x, y):
        return (off + x * s * content, off + y * s * content)

    pts = [pt(x, y) for x, y in PULSE]
    width = max(3, int(s * 0.075 * content / 0.82))
    d.line(pts, fill=LIME, width=width, joint="curve")
    r = width / 2
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=LIME)
    # ponto azul: o "alerta" no fim do gráfico
    bx, by = pt(0.84, 0.30)
    br = s * 0.06 * content / 0.82
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=BLUE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (72, 96, 128, 144, 152, 192, 384, 512):
        draw_icon(size, maskable=False).save(OUT / f"icon-{size}x{size}.png", optimize=True)
    for size in (192, 512):
        draw_icon(size, maskable=True).save(OUT / f"maskable-{size}x{size}.png", optimize=True)
    # iPhone: ícone sem transparência (o iOS arredonda sozinho)
    apple = Image.new("RGBA", (180, 180), NAVY)
    apple.alpha_composite(draw_icon(180, maskable=True))
    apple.convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    fav = draw_icon(64, maskable=False)
    fav.save(ROOT / "frontend" / "public" / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print("Ícones gerados em", OUT)


if __name__ == "__main__":
    main()
