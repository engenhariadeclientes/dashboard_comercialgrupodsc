"""Importer dos leads de Meta Ads já capturados no RD Station (export de contatos).

Contexto (decisão da Stella, 22/07/2026): o histórico de leads de Meta Ads não vem
de um export "tratado" separado — está dentro do export de contatos do RD Station
(9.365 contatos no total), mas só uma fração tem sinal real de anúncio. Este
importer filtra exatamente essa fração: linhas cujas colunas Tags ou
"Eventos (Últimos 100)" contenham "meta" ou "[a]núncio(s)" (224 linhas confirmadas
em 22/07/2026: lotes "Base de Leads Anúncios Duplique/DSC", "lead-meta-duplique",
tag "anúncio meta"). O restante da base (~9.140 contatos) fica fora da Fase 1.

Nota técnica: o CSV real tem encoding misto (algumas células UTF-8, outras
cp1252/latin-1, dentro do mesmo arquivo — export provavelmente colado de fontes
diferentes ao longo do tempo). Por isso: (1) acesso por posição de coluna, não por
nome de cabeçalho (o cabeçalho acentuado também sofre o mesmo problema); (2) leitura
com cp1252/errors=replace (nunca quebra) + `ftfy.fix_text` pra recuperar o texto
correto nos campos livres (nome, cidade, tags).

Uso: python importers/rd_leads_meta.py caminho/do/arquivo.csv
"""
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import ftfy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importers.common_import import logger  # noqa: E402
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

FONTE = "importacao"
CANAL = "meta_ads"

IDX_EMAIL, IDX_NOME, IDX_TELEFONE, IDX_CELULAR = 0, 1, 2, 3
IDX_ESTADO, IDX_CIDADE = 8, 9
IDX_TAGS = 13
IDX_DATA_PRIMEIRA_CONVERSAO = 16
IDX_EVENTOS = 20

MIN_COLUNAS = 21


def _f(valor: Optional[str]) -> str:
    return ftfy.fix_text(valor) if valor else ""


def _eh_lead_meta(tags: str, eventos: str) -> bool:
    t, e = tags.lower(), eventos.lower()
    return "meta" in t or "ncio" in t or "meta" in e or "ncio" in e


def _parse_data(valor: str) -> datetime:
    if not valor:
        return datetime.now()
    try:
        # formato observado: "2026-07-18 19:54:28 -0300"
        return datetime.strptime(valor.strip()[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.now()


def importar(caminho: str) -> None:
    novos, existentes, avaliados = 0, 0, 0
    with get_connection() as conn:
        with open(caminho, encoding="cp1252", errors="replace", newline="") as f:
            leitor = csv.reader(f)
            next(leitor)  # cabeçalho — não usamos por nome (mesmo problema de encoding)

            for row in leitor:
                if len(row) < MIN_COLUNAS:
                    continue

                tags_raw = row[IDX_TAGS] or ""
                eventos_raw = row[IDX_EVENTOS] or ""
                if not _eh_lead_meta(tags_raw, eventos_raw):
                    continue
                avaliados += 1

                nome_raw = _f(row[IDX_NOME])
                if nome_raw.strip().lower() == "lead":
                    nome_raw = ""
                email_raw = row[IDX_EMAIL]
                telefone_raw = row[IDX_CELULAR] or row[IDX_TELEFONE]
                cidade = _f(row[IDX_CIDADE]) or None
                uf_informada = (row[IDX_ESTADO] or "").strip() or None
                campanha = _f(eventos_raw).strip() or _f(tags_raw).strip() or "meta_ads_rd_historico"
                data_entrada = _parse_data(row[IDX_DATA_PRIMEIRA_CONVERSAO])

                nome = normalizar_nome(nome_raw)
                email = normalizar_email(email_raw)
                telefone, telefone_invalido = extrair_telefone_valido(telefone_raw) if telefone_raw else (None, True)
                if not (nome or email or (telefone and not telefone_invalido)):
                    continue

                telefone_final = telefone if not telefone_invalido else None
                variacoes = gerar_variacoes_telefone(telefone_final) if telefone_final else []
                marca_info = derivar_marca(conn, cidade=cidade, uf_informada=uf_informada, telefone_e164=telefone_final)

                dados = {
                    "nome": nome,
                    "telefone": telefone_final,
                    "telefone_variacoes": variacoes or None,
                    "email": email,
                    "cidade": cidade,
                    "uf": marca_info["uf"],
                    "regiao": marca_info["regiao"],
                    "marca": marca_info["marca"],
                    "uf_derivada_por_ddd": marca_info["uf_derivada_por_ddd"],
                    "canal_entrada": CANAL,
                    "campanha_entrada": campanha,
                    "origem_detalhe_entrada": _f(tags_raw) or None,
                    "tipo_captura": None,
                    "data_entrada": data_entrada,
                    "payload": {"tags_rd": _f(tags_raw), "eventos_rd": _f(eventos_raw)},
                }

                lead_id, criado = resolver_ou_criar_lead(conn, dados, fonte=FONTE)
                if not criado:
                    atualizar_campos_lead(
                        conn, lead_id,
                        {k: dados[k] for k in ("cidade", "uf", "regiao", "marca", "uf_derivada_por_ddd") if dados.get(k) is not None},
                    )
                    existentes += 1
                else:
                    novos += 1

                registrar_evento(conn, lead_id, FONTE, "importado", data_entrada,
                                  canal=CANAL, campanha=campanha, origem_detalhe=dados["origem_detalhe_entrada"],
                                  payload=dados["payload"])

                if avaliados % 50 == 0:
                    conn.commit()
        conn.commit()

    logger.info(
        "Importação RD (leads Meta) concluída: %d avaliados, %d novos, %d já existentes (matched)",
        avaliados, novos, existentes,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python importers/rd_leads_meta.py caminho/do/arquivo.csv", file=sys.stderr)
        sys.exit(1)
    importar(sys.argv[1])
