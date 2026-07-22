"""Conexão com o Postgres. Lê DATABASE_URL do ambiente (Railway injeta em produção)."""
import logging
import os
import time

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger("db")


def get_connection() -> psycopg.Connection:
    database_url = os.environ["DATABASE_URL"]
    return psycopg.connect(database_url, row_factory=dict_row)


class ConexaoComReconexao:
    """Wrapper para scripts longos (importers) contra o proxy público do Railway,
    que derruba conexões ociosas/longas (~15-20 min observado empiricamente em
    22/07/2026). `executar(fn)` roda fn(conn) e reconecta+retenta em caso de
    OperationalError, em vez de deixar o script inteiro morrer no meio de uma
    carga de milhares de linhas."""

    def __init__(self, max_tentativas: int = 5):
        self.max_tentativas = max_tentativas
        self.conn = get_connection()

    def executar(self, fn):
        for tentativa in range(1, self.max_tentativas + 1):
            try:
                return fn(self.conn)
            except psycopg.OperationalError:
                logger.warning("Conexão caiu (tentativa %d/%d) — reconectando...", tentativa, self.max_tentativas)
                try:
                    self.conn.close()
                except Exception:
                    pass
                time.sleep(2)
                self.conn = get_connection()
        raise RuntimeError("Falha persistente de conexão com o Postgres")

    def commit(self) -> None:
        self.executar(lambda conn: conn.commit())

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
