"""Worker sync_agendor — spec seção 5.5. Roda a cada 30 min (cron Railway).

Snapshot-diff: compara o estado atual da API com o que está em `negocios` e gera
eventos mudou_etapa, mudou_funil, valor_lancado, ganho, perdido, negocio_criado,
negocio_desqualificado. Idempotente (eventos só disparam em transições reais) e
incremental (usa sync_state, mas sempre relê todos os deals abertos pois a API
não confirma ter um filtro de "atualizado desde" documentado — ver aviso em
agendor_api.py).
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workers.agendor_api import buscar_organizacao, buscar_pessoa, listar_deals  # noqa: E402
from workers.common.db import get_connection  # noqa: E402
from workers.common.eventos import registrar_evento  # noqa: E402
from workers.common.matching import atualizar_campos_lead, resolver_ou_criar_lead  # noqa: E402
from workers.common.normalizacao import (  # noqa: E402
    derivar_marca,
    extrair_telefone_valido,
    gerar_variacoes_telefone,
    normalizar_email,
    normalizar_nome,
)
from workers.common.regras_negocio import (  # noqa: E402
    eh_etapa_assinatura_contrato,
    eh_etapa_lead_sem_perfil,
    eh_etapa_proposta_enviada,
    eh_nome_jornada_porter,
    extrair_regiao_jornada_porter,
    mapear_canal_origem_agendor,
    mapear_status,
)
from workers.common.sync_state import registrar_sync  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sync_agendor")

WORKER = "sync_agendor"
FONTE = "agendor"


def _resolver_lead(conn, deal: dict) -> Optional[int]:
    pessoa_id = deal.get("pessoa_id")
    organizacao_id = deal.get("organizacao_id")

    origem_detalhe_org = None
    if pessoa_id is not None:
        pessoa = buscar_pessoa(pessoa_id) or {}
        nome_raw = pessoa.get("nome") or deal.get("pessoa_nome_resumo")
        email_raw = pessoa.get("email") or deal.get("pessoa_email_resumo")
    elif organizacao_id is not None:
        # negócio sem pessoa vinculada, só organização — achado real 22/07/2026
        # ("laurita sasse" cadastrada como organização, não como pessoa): o
        # contato (telefone/e-mail/origem) só existe no registro da organização
        pessoa = buscar_organizacao(organizacao_id) or {}
        nome_raw = pessoa.get("nome") or deal.get("organizacao_nome")
        email_raw = pessoa.get("email")
        origem_detalhe_org = pessoa.get("origem_detalhe")
    else:
        return None

    nome = normalizar_nome(nome_raw)
    email = normalizar_email(email_raw)
    telefone, invalido = extrair_telefone_valido(pessoa.get("telefone")) if pessoa.get("telefone") else (None, True)
    if invalido:
        telefone = None

    if not (nome or email or telefone):
        return None

    variacoes = gerar_variacoes_telefone(telefone) if telefone else []
    marca_info = derivar_marca(
        conn, cidade=pessoa.get("cidade"), uf_informada=pessoa.get("uf"), telefone_e164=telefone,
        consultor=deal.get("consultor"),
    )

    # sinal do nome (seção "Jornada Porter" — decisão 22/07/2026): o Agendor sozinho
    # não sabe a origem real do contato, mas o nome costuma denunciar "JP-<região>"
    if eh_nome_jornada_porter(nome_raw):
        canal_entrada = "evento"
        regiao_jp = extrair_regiao_jornada_porter(nome_raw)
        campanha_entrada = f"Jornada_Porter_{regiao_jp}" if regiao_jp else "Jornada_Porter"
    elif origem_detalhe_org:
        # leadOrigin da organização (ex.: "Redes Sociais" -> meta_ads)
        canal_entrada = mapear_canal_origem_agendor(origem_detalhe_org)
        campanha_entrada = None
    else:
        canal_entrada = "organico"
        campanha_entrada = None

    dados = {
        "nome": nome,
        "telefone": telefone,
        "telefone_variacoes": variacoes or None,
        "email": email,
        "cidade": pessoa.get("cidade"),
        "profissao_funcao": pessoa.get("profissao_funcao"),
        "marca": marca_info["marca"],
        "uf": marca_info["uf"],
        "regiao": marca_info["regiao"],
        "uf_derivada_por_ddd": marca_info["uf_derivada_por_ddd"],
        "canal_entrada": canal_entrada,
        "campanha_entrada": campanha_entrada,
        "origem_detalhe_entrada": origem_detalhe_org,
        "data_entrada": deal.get("data_criacao") or datetime.now(timezone.utc),
        "payload": {"origem": "sync_agendor", "organizacao": pessoa.get("organizacao_nome") or deal.get("organizacao_nome")},
    }
    lead_id, criado = resolver_ou_criar_lead(conn, dados, fonte=FONTE)
    if not criado:
        atualizar_campos_lead(conn, lead_id, {k: dados[k] for k in ("marca", "uf", "regiao") if dados.get(k)})
    return lead_id


def _buscar_negocio_atual(conn, agendor_negocio_id: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM negocios WHERE agendor_negocio_id = %s",
            (agendor_negocio_id,),
        )
        return cur.fetchone()


def _upsert_negocio(conn, deal: dict, lead_id: Optional[int]) -> None:
    status = mapear_status(deal.get("status_nome"))
    etapa = deal.get("etapa")
    valor = deal.get("valor")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO negocios
                (agendor_negocio_id, lead_id, titulo, funil, etapa_atual, consultor,
                 valor, mensalidade_media, status, motivo_perda, data_criacao, data_fechamento)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (agendor_negocio_id) DO UPDATE SET
                lead_id = COALESCE(negocios.lead_id, EXCLUDED.lead_id),
                titulo = EXCLUDED.titulo,
                funil = EXCLUDED.funil,
                etapa_atual = EXCLUDED.etapa_atual,
                consultor = EXCLUDED.consultor,
                valor = EXCLUDED.valor,
                mensalidade_media = CASE WHEN negocios.mensalidade_ajustada THEN negocios.mensalidade_media ELSE EXCLUDED.valor END,
                status = EXCLUDED.status,
                motivo_perda = EXCLUDED.motivo_perda,
                data_fechamento = EXCLUDED.data_fechamento,
                atualizado_em = NOW()
            """,
            (
                deal["agendor_negocio_id"], lead_id, deal.get("titulo"), deal.get("funil"),
                etapa, deal.get("consultor"), valor, valor,
                status, deal.get("motivo_perda"), deal.get("data_criacao"), deal.get("data_fechamento"),
            ),
        )

    if lead_id is not None:
        gerou_proposta = eh_etapa_proposta_enviada(etapa) or bool(valor)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE leads SET
                    agendor_negocio_id = %s,
                    consultor = %s,
                    etapa_atual = %s,
                    gerou_proposta = %s OR leads.gerou_proposta,
                    valor_orcamento = CASE WHEN %s THEN %s ELSE leads.valor_orcamento END,
                    status_final = %s,
                    data_fechamento = %s,
                    atualizado_em = NOW()
                WHERE id = %s
                """,
                (deal["agendor_negocio_id"], deal.get("consultor"), etapa, gerou_proposta,
                 gerou_proposta, valor, status, deal.get("data_fechamento"), lead_id),
            )


def _processar_deal(conn, deal: dict, agora: datetime) -> None:
    agendor_id = deal.get("agendor_negocio_id")
    if agendor_id is None:
        logger.warning("Deal sem id, ignorado: %s", deal.get("titulo"))
        return

    anterior = _buscar_negocio_atual(conn, agendor_id)
    lead_id = anterior["lead_id"] if anterior else _resolver_lead(conn, deal)
    novo_status = mapear_status(deal.get("status_nome"))

    _upsert_negocio(conn, deal, lead_id)

    if anterior is None:
        registrar_evento(conn, lead_id, FONTE, "negocio_criado", deal.get("data_criacao") or agora,
                          canal=None, campanha=deal.get("funil"), origem_detalhe=deal.get("etapa"),
                          payload={"agendor_negocio_id": agendor_id})
        # negócio já nasce em uma etapa/estado que pode disparar regras (ex.: carga feita
        # direto numa etapa avançada) — trata como transição a partir de "nada"
        etapa_anterior, funil_anterior, valor_anterior, status_anterior = None, None, None, "aberto"
    else:
        etapa_anterior = anterior["etapa_atual"]
        funil_anterior = anterior["funil"]
        valor_anterior = float(anterior["valor"]) if anterior["valor"] is not None else None
        status_anterior = anterior["status"]

    etapa_nova = deal.get("etapa")
    funil_novo = deal.get("funil")
    valor_novo = deal.get("valor")

    if funil_anterior is not None and funil_novo != funil_anterior:
        registrar_evento(conn, lead_id, FONTE, "mudou_funil", agora,
                          campanha=funil_novo, origem_detalhe=etapa_nova,
                          payload={"agendor_negocio_id": agendor_id, "funil_de": funil_anterior,
                                   "funil_para": funil_novo, "etapa_de_chegada": etapa_nova})

    if etapa_nova != etapa_anterior:
        registrar_evento(conn, lead_id, FONTE, "mudou_etapa", agora,
                          campanha=funil_novo, origem_detalhe=etapa_nova,
                          payload={"agendor_negocio_id": agendor_id, "etapa_de": etapa_anterior, "etapa_para": etapa_nova})

        if eh_etapa_proposta_enviada(etapa_nova) and not eh_etapa_proposta_enviada(etapa_anterior):
            registrar_evento(conn, lead_id, FONTE, "proposta_gerada", agora,
                              payload={"agendor_negocio_id": agendor_id, "valor": valor_novo})

        if eh_etapa_lead_sem_perfil(etapa_nova) and not eh_etapa_lead_sem_perfil(etapa_anterior):
            registrar_evento(conn, lead_id, FONTE, "negocio_desqualificado", agora,
                              payload={"agendor_negocio_id": agendor_id, "etapa": etapa_nova})

        if eh_etapa_assinatura_contrato(etapa_nova) and status_anterior != "ganho":
            registrar_evento(conn, lead_id, FONTE, "ganho", agora, payload={"agendor_negocio_id": agendor_id})

    if valor_novo and valor_novo != valor_anterior:
        registrar_evento(conn, lead_id, FONTE, "valor_lancado", agora,
                          payload={"agendor_negocio_id": agendor_id, "valor": valor_novo, "valor_anterior": valor_anterior})
        if not eh_etapa_proposta_enviada(etapa_anterior):
            registrar_evento(conn, lead_id, FONTE, "proposta_gerada", agora,
                              payload={"agendor_negocio_id": agendor_id, "valor": valor_novo})

    if novo_status != status_anterior:
        if novo_status == "ganho":
            registrar_evento(conn, lead_id, FONTE, "ganho", agora, payload={"agendor_negocio_id": agendor_id})
        elif novo_status == "perdido":
            registrar_evento(conn, lead_id, FONTE, "perdido", agora,
                              payload={"agendor_negocio_id": agendor_id, "motivo": deal.get("motivo_perda")})


def rodar() -> None:
    agora = datetime.now(timezone.utc)
    processados = 0
    with get_connection() as conn:
        for deal in listar_deals():
            try:
                _processar_deal(conn, deal, agora)
                processados += 1
            except Exception:
                logger.exception("Falha processando deal %s", deal.get("agendor_negocio_id"))
                conn.rollback()
                continue
            conn.commit()

        registrar_sync(conn, WORKER, agora, detalhes={"deals_processados": processados})
        conn.commit()

    logger.info("sync_agendor concluído: %d deals processados", processados)


if __name__ == "__main__":
    rodar()
