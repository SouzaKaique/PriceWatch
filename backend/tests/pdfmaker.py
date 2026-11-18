"""Gerador mínimo de PDF para os testes (texto posicionado + links clicáveis)."""


def _esc(s: str) -> bytes:
    raw = s.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def make_pdf(pages, encrypt_note=False) -> bytes:
    """pages: lista de dicts {"texts": [(x, y, size, texto)], "links": [((x1, y1, x2, y2), url)]}"""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    pages_id = len(objs) + 1  # reservado abaixo
    objs.append(b"")  # placeholder Pages
    page_ids = []
    for pg in pages:
        stream = b"".join(
            b"BT /F1 %d Tf %.1f %.1f Td (" % (size, x, y) + _esc(t) + b") Tj ET\n" for x, y, size, t in pg["texts"]
        )
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream")
        annots = []
        for (x1, y1, x2, y2), url in pg.get("links", []):
            annots.append(add(
                b"<< /Type /Annot /Subtype /Link /Rect [%.1f %.1f %.1f %.1f] /Border [0 0 0] "
                b"/A << /S /URI /URI (" % (x1, y1, x2, y2) + _esc(url) + b") >> >>"
            ))
        annot_ref = (b" /Annots [" + b" ".join(b"%d 0 R" % a for a in annots) + b"]") if annots else b""
        page_ids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >>" % (pages_id, content, font) + annot_ref + b" >>"
        ))
    objs[pages_id - 1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % p for p in page_ids) + \
        b"] /Count %d >>" % len(page_ids)
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, xref)
    return bytes(out)
