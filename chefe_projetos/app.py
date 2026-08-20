import os
from datetime import date

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from auth import hash_pin, verify_pin
from db import get_conn

app = FastAPI(title="Chefe de Projetos")
app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET"])
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

STATUS_ORDEM = ["pendente", "em_andamento", "concluida"]
STATUS_LABEL = {
    "pendente": "Pendente",
    "em_andamento": "Em andamento",
    "concluida": "Concluída",
}


def pessoa_logada(request: Request):
    return request.session.get("pessoa")


def garantir_tarefas_do_dia(cur, hoje: date):
    cur.execute("select * from tarefas_recorrentes where ativa = true")
    for modelo in cur.fetchall():
        cur.execute(
            """insert into tarefas
                   (titulo, descricao, pessoa_id, projeto_id, origem_recorrente_id, data_referencia)
               values (%s, %s, %s, %s, %s, %s)
               on conflict (origem_recorrente_id, data_referencia) do nothing""",
            (
                modelo["titulo"],
                modelo["descricao"],
                modelo["pessoa_id"],
                modelo["projeto_id"],
                modelo["id"],
                hoje,
            ),
        )


@app.get("/")
def raiz(request: Request):
    if pessoa_logada(request):
        return RedirectResponse("/board")
    return RedirectResponse("/login")


@app.get("/login")
def login_form(request: Request):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select id, nome, cargo, pin_hash is not null as tem_pin from pessoas order by nome")
        pessoas = cur.fetchall()
    return templates.TemplateResponse(
        "login.html", {"request": request, "pessoas": pessoas, "erro": None}
    )


@app.post("/login")
def login_submit(request: Request, pessoa_id: str = Form(...), pin: str = Form(...)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select * from pessoas where id = %s", (pessoa_id,))
        pessoa = cur.fetchone()
        if not pessoa:
            return RedirectResponse("/login", status_code=303)

        if pessoa["pin_hash"] is None:
            if len(pin) < 4:
                cur.execute("select id, nome, cargo, pin_hash is not null as tem_pin from pessoas order by nome")
                pessoas = cur.fetchall()
                return templates.TemplateResponse(
                    "login.html",
                    {"request": request, "pessoas": pessoas, "erro": "PIN precisa ter pelo menos 4 dígitos."},
                )
            cur.execute(
                "update pessoas set pin_hash = %s where id = %s",
                (hash_pin(pin), pessoa_id),
            )
            conn.commit()
        elif not verify_pin(pin, pessoa["pin_hash"]):
            cur.execute("select id, nome, cargo, pin_hash is not null as tem_pin from pessoas order by nome")
            pessoas = cur.fetchall()
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "pessoas": pessoas, "erro": "PIN incorreto."},
            )

    request.session["pessoa"] = {
        "id": str(pessoa["id"]),
        "nome": pessoa["nome"],
        "eh_chefe": pessoa["eh_chefe"],
    }
    return RedirectResponse("/board", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")


@app.get("/board")
def board(request: Request):
    pessoa = pessoa_logada(request)
    if not pessoa:
        return RedirectResponse("/login")

    hoje = date.today()
    with get_conn() as conn, conn.cursor() as cur:
        garantir_tarefas_do_dia(cur, hoje)
        conn.commit()

        cur.execute(
            """select t.*, p.nome as projeto_nome
               from tarefas t
               left join projetos p on p.id = t.projeto_id
               where t.pessoa_id = %s and t.data_referencia = %s
               order by (t.status = 'concluida'), t.criado_em""",
            (pessoa["id"], hoje),
        )
        tarefas = cur.fetchall()

        cur.execute("select id, nome from projetos where ativo = true order by nome")
        projetos = cur.fetchall()

    return templates.TemplateResponse(
        "board.html",
        {
            "request": request,
            "pessoa": pessoa,
            "tarefas": tarefas,
            "projetos": projetos,
            "status_label": STATUS_LABEL,
            "hoje": hoje,
        },
    )


@app.post("/tarefas")
def criar_tarefa(
    request: Request,
    titulo: str = Form(...),
    descricao: str = Form(""),
    projeto_id: str = Form(""),
):
    pessoa = pessoa_logada(request)
    if not pessoa:
        return RedirectResponse("/login")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into tarefas (titulo, descricao, pessoa_id, projeto_id)
               values (%s, %s, %s, %s)""",
            (titulo, descricao or None, pessoa["id"], projeto_id or None),
        )
        conn.commit()
    return RedirectResponse("/board", status_code=303)


@app.post("/tarefas/{tarefa_id}/status")
def atualizar_status(request: Request, tarefa_id: str, status: str = Form(...)):
    pessoa = pessoa_logada(request)
    if not pessoa or status not in STATUS_ORDEM:
        return RedirectResponse("/login")
    with get_conn() as conn, conn.cursor() as cur:
        concluida_em = "now()" if status == "concluida" else "null"
        cur.execute(
            f"""update tarefas set status = %s, concluida_em = {concluida_em}
                where id = %s and pessoa_id = %s""",
            (status, tarefa_id, pessoa["id"]),
        )
        conn.commit()
    voltar = request.query_params.get("voltar", "/board")
    return RedirectResponse(voltar, status_code=303)


@app.get("/chefe")
def visao_chefe(request: Request):
    pessoa = pessoa_logada(request)
    if not pessoa:
        return RedirectResponse("/login")
    if not pessoa["eh_chefe"]:
        return RedirectResponse("/board")

    hoje = date.today()
    with get_conn() as conn, conn.cursor() as cur:
        garantir_tarefas_do_dia(cur, hoje)
        conn.commit()

        cur.execute(
            """select pe.id as pessoa_id, pe.nome as pessoa_nome, pe.cargo,
                      t.id as tarefa_id, t.titulo, t.status, t.criado_em,
                      pr.nome as projeto_nome
               from pessoas pe
               left join tarefas t on t.pessoa_id = pe.id and t.data_referencia = %s
               left join projetos pr on pr.id = t.projeto_id
               where pe.eh_chefe = false
               order by pe.nome, (t.status = 'concluida'), t.criado_em""",
            (hoje,),
        )
        linhas = cur.fetchall()

        cur.execute(
            """select p.nome, count(*) filter (where t.status != 'concluida') as pendentes,
                      count(*) as total
               from projetos p
               left join tarefas t on t.projeto_id = p.id and t.data_referencia = %s
               where p.ativo = true
               group by p.nome
               order by p.nome""",
            (hoje,),
        )
        resumo_projetos = cur.fetchall()

    equipe = {}
    for linha in linhas:
        chave = linha["pessoa_id"]
        if chave not in equipe:
            equipe[chave] = {"nome": linha["pessoa_nome"], "cargo": linha["cargo"], "tarefas": []}
        if linha["tarefa_id"]:
            equipe[chave]["tarefas"].append(linha)

    return templates.TemplateResponse(
        "chefe.html",
        {
            "request": request,
            "pessoa": pessoa,
            "equipe": list(equipe.values()),
            "resumo_projetos": resumo_projetos,
            "status_label": STATUS_LABEL,
            "hoje": hoje,
        },
    )
