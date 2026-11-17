"""Fábrica da aplicação Flask do PRICE WATCH."""
import hmac
import os
import logging
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .config import BASE_DIR, Config
from .extensions import db

APP_VERSION = "0.1.0"


def create_app(config_class: type = Config) -> Flask:
    instance = os.getenv("PRICEWATCH_INSTANCE_DIR", "").strip() or str(BASE_DIR / "instance")
    app = Flask(__name__, instance_path=instance)
    app.config.from_object(config_class)
    app.config["APP_VERSION"] = APP_VERSION
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    @app.before_request
    def _require_api_key():
        key = app.config["API_ACCESS_KEY"]
        if not key or request.method == "OPTIONS" or request.path == "/api/health":
            return None
        if request.path.startswith("/api/"):
            sent = request.headers.get("X-API-Key", "")
            if not hmac.compare_digest(sent, key):
                return jsonify({"error": "unauthorized"}), 401
        return None

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        return jsonify({"error": exc.name, "message": exc.description}), exc.code

    from .routes.health import bp as health_bp
    from .routes.coupons import bp as coupons_bp
    from .routes.integrations import bp as integrations_bp
    from .routes.monitor import bp as monitor_bp
    from .routes.notifications import bp as notifications_bp
    from .routes.products import bp as products_bp

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(products_bp, url_prefix="/api")
    app.register_blueprint(integrations_bp, url_prefix="/api")
    app.register_blueprint(monitor_bp, url_prefix="/api")
    app.register_blueprint(coupons_bp, url_prefix="/api")
    app.register_blueprint(notifications_bp, url_prefix="/api")

    # Por último: o PWA responde a tudo que não for /api
    from .routes.spa import bp as spa_bp

    app.register_blueprint(spa_bp)

    with app.app_context():
        from . import models  # noqa: F401  (registra as tabelas)
        from .migrations import ensure_columns

        db.create_all()
        ensure_columns()

        from .services.maintenance import check_integrity

        check_integrity()

    return app
