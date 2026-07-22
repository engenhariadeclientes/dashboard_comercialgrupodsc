"""Matching (unificação de identidade) — spec seção 6.

Ordem de resolução: telefone normalizado (com variações) → e-mail → nome fuzzy
(nunca resolve sozinho, só gera fila de revisão) → cria lead novo.
"""
from typing import Optional

LIMIAR_FUZZY_NOME = 0.85


def encontrar_lead_por_telefone(conn, telefone: Optional[str], variacoes: list[str]) -> Optional[int]:
    if not telefone and not variacoes:
        return None
    candidatos = list({v for v in ([telefone] if telefone else []) + (variacoes or []) if v})
    if not candidatos:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM leads
            WHERE telefone = ANY(%s) OR telefone_variacoes && %s
            LIMIT 1
            """,
            (candidatos, candidatos),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def encontrar_lead_por_email(conn, email: Optional[str]) -> Optional[int]:
    if not email:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM leads WHERE email = %s LIMIT 1", (email,))
        row = cur.fetchone()
        return row["id"] if row else None


def encontrar_candidato_por_nome(conn, nome: Optional[str], limiar: float = LIMIAR_FUZZY_NOME) -> Optional[dict]:
    """Busca o melhor candidato por similaridade de nome (pg_trgm). Não resolve sozinho."""
    if not nome:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, nome, similarity(nome, %s) AS score
            FROM leads
            WHERE nome %% %s
            ORDER BY score DESC
            LIMIT 1
            """,
            (nome, nome),
        )
        row = cur.fetchone()
        if row and row["score"] >= limiar:
            return {"lead_id": row["id"], "nome": row["nome"], "score": float(row["score"])}
        return None


def registrar_matching_pendente(
    conn,
    lead_id_candidato: int,
    nome_recebido: Optional[str],
    telefone_recebido: Optional[str],
    email_recebido: Optional[str],
    fonte: str,
    similaridade: float,
    payload: Optional[dict] = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO matching_pendente
                (lead_id_candidato, nome_recebido, telefone_recebido, email_recebido,
                 fonte, similaridade, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                lead_id_candidato,
                nome_recebido,
                telefone_recebido,
                email_recebido,
                fonte,
                similaridade,
                psycopg_json(payload),
            ),
        )


def psycopg_json(payload):
    from psycopg.types.json import Jsonb

    return Jsonb(payload) if payload is not None else None


def resolver_ou_criar_lead(conn, dados: dict, fonte: str) -> tuple[int, bool]:
    """Resolve o lead existente ou cria um novo. Retorna (lead_id, criado).

    `dados` aceita as chaves de colunas de `leads` que se aplicarem (nome, telefone,
    telefone_variacoes, email, cidade, uf, regiao, marca, uf_derivada_por_ddd,
    profissao_funcao, canal_entrada, campanha_entrada, origem_detalhe_entrada,
    tipo_captura, data_entrada, ...).
    """
    telefone = dados.get("telefone")
    variacoes = dados.get("telefone_variacoes") or []
    email = dados.get("email")
    nome = dados.get("nome")

    lead_id = encontrar_lead_por_telefone(conn, telefone, variacoes)
    if lead_id is None:
        lead_id = encontrar_lead_por_email(conn, email)

    if lead_id is None:
        candidato = encontrar_candidato_por_nome(conn, nome)
        if candidato:
            registrar_matching_pendente(
                conn,
                lead_id_candidato=candidato["lead_id"],
                nome_recebido=nome,
                telefone_recebido=telefone,
                email_recebido=email,
                fonte=fonte,
                similaridade=candidato["score"],
                payload=dados.get("payload"),
            )

    if lead_id is not None:
        return lead_id, False

    colunas = [k for k in dados.keys() if k != "payload"]
    valores = [dados[k] for k in colunas]
    placeholders = ", ".join(["%s"] * len(colunas))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO leads ({', '.join(colunas)}) VALUES ({placeholders}) RETURNING id",
            valores,
        )
        novo_id = cur.fetchone()["id"]
    return novo_id, True


def atualizar_campos_lead(conn, lead_id: int, campos: dict) -> dict:
    """Atualiza campos de um lead existente e retorna os valores anteriores
    (para o chamador preservar no payload do evento — regra de conflito da seção 6)."""
    if not campos:
        return {}
    colunas = list(campos.keys())
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(colunas)} FROM leads WHERE id = %s",
            (lead_id,),
        )
        anteriores = dict(cur.fetchone() or {})

        set_clause = ", ".join(f"{c} = %s" for c in colunas)
        cur.execute(
            f"UPDATE leads SET {set_clause}, atualizado_em = NOW() WHERE id = %s",
            [*campos.values(), lead_id],
        )
    return anteriores
