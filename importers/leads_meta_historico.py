"""Importer dos leads históricos do Meta (export nativo do Business Suite/Lead
Center) — spec seção 8.2, item 2. Formato real confirmado 23/07/2026: CSV com
Criado em, Nome, Email, Fonte, Formulário, Canal, Estágio, Proprietário,
Rótulos, Telefone, Número de telefone secundário, Número do WhatsApp.

Meta só libera os últimos 90 dias de histórico por esse export — por isso os
arquivos são recorrentes (não um "carrega uma vez e pronto").

Um arquivo por marca (o nome do arquivo diz DSC ou Duplique) — usado como sinal
de marca só quando não há nenhum outro dado de localização (mesma lógica de
_marca_por_texto já usada pra consultor/campanha), nunca sobrepõe cidade/UF real.

Uso: python importers/leads_meta_historico.py leads_meta_DSC.csv DSC
     python importers/leads_meta_historico.py leads_meta_Duplique.csv Duplique
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

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

FONTE = "importacao"
CANAL = "meta_ads"

# "Fonte" do export: Pago = anúncio de verdade -> meta_ads; Orgânico/Direto não
# vieram de anúncio pago, mas ainda são toque no Meta -> organico (decisão
# pragmática, sem sinal melhor disponível — sinalizar se precisar revisar)
FONTE_PARA_CANAL = {"pago": "meta_ads"}


def _mapear_canal(fonte_raw: str) -> str:
    return FONTE_PARA_CANAL.get((fonte_raw or "").strip().lower(), "organico")


def _parse_data(valor: str) -> datetime:
    if not valor:
        return datetime.now()
    try:
        return datetime.strptime(valor.strip(), "%m/%d/%Y %I:%M%p")
    except ValueError:
        return datetime.now()


def importar(caminho: str, marca_arquivo: str) -> None:
    novos, existentes = 0, 0
    conexao = ConexaoComReconexao()
    try:
        with open(caminho, encoding="utf-8-sig", newline="") as f:
            leitor = csv.DictReader(f)
            for row in leitor:
                nome_raw = row.get("Nome")
                email_raw = row.get("Email")
                telefone_raw = row.get("Telefone") or row.get("Número de telefone secundário") or row.get("Número do WhatsApp")
                fonte_raw = row.get("Fonte")
                formulario = row.get("Formulário")
                estagio = row.get("Estágio")
                data_entrada = _parse_data(row.get("Criado em"))

                nome = normalizar_nome(nome_raw)
                email = normalizar_email(email_raw)
                telefone, invalido = extrair_telefone_valido(telefone_raw) if telefone_raw else (None, True)
                if invalido:
                    telefone = None
                if not (nome or email or telefone):
                    continue

                canal = _mapear_canal(fonte_raw)

                def processar(conn, nome=nome, email=email, telefone=telefone, canal=canal,
                              formulario=formulario, estagio=estagio, fonte_raw=fonte_raw,
                              data_entrada=data_entrada, marca_arquivo=marca_arquivo):
                    variacoes = gerar_variacoes_telefone(telefone) if telefone else []
                    marca_info = derivar_marca(conn, campanha=marca_arquivo)
                    dados = {
                        "nome": nome,
                        "telefone": telefone,
                        "telefone_variacoes": variacoes or None,
                        "email": email,
                        "marca": marca_info["marca"],
                        "uf": marca_info["uf"],
                        "regiao": marca_info["regiao"],
                        "uf_derivada_por_ddd": marca_info["uf_derivada_por_ddd"],
                        "canal_entrada": canal,
                        "campanha_entrada": formulario,
                        "origem_detalhe_entrada": fonte_raw,
                        "data_entrada": data_entrada,
                        "payload": {"estagio_meta": estagio, "fonte_meta": fonte_raw, "arquivo": Path(caminho).name},
                    }
                    lead_id, criado = resolver_ou_criar_lead(conn, dados, fonte=FONTE)
                    if not criado:
                        atualizar_campos_lead(
                            conn, lead_id,
                            {k: dados[k] for k in ("marca", "uf", "regiao", "uf_derivada_por_ddd") if dados.get(k) is not None},
                        )
                    registrar_evento(conn, lead_id, FONTE, "importado", data_entrada,
                                      canal=canal, campanha=formulario, origem_detalhe=fonte_raw,
                                      payload=dados["payload"])
                    conn.commit()
                    return criado

                criado = conexao.executar(processar)
                if criado:
                    novos += 1
                else:
                    existentes += 1
    finally:
        conexao.close()

    logger.info("Importação Meta (%s) concluída: %d leads novos, %d já existentes (matched)", marca_arquivo, novos, existentes)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python importers/leads_meta_historico.py arquivo.csv DSC|Duplique", file=sys.stderr)
        sys.exit(1)
    importar(sys.argv[1], sys.argv[2])
