"""Inserção idempotente de eventos (constraint anti-duplicação da seção 4.3)."""
from datetime import datetime
from typing import Optional

from psycopg.types.json import Jsonb


def registrar_evento(
    conn,
    lead_id: Optional[int],
    fonte: str,
    tipo_evento: str,
    data_evento: datetime,
    canal: Optional[str] = None,
    campanha: Optional[str] = None,
    origem_detalhe: Optional[str] = None,
    payload: Optional[dict] = None,
) -> Optional[int]:
    """Insere o evento; se já existir (mesma fonte/tipo/lead/data_evento), não duplica.

    Também atualiza `leads.data_ultima_conversao` com a data deste evento, quando
    mais recente que a já registrada — é o sinal de "última conversão" usado nas
    análises de gestão (seção 019 da migration), diferente de `atualizado_em`, que
    muda a cada ciclo de sync mesmo sem nenhuma novidade real.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO eventos (lead_id, fonte, tipo_evento, canal, campanha, origem_detalhe, payload, data_evento)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fonte, tipo_evento, lead_id, data_evento) DO NOTHING
            RETURNING id
            """,
            (lead_id, fonte, tipo_evento, canal, campanha, origem_detalhe, Jsonb(payload) if payload is not None else None, data_evento),
        )
        row = cur.fetchone()
        evento_id = row["id"] if row else None

        if evento_id is not None and lead_id is not None:
            cur.execute(
                """
                UPDATE leads
                SET data_ultima_conversao = GREATEST(COALESCE(data_ultima_conversao, %s), %s)
                WHERE id = %s
                """,
                (data_evento, data_evento, lead_id),
            )

        return evento_id
