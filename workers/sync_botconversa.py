"""Worker sync_botconversa — spec seção 5.2, adaptado com dados reais (22/07/2026).

Roda pras duas contas (DSC e Duplique). Pra cada assinante do BotConversa:
resolve/atualiza o lead (telefone primeiro) e mantém os campos da camada IA
(passou_ia, status_ia, qualificado_sql, data_qualificacao) sincronizados, além
de registrar eventos (ia_iniciou_conversa, ia_qualificou, ia_desqualificou).

Decisão da Stella (22/07/2026): "repassado ao consultor" é sinalizado pelas tags
Distrib_<Nome> (conta DSC) / Enviado_<Nome> / Envio_<Nome> (conta Duplique) — tags
genéricas como "Consultor_escolheu" ou "Aguardando consultor escolher" são de
outro fluxo e NÃO contam. Lead sem essa tag = está sendo tratado pela IA.

Para leads já existentes (matched por telefone/e-mail), só os campos da camada
IA são atualizados — canal_entrada/campanha_entrada/marca do primeiro toque
nunca são sobrescritos por este worker. Só leads genuinamente novos (nunca
vistos antes) recebem canal_entrada derivado do BotConversa.
"""
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workers.botconversa_api import listar_subscribers  # noqa: E402
from workers.common.db import ConexaoComReconexao  # noqa: E402
from workers.common.eventos import registrar_evento  # noqa: E402
from workers.common.matching import atualizar_campos_lead, resolver_ou_criar_lead  # noqa: E402
from workers.common.normalizacao import (  # noqa: E402
    derivar_marca,
    extrair_telefone_valido,
    gerar_variacoes_telefone,
    normalizar_email,
    normalizar_nome,
)
from workers.common.sync_state import registrar_sync  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sync_botconversa")

WORKER = "sync_botconversa"
FONTE = "botconversa"

CONTAS = {
    "DSC": "BOTCONVERSA_API_KEY_DSC",
    "Duplique": "BOTCONVERSA_API_KEY_DUP",
}

_RE_TAG_REPASSE = re.compile(r"^(distrib|enviado|envio)_(.+)$", re.IGNORECASE)

# valores reais observados em "Canal de Aquisição" (22/07/2026) — o que não mapear
# fica sem canal definido (o lead resolve pelo canal do primeiro toque, se houver)
CANAL_AQUISICAO_MAP = {
    "facebook ads": "meta_ads",
    "anúncio": "meta_ads",
    "anuncio": "meta_ads",
    "anúncio instagram": "meta_ads",
    "anuncio meta": "meta_ads",
    "cadastro no site dsc": "site",
}


def _extrair_consultor_repasse(tags: list[str]) -> Optional[str]:
    for tag in tags:
        m = _RE_TAG_REPASSE.match(tag.strip())
        if m:
            return m.group(2).strip()
    return None


def _mapear_canal(canal_raw: Optional[str]) -> Optional[str]:
    if not canal_raw:
        return None
    return CANAL_AQUISICAO_MAP.get(canal_raw.strip().lower())


def _calcular_status_ia(variaveis: dict, tags: list[str], consultor_repasse: Optional[str]) -> tuple[str, bool]:
    if variaveis.get("MOTIVO_NAO_QUAL"):
        return "desqualificado", False
    if consultor_repasse:
        return "qualificado", True
    if any(t.strip().lower() == "insucesso" for t in tags):
        return "sem_resposta", False
    return "em_conversa", False


TAGS_IGNORADAS = {"contato_operacional"}  # contatos não comerciais (decisão da Stella, 22/07/2026)


