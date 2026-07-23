"""Importer do export nativo (xlsx) de negócios do Agendor — spec seção 8.2, item 1.

Formato real confirmado em 22/07/2026 (export "445238-negocios-*.xlsx"): 48 colunas,
cabeçalho na linha 1. O export pode vir dividido em vários arquivos (mesmo cabeçalho).

Uso: python importers/agendor_historico.py arquivo1.xlsx [arquivo2.xlsx ...]
"""
import sys
from pathlib import Path
from typing import Optional

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importers.common_import import logger  # noqa: E402
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
from workers.common.regras_negocio import (  # noqa: E402
    eh_etapa_assinatura_contrato,
    eh_etapa_lead_sem_perfil,
    eh_etapa_proposta_enviada,
    eh_nome_jornada_porter,
    extrair_regiao_jornada_porter,
    mapear_canal_origem_agendor,
    mapear_status,
)

FONTE = "agendor"


def _valor_numerico(v) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _melhor_telefone(row: dict) -> Optional[str]:
    for campo in ("Celular", "WhatsApp", "Telefone"):
        raw = row.get(campo)
        if raw:
            telefone, invalido = extrair_telefone_valido(str(raw))
            if not invalido:
                return telefone
    return None


def _resolver_lead_ou_none(conn, row: dict) -> Optional[int]:
    # quando não há pessoa vinculada, mas há empresa/organização, a planilha do
    # Agendor já traz o telefone/e-mail da organização nas mesmas colunas —
    # só faltava usar o nome da empresa como fallback (decisão da Stella, 23/07/2026)
    nome_fonte = row.get("Pessoa relacionada") or row.get("Empresa relacionada")
    nome = normalizar_nome(nome_fonte)
    email = normalizar_email(row.get("E-mail"))
    telefone = _melhor_telefone(row)

    # negócio sem NENHUM dado de contato (comum em deals nomeados por condomínio,
    # sem pessoa vinculada) → não cria lead-fantasma; negocios.lead_id fica NULL
    if not (nome or email or telefone):
        return None

    variacoes = gerar_variacoes_telefone(telefone) if telefone else []
    cidade = row.get("Cidade")
    uf_informada = row.get("Estado")
    marca_info = derivar_marca(
        conn, cidade=cidade, uf_informada=uf_informada, telefone_e164=telefone,
        consultor=row.get("Usuário responsável"),
    )
    if eh_nome_jornada_porter(nome_fonte):
        canal = "evento"
        regiao_jp = extrair_regiao_jornada_porter(nome_fonte)
        campanha = f"Jornada_Porter_{regiao_jp}" if regiao_jp else "Jornada_Porter"
    else:
        canal = mapear_canal_origem_agendor(row.get("Origem do cliente"))
        campanha = None

    dados = {
        "nome": nome,
        "telefone": telefone,
        "telefone_variacoes": variacoes or None,
        "email": email,
        "cidade": cidade,
        "uf": marca_info["uf"],
        "regiao": marca_info["regiao"],
        "marca": marca_info["marca"],
        "uf_derivada_por_ddd": marca_info["uf_derivada_por_ddd"],
        "canal_entrada": canal,
        "campanha_entrada": campanha,
        "origem_detalhe_entrada": row.get("Origem do cliente"),
        "tipo_captura": None,
        "data_entrada": row.get("Data de cadastro") or row.get("Data de início"),
        "payload": {"origem_agendor": row.get("Origem do cliente")},
    }
    lead_id, criado = resolver_ou_criar_lead(conn, dados, fonte=FONTE)
    if not criado:
        atualizar_campos_lead(
            conn,
            lead_id,
            {k: dados[k] for k in ("cidade", "uf", "regiao", "marca", "uf_derivada_por_ddd") if dados.get(k) is not None},
        )
    return lead_id


