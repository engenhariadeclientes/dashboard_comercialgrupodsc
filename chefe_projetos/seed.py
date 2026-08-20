"""Cria as tabelas (schema.sql) e popula pessoas, projetos e tarefas recorrentes
iniciais. Idempotente: pode rodar de novo sem duplicar nada (usa nome como chave
de checagem). Requer DATABASE_URL no ambiente.
"""
from pathlib import Path

from db import get_conn

PESSOAS = [
    ("Stella", "Diretora Estratégica / Gestora de Projetos", True, "estratégia, comercial, tráfego, social media, closer, gestão de carteira"),
    ("Daniela", "Coordenadora de CS", False, "cs, atendimento, ia, agentes, monitoramento, qualidade"),
    ("Leonardo", "Estagiário Tech Marketing", False, "automação, tech, ti, suporte, ia"),
    ("Gustavo", "Vídeo Maker / Editor", False, "vídeo, edição, social media, stories"),
]

PROJETOS = [
    ("Assistente de Cobrança em IA", "campanha"),
    ("Consultoria de IA para Empresários", "campanha"),
    ("Método EP — Clínicas Médicas", "campanha"),
    ("Imersão Geração IA — Prospecção de Escolas", "campanha"),
    ("Operação de CS — Agentes de IA", "operacao"),
    ("Automações e Suporte Técnico", "operacao"),
    ("Gestão de Carteira", "carteira"),
]

# (titulo, descricao, pessoa, projeto)
TAREFAS_RECORRENTES = [
    (
        "Monitorar agentes de IA ativos",
        "Checar se todos os agentes de IA em produção estão no ar, sem erros.",
        "Daniela",
        "Operação de CS — Agentes de IA",
    ),
    (
        "Monitorar conversas dos agentes de IA",
        "Revisar amostra de conversas para garantir qualidade das entregas contratadas.",
        "Daniela",
        "Operação de CS — Agentes de IA",
    ),
    (
        "Monitorar automações existentes",
        "Checar se as automações em produção estão rodando sem erro.",
        "Leonardo",
        "Automações e Suporte Técnico",
    ),
    (
        "Suporte técnico ao time",
        "Atender chamados de TI/automações de baixa complexidade.",
        "Leonardo",
        "Automações e Suporte Técnico",
    ),
    (
        "Stories da empresa",
        "Cumprir a meta de stories em tempo real da empresa.",
        "Gustavo",
        None,
    ),
]


def run():
    schema_sql = Path(__file__).with_name("schema.sql").read_text()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(schema_sql)

        pessoa_ids = {}
        for nome, cargo, eh_chefe, skills in PESSOAS:
            cur.execute("select id from pessoas where nome = %s", (nome,))
            row = cur.fetchone()
            if row:
                pessoa_ids[nome] = row["id"]
                # preenche skills só se ainda não foi editado manualmente
                cur.execute(
                    "update pessoas set skills = %s where id = %s and skills = ''",
                    (skills, row["id"]),
                )
                continue
            cur.execute(
                "insert into pessoas (nome, cargo, eh_chefe, skills) values (%s, %s, %s, %s) returning id",
                (nome, cargo, eh_chefe, skills),
            )
            pessoa_ids[nome] = cur.fetchone()["id"]

        projeto_ids = {}
        for nome, tipo in PROJETOS:
            cur.execute("select id from projetos where nome = %s", (nome,))
            row = cur.fetchone()
            if row:
                projeto_ids[nome] = row["id"]
                continue
            cur.execute(
                "insert into projetos (nome, tipo) values (%s, %s) returning id",
                (nome, tipo),
            )
            projeto_ids[nome] = cur.fetchone()["id"]

        for titulo, descricao, pessoa_nome, projeto_nome in TAREFAS_RECORRENTES:
            cur.execute(
                "select id from tarefas_recorrentes where titulo = %s and pessoa_id = %s",
                (titulo, pessoa_ids[pessoa_nome]),
            )
            if cur.fetchone():
                continue
            cur.execute(
                """insert into tarefas_recorrentes
                   (titulo, descricao, pessoa_id, projeto_id, frequencia)
                   values (%s, %s, %s, %s, 'diaria')""",
                (
                    titulo,
                    descricao,
                    pessoa_ids[pessoa_nome],
                    projeto_ids[projeto_nome] if projeto_nome else None,
                ),
            )
        conn.commit()
    print("Seed concluído.")


if __name__ == "__main__":
    run()
