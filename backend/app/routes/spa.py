"""Serve o PWA (build de produção do Angular) no mesmo endereço da API.

Assim o app instalado no celular e a API ficam na mesma origem: sem CORS, com
service worker e notificações Web Push funcionando quando acessado por HTTPS.
"""
from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, send_from_directory

bp = Blueprint("spa", __name__)

# Arquivos que precisam ser sempre revalidados (o resto tem hash no nome).
NO_CACHE = {"index.html", "ngsw.json", "ngsw-worker.js", "safety-worker.js", "worker-basic.min.js",
            "manifest.webmanifest"}


def _dist() -> Path | None:
    path = Path(current_app.config["FRONTEND_DIST"])
    return path if (path / "index.html").is_file() else None


@bp.get("/", defaults={"path": ""})
@bp.get("/<path:path>")
def serve(path: str):
    if path.startswith("api/") or path == "api":
        abort(404)
    dist = _dist()
    if dist is None:
        return jsonify({
            "error": "frontend_not_built",
            "message": "Build do app não encontrado. Rode 'npm run build' na pasta frontend "
                       "(ou use 'npm start' em desenvolvimento, em http://localhost:4200).",
        }), 404

    target = (dist / path).resolve() if path else dist / "index.html"
    if path and dist.resolve() in target.parents and target.is_file():
        resp = send_from_directory(dist, path)
        name = target.name
    else:
        # Rotas do app (ex.: /produtos/3) → index.html; o Angular resolve no navegador.
        if "." in Path(path).name:
            abort(404)  # arquivo inexistente: não mascarar com index.html
        resp = send_from_directory(dist, "index.html")
        name = "index.html"

    if name in NO_CACHE:
        resp.headers["Cache-Control"] = "no-cache"
    elif path.endswith((".js", ".css")) and "-" in name:
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp
