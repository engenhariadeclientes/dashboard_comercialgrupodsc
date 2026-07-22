"""Importer do CSV padrão genérico da carga inicial (spec seção 8.1, formato alternativo).

Colunas (separador ';'):
nome;telefone;email;cidade;uf;profissao_funcao;canal;campanha;origem_detalhe;tipo_captura;data_entrada

Uso: python importers/csv_padrao.py caminho/do/arquivo.csv
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

from common_import import importar_lead, logger, montar_dados_lead

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workers.common.db import get_connection  # noqa: E402

COLUNAS_ESPERADAS = [
    "nome", "telefone", "email", "cidade", "uf", "profissao_funcao",
    "canal", "campanha", "origem_detalhe", "tipo_captura", "data_entrada",
]


def parse_data(valor: str | None) -> datetime:
    if not valor:
        return datetime.now()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(valor.strip(), fmt)
        except ValueError:
            continue
    logger.warning("data_entrada não reconhecida (%s), usando agora()", valor)
    return datetime.now()


def importar(caminho: str) -> None:
    novos, existentes = 0, 0
    with get_connection() as conn:
        with open(caminho, encoding="utf-8-sig", newline="") as f:
            leitor = csv.DictReader(f, delimiter=";")
            faltantes = set(COLUNAS_ESPERADAS) - set(leitor.fieldnames or [])
            if faltantes:
                raise ValueError(f"Colunas ausentes no CSV: {faltantes}")

            for linha in leitor:
                dados = montar_dados_lead(
                    conn,
                    nome_raw=linha.get("nome"),
                    telefone_raw=linha.get("telefone"),
                    email_raw=linha.get("email"),
                    cidade=linha.get("cidade") or None,
                    uf_informada=linha.get("uf") or None,
                    profissao_funcao=linha.get("profissao_funcao") or None,
                    canal=linha.get("canal") or "outro",
                    campanha=linha.get("campanha") or None,
                    origem_detalhe=linha.get("origem_detalhe") or None,
                    tipo_captura=linha.get("tipo_captura") or None,
                    data_entrada=parse_data(linha.get("data_entrada")),
                )
                _, criado = importar_lead(conn, dados, fonte="importacao")
                if criado:
                    novos += 1
                else:
                    existentes += 1
        conn.commit()

    logger.info("Importação concluída: %d leads novos, %d já existentes (matched)", novos, existentes)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python importers/csv_padrao.py caminho/do/arquivo.csv", file=sys.stderr)
        sys.exit(1)
    importar(sys.argv[1])
