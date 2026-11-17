r"""Diagnóstico pela linha de comando (não precisa do backend rodando):

    .venv\Scripts\python diagnostico.py
"""
import sys

from app import create_app
from app.services import diagnostics

ICON = {"ok": "[ OK ]", "warn": "[ ATENÇÃO ]", "error": "[ ERRO ]"}

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    app = create_app()
    with app.app_context():
        items = diagnostics.run(include_scheduler=False)
    for it in items:
        print(f"{ICON[it['status']]:<12} {it['label']}: {it['detail']}")
        if it["hint"]:
            print(f"{'':<12} → {it['hint']}")
    sys.exit(1 if any(i["status"] == "error" for i in items) else 0)
