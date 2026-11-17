"""Migração mínima para SQLite: adiciona colunas novas em tabelas já existentes.

`db.create_all()` cria tabelas, mas não altera as existentes. Como o banco é
local e as mudanças são aditivas, basta um ALTER TABLE ADD COLUMN por coluna
ausente — sem perder dados já coletados.
"""
import logging

from sqlalchemy import inspect, text

from .extensions import db

log = logging.getLogger(__name__)


def ensure_columns() -> None:
    engine = db.engine
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in db.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable and column.default is None and column.server_default is None:
                    log.error("Coluna obrigatória %s.%s precisa de migração manual", table.name, column.name)
                    continue
                ddl_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}'))
                log.info("Coluna adicionada: %s.%s", table.name, column.name)
