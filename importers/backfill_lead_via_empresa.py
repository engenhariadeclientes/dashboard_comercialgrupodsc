"""Backfill cirúrgico: resolve lead_id (via Pessoa OU Empresa relacionada) só para
os negócios que hoje estão com lead_id NULL, direto dos arquivos xlsx locais —
sem nenhuma chamada à API do Agendor (decisão da Stella, 23/07/2026: priorizar
velocidade, evitar timeouts/lentidão da API).

Uso: python importers/backfill_lead_via_empresa.py arquivo1.xlsx [arquivo2.xlsx ...]
"""
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importers.common_import import logger  # noqa: E402
from importers.agendor_historico import _melhor_telefone  # noqa: E402
from workers.common.db import ConexaoComReconexao  # noqa: E402
from workers.common.eventos import registrar_evento  # noqa: E402
from workers.common.matching import atualizar_campos_lead, resolver_ou_criar_lead  # noqa: E402
from workers.common.normalizacao import (  # noqa: E402
    derivar_marca,
    gerar_variacoes_telefone,
    normalizar_email,
    normalizar_nome,
)
from workers.common.regras_negocio import (  # noqa: E402
    eh_nome_jornada_porter,
    extrair_regiao_jornada_porter,
    mapear_canal_origem_agendor,
)

FONTE = "agendor"


def _resolver_lead_para_negocio_existente(conn, row: dict) -> None:
    agendor_id = row.get("Código do Negócio")
    if agendor_id is None:
        return
    agendor_id = int(agendor_id)

    nome_fonte = row.get("Pessoa relacionada") or row.get("Empresa relacionada")
    nome = normalizar_nome(nome_fonte)
    email = normalizar_email(row.get("E-mail"))
    telefone = _melhor_telefone(row)

    if not (nome or email or telefone):
        return

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
        "data_entrada": row.get("Data de cadastro") or row.get("Data de início"),
        "payload": {"origem_agendor": row.get("Origem do cliente"), "via": "backfill_empresa"},
    }
    lead_id, criado = resolver_ou_criar_lead(conn, dados, fonte=FONTE)
    if not criado:
        atualizar_campos_lead(
            conn, lead_id,
            {k: dados[k] for k in ("cidade", "uf", "regiao", "marca", "uf_derivada_por_ddd") if dados.get(k) is not None},
        )

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE negocios SET lead_id = %s, atualizado_em = NOW() WHERE agendor_negocio_id = %s AND lead_id IS NULL",
            (lead_id, agendor_id),
        )
    if row.get("Data de cadastro"):
        registrar_evento(conn, lead_id, FONTE, "negocio_criado", row.get("Data de cadastro"),
                          canal=None, campanha=row.get("Funil"), origem_detalhe=row.get("Etapa"),
                          payload={"agendor_negocio_id": agendor_id, "importado_de": "backfill_empresa"})


def rodar(caminhos: list[str]) -> None:
    conexao = ConexaoComReconexao()
    total_avaliados, total_resolvidos = 0, 0
    try:
        def buscar_pendentes(conn):
            with conn.cursor() as cur:
                cur.execute("SELECT agendor_negocio_id FROM negocios WHERE lead_id IS NULL")
                return {r["agendor_negocio_id"] for r in cur.fetchall()}

        pendentes = conexao.executar(buscar_pendentes)
        logger.info("negocios pendentes de lead (antes do backfill): %d", len(pendentes))

        for caminho in caminhos:
            logger.info("Lendo %s", caminho)
            wb = openpyxl.load_workbook(caminho, data_only=True)
            ws = wb.active
            linhas = list(ws.iter_rows(values_only=True))
            headers = linhas[0]

            for valores in linhas[1:]:
                row = dict(zip(headers, valores))
                agendor_id = row.get("Código do Negócio")
                if agendor_id is None or int(agendor_id) not in pendentes:
                    continue
                total_avaliados += 1

                def processar(conn, row=row):
                    _resolver_lead_para_negocio_existente(conn, row)

                conexao.executar(processar)
                total_resolvidos += 1
                if total_resolvidos % 50 == 0:
                    logger.info("... %d avaliados", total_resolvidos)
            wb.close()
    finally:
        conexao.close()

    logger.info("Backfill concluído: %d negócios pendentes avaliados", total_avaliados)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python importers/backfill_lead_via_empresa.py arquivo1.xlsx [arquivo2.xlsx ...]", file=sys.stderr)
        sys.exit(1)
    rodar(sys.argv[1:])
