"""Controle de sync incremental por worker (spec seção 7)."""
from datetime import datetime
from typing import Optional


def obter_ultimo_sync(conn, worker: str) -> Optional[datetime]:
    with conn.cursor() as cur:
        cur.execute("SELECT ultimo_sync FROM sync_state WHERE worker = %s", (worker,))
        row = cur.fetchone()
        return row["ultimo_sync"] if row else None


def registrar_sync(conn, worker: str, momento: datetime, detalhes: Optional[dict] = None) -> None:
    from psycopg.types.json import Jsonb

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_state (worker, ultimo_sync, detalhes, atualizado_em)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (worker) DO UPDATE
                SET ultimo_sync = EXCLUDED.ultimo_sync,
                    detalhes = EXCLUDED.detalhes,
                    atualizado_em = NOW()
            """,
            (worker, momento, Jsonb(detalhes) if detalhes is not None else None),
        )