def _processar_subscriber(conn, sub: dict, marca_conta: str, agora: datetime) -> None:
    variaveis = sub.get("variables") or {}
    tags = sub.get("tags") or []

    if any(t.strip().lower() in TAGS_IGNORADAS for t in tags):
        return

    nome_raw = sub.get("full_name") or sub.get("first_name")
    email_raw = variaveis.get("Email")
    telefone_raw = sub.get("phone")

    nome = normalizar_nome(nome_raw)
    email = normalizar_email(email_raw)
    telefone, invalido = extrair_telefone_valido(telefone_raw) if telefone_raw else (None, True)
    if invalido:
        telefone = None

    if not (nome or email or telefone):
        return

    consultor_repasse = _extrair_consultor_repasse(tags)
    status_ia, qualificado_sql = _calcular_status_ia(variaveis, tags, consultor_repasse)
    regiao_bc = variaveis.get("REGIÃO")
    profissao = variaveis.get("cargo-funcao")

    # retrato consultável (sobrescrito a cada sync — diferente do payload de eventos,
    # que é histórico) dos campos personalizados mais úteis pro acompanhamento
    dados_botconversa = {
        "temperatura": variaveis.get("TEMPERATURA"),
        "perfil_cliente": variaveis.get("PERFIL_CLIENTE"),
        "resumo_conversa": variaveis.get("RESUMO CONVERSA") or variaveis.get("Resumo da conversa"),
        "data_solicitada": variaveis.get("DATA_SOLICITADA"),
        "horario_solicitado": variaveis.get("HORARIO_SOLICITADO"),
        "telefone_decisor": variaveis.get("TELEFONE_DECISOR"),
        "motivo_nao_qual": variaveis.get("MOTIVO_NAO_QUAL"),
        "canal_aquisicao_bc": variaveis.get("Canal de Aquisição"),
        "tags": tags,
        "conta": marca_conta,
    }

    variacoes = gerar_variacoes_telefone(telefone) if telefone else []

    # verifica se o lead já existe (pra decidir se mexe em canal_entrada/marca)
    lead_id_existente = None
    with conn.cursor() as cur:
        if telefone:
            cur.execute(
                "SELECT id, status_ia, canal_entrada FROM leads WHERE telefone = ANY(%s) OR telefone_variacoes && %s LIMIT 1",
                ([telefone, *variacoes], [telefone, *variacoes]),
            )
        else:
            cur.execute("SELECT id, status_ia, canal_entrada FROM leads WHERE email = %s LIMIT 1", (email,))
        row = cur.fetchone()
        if row:
            lead_id_existente = row["id"]
            status_ia_anterior = row["status_ia"]
            canal_atual = row["canal_entrada"]
        else:
            status_ia_anterior = None
            canal_atual = None

    if lead_id_existente is None:
        marca_info = derivar_marca(conn, cidade=regiao_bc, consultor=consultor_repasse)
        canal = _mapear_canal(variaveis.get("Canal de Aquisição")) or "organico"
        dados = {
            "nome": nome,
            "telefone": telefone,
            "telefone_variacoes": variacoes or None,
            "email": email,
            "regiao": marca_info["regiao"] or regiao_bc,
            "uf": marca_info["uf"],
            "marca": marca_info["marca"],
            "uf_derivada_por_ddd": marca_info["uf_derivada_por_ddd"],
            "profissao_funcao": profissao,
            "canal_entrada": canal,
            "campanha_entrada": None,
            "data_entrada": sub.get("created_at") or agora,
            "passou_ia": True,
            "status_ia": status_ia,
            "qualificado_sql": qualificado_sql,
            "dados_botconversa": Jsonb(dados_botconversa),
            "payload": {"origem": "sync_botconversa", "conta": marca_conta},
        }
        lead_id, _ = resolver_ou_criar_lead(conn, dados, fonte=FONTE)
    else:
        lead_id = lead_id_existente
        campos = {
            "dados_botconversa": Jsonb(dados_botconversa),
            "passou_ia": True,
            "status_ia": status_ia,
            "qualificado_sql": qualificado_sql,
        }
        # canal_entrada='organico' é a marca de "não sabemos a origem" — se o
        # BotConversa revela um canal concreto (ex.: Facebook Ads), corrige em vez
        # de manter uma atribuição que já era incerta (decisão da Stella, 22/07/2026)
        if canal_atual == "organico":
            canal_bc = _mapear_canal(variaveis.get("Canal de Aquisição"))
            if canal_bc:
                campos["canal_entrada"] = canal_bc
        atualizar_campos_lead(conn, lead_id, campos)

    data_evento_conversa = sub.get("created_at") or agora
    registrar_evento(conn, lead_id, FONTE, "ia_iniciou_conversa", data_evento_conversa,
                      payload={"conta": marca_conta})

    if status_ia != status_ia_anterior:
        if status_ia == "qualificado":
            with conn.cursor() as cur:
                cur.execute("UPDATE leads SET data_qualificacao = %s WHERE id = %s AND data_qualificacao IS NULL",
                            (agora, lead_id))
            registrar_evento(conn, lead_id, FONTE, "ia_qualificou", agora,
                              payload={"conta": marca_conta, "consultor_repasse": consultor_repasse,
                                       "temperatura": variaveis.get("TEMPERATURA"), "perfil": variaveis.get("PERFIL_CLIENTE")})
            if consultor_repasse:
                atualizar_campos_lead(conn, lead_id, {"consultor": consultor_repasse})
        elif status_ia == "desqualificado":
            registrar_evento(conn, lead_id, FONTE, "ia_desqualificou", agora,
                              payload={"conta": marca_conta, "motivo": variaveis.get("MOTIVO_NAO_QUAL")})

    conn.commit()


def rodar() -> None:
    import os

    agora = datetime.now(timezone.utc)
    total = 0
    conexao = ConexaoComReconexao()
    try:
        for marca_conta, env_var in CONTAS.items():
            api_key = os.environ.get(env_var)
            if not api_key:
                logger.warning("Variável %s não configurada, pulando conta %s", env_var, marca_conta)
                continue
            logger.info("Sincronizando conta %s", marca_conta)
            conta_total = 0
            for sub in listar_subscribers(api_key):
                try:
                    conexao.executar(lambda conn, sub=sub: _processar_subscriber(conn, sub, marca_conta, agora))
                except Exception:
                    logger.exception("Falha processando subscriber %s (conta %s)", sub.get("id"), marca_conta)
                    continue
                conta_total += 1
                total += 1
                if conta_total % 100 == 0:
                    logger.info("... %d processados (%s)", conta_total, marca_conta)
            logger.info("Conta %s concluída: %d subscribers processados", marca_conta, conta_total)

        conexao.executar(lambda conn: registrar_sync(conn, WORKER, agora, detalhes={"subscribers_processados": total}))
        conexao.commit()
    finally:
        conexao.close()

    logger.info("sync_botconversa concluído: %d subscribers processados no total", total)


if __name__ == "__main__":
    rodar()