def _upsert_negocio(conn, row: dict, lead_id: Optional[int]) -> None:
    agendor_id = row.get("Código do Negócio")
    if agendor_id is None:
        return
    agendor_id = int(agendor_id)

    valor = _valor_numerico(row.get("Valor"))
    status = mapear_status(row.get("Status"))
    etapa = row.get("Etapa")
    funil = row.get("Funil")

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO negocios
                (agendor_negocio_id, lead_id, titulo, funil, etapa_atual, consultor,
                 valor, mensalidade_media, status, motivo_perda, data_criacao, data_fechamento)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (agendor_negocio_id) DO UPDATE SET
                lead_id = EXCLUDED.lead_id,
                titulo = EXCLUDED.titulo,
                funil = EXCLUDED.funil,
                etapa_atual = EXCLUDED.etapa_atual,
                consultor = EXCLUDED.consultor,
                valor = EXCLUDED.valor,
                -- mensalidade_media só é sobrescrita se ainda não foi ajustada manualmente
                mensalidade_media = CASE WHEN negocios.mensalidade_ajustada THEN negocios.mensalidade_media ELSE EXCLUDED.mensalidade_media END,
                status = EXCLUDED.status,
                motivo_perda = EXCLUDED.motivo_perda,
                data_fechamento = EXCLUDED.data_fechamento,
                atualizado_em = NOW()
            """,
            (
                agendor_id, lead_id, row.get("Título do negócio"), funil, etapa,
                row.get("Usuário responsável"), valor, valor, status,
                row.get("Motivo de perda"), row.get("Data de cadastro"), row.get("Data de conclusão"),
            ),
        )

    gerou_proposta = eh_etapa_proposta_enviada(etapa) or bool(valor)
    if lead_id is not None:
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
                (agendor_id, row.get("Usuário responsável"), etapa, gerou_proposta,
                 gerou_proposta, valor, status, row.get("Data de conclusão"), lead_id),
            )

    momento_evento = row.get("Ultima atualização") or row.get("Data de cadastro")
    data_criacao = row.get("Data de cadastro")

    if data_criacao:
        registrar_evento(conn, lead_id, FONTE, "negocio_criado", data_criacao,
                          canal=None, campanha=funil, origem_detalhe=etapa,
                          payload={"agendor_negocio_id": agendor_id, "importado_de": "historico"})

    if momento_evento:
        if valor:
            registrar_evento(conn, lead_id, FONTE, "valor_lancado", momento_evento,
                              payload={"agendor_negocio_id": agendor_id, "valor": valor})
        if eh_etapa_proposta_enviada(etapa) or valor:
            registrar_evento(conn, lead_id, FONTE, "proposta_gerada", momento_evento,
                              payload={"agendor_negocio_id": agendor_id, "etapa": etapa})
        if status == "ganho" or eh_etapa_assinatura_contrato(etapa):
            registrar_evento(conn, lead_id, FONTE, "ganho", momento_evento,
                              payload={"agendor_negocio_id": agendor_id})
        elif status == "perdido":
            registrar_evento(conn, lead_id, FONTE, "perdido", momento_evento,
                              payload={"agendor_negocio_id": agendor_id, "motivo": row.get("Motivo de perda")})
        if eh_etapa_lead_sem_perfil(etapa):
            # nome de evento cunhado nesta implementação (não está no enum literal da
            # seção 4.3) para distinguir desqualificação comercial de ia_desqualificou
            registrar_evento(conn, lead_id, FONTE, "negocio_desqualificado", momento_evento,
                              payload={"agendor_negocio_id": agendor_id, "etapa": etapa})


def _ids_ja_importados(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT agendor_negocio_id FROM negocios")
        return {r["agendor_negocio_id"] for r in cur.fetchall()}


def importar(caminhos: list[str]) -> None:
    total_negocios, pulados = 0, 0
    conexao = ConexaoComReconexao()
    try:
        ja_importados = conexao.executar(_ids_ja_importados)
        logger.info("%d negócios já importados em execuções anteriores (serão pulados)", len(ja_importados))

        for caminho in caminhos:
            logger.info("Lendo %s", caminho)
            wb = openpyxl.load_workbook(caminho, data_only=True)
            ws = wb.active
            linhas = list(ws.iter_rows(values_only=True))
            headers = linhas[0]

            for valores in linhas[1:]:
                row = dict(zip(headers, valores))
                agendor_id = row.get("Código do Negócio")

                # checagem em memória (sem round-trip de rede) pra pular o que já foi
                # importado em execuções anteriores — permite reiniciar sem reprocessar
                # tudo do zero a cada corte do ambiente (~30min de duração de background)
                if agendor_id is not None and int(agendor_id) in ja_importados:
                    pulados += 1
                    continue

                def processar(conn, row=row):
                    lead_id = _resolver_lead_ou_none(conn, row)
                    _upsert_negocio(conn, row, lead_id)
                    conn.commit()

                conexao.executar(processar)
                total_negocios += 1
                if total_negocios % 50 == 0:
                    logger.info("... %d negócios processados", total_negocios)
            wb.close()
    finally:
        conexao.close()

    logger.info("Importação do Agendor concluída: %d negócios processados, %d já importados antes (pulados)", total_negocios, pulados)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python importers/agendor_historico.py arquivo1.xlsx [arquivo2.xlsx ...]", file=sys.stderr)
        sys.exit(1)
    importar(sys.argv[1:])
