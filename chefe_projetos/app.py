import os
from datetime import date, timedelta

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


STATUS_AGENTE_LABEL = {
    "ativo": "Ativo",
    "com_erro": "Com erro",
    "pausado": "Pausado",
}


def pessoa_logada(request: Request):
    return request.session.get("pessoa")


def exigir_chefe(request: Request):
    """Retorna a pessoa logada se for chefe, senão retorna um redirect."""
    pessoa = pessoa_logada(request)
    if not pessoa:
        return None, RedirectResponse("/login")
    if not pessoa["eh_chefe"]:
        return None, RedirectResponse("/board")
    return pessoa, None


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
    pessoa, redirect = exigir_chefe(request)
    if redirect:
        return redirect

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

        cur.execute(
            """select a.*, pe.nome as responsavel_nome
               from agentes_ia a
               left join pessoas pe on pe.id = a.responsavel_id
               order by (a.status = 'com_erro') desc, a.nome"""
        )
        agentes = cur.fetchall()

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
            "agentes": agentes,
            "status_label": STATUS_LABEL,
            "status_agente_label": STATUS_AGENTE_LABEL,
            "hoje": hoje,
        },
    )


# ---------------------------------------------------------------------------
# Admin (só chefe): cadastro de pessoas, projetos, agentes de IA e tarefas
# ---------------------------------------------------------------------------


@app.get("/admin")
def admin_hub(request: Request):
    pessoa, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("admin.html", {"request": request, "pessoa": pessoa})


@app.get("/admin/pessoas")
def admin_pessoas(request: Request):
    pessoa, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select * from pessoas order by eh_chefe desc, nome")
        pessoas = cur.fetchall()
    return templates.TemplateResponse(
        "admin_pessoas.html", {"request": request, "pessoa": pessoa, "pessoas": pessoas}
    )


@app.post("/admin/pessoas")
def admin_criar_pessoa(
    request: Request,
    nome: str = Form(...),
    cargo: str = Form(...),
    skills: str = Form(""),
):
    _, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into pessoas (nome, cargo, skills) values (%s, %s, %s)",
            (nome, cargo, skills),
        )
        conn.commit()
    return RedirectResponse("/admin/pessoas", status_code=303)


@app.post("/admin/pessoas/{pessoa_id}")
def admin_editar_pessoa(
    request: Request,
    pessoa_id: str,
    nome: str = Form(...),
    cargo: str = Form(...),
    skills: str = Form(""),
    ativo: str = Form(""),
):
    _, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "update pessoas set nome = %s, cargo = %s, skills = %s, ativo = %s where id = %s",
            (nome, cargo, skills, bool(ativo), pessoa_id),
        )
        conn.commit()
    return RedirectResponse("/admin/pessoas", status_code=303)


@app.get("/admin/projetos")
def admin_projetos(request: Request):
    pessoa, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select * from projetos order by ativo desc, nome")
        projetos = cur.fetchall()
    return templates.TemplateResponse(
        "admin_projetos.html", {"request": request, "pessoa": pessoa, "projetos": projetos}
    )


@app.post("/admin/projetos")
def admin_criar_projeto(request: Request, nome: str = Form(...), tipo: str = Form("campanha")):
    _, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("insert into projetos (nome, tipo) values (%s, %s)", (nome, tipo))
        conn.commit()
    return RedirectResponse("/admin/projetos", status_code=303)


@app.post("/admin/projetos/{projeto_id}/toggle")
def admin_toggle_projeto(request: Request, projeto_id: str):
    _, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("update projetos set ativo = not ativo where id = %s", (projeto_id,))
        conn.commit()
    return RedirectResponse("/admin/projetos", status_code=303)


@app.get("/admin/agentes")
def admin_agentes(request: Request):
    pessoa, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """select a.*, pe.nome as responsavel_nome, pr.nome as projeto_nome
               from agentes_ia a
               left join pessoas pe on pe.id = a.responsavel_id
               left join projetos pr on pr.id = a.projeto_id
               order by a.nome"""
        )
        agentes = cur.fetchall()
        cur.execute("select id, nome from pessoas where ativo = true order by nome")
        pessoas = cur.fetchall()
        cur.execute("select id, nome from projetos where ativo = true order by nome")
        projetos = cur.fetchall()
    return templates.TemplateResponse(
        "admin_agentes.html",
        {
            "request": request,
            "pessoa": pessoa,
            "agentes": agentes,
            "pessoas": pessoas,
            "projetos": projetos,
            "status_agente_label": STATUS_AGENTE_LABEL,
        },
    )


@app.post("/admin/agentes")
def admin_criar_agente(
    request: Request,
    nome: str = Form(...),
    cliente: str = Form(""),
    projeto_id: str = Form(""),
    responsavel_id: str = Form(""),
):
    _, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into agentes_ia (nome, cliente, projeto_id, responsavel_id)
               values (%s, %s, %s, %s)""",
            (nome, cliente or None, projeto_id or None, responsavel_id or None),
        )
        conn.commit()
    return RedirectResponse("/admin/agentes", status_code=303)


@app.post("/admin/agentes/{agente_id}")
def admin_editar_agente(
    request: Request,
    agente_id: str,
    status: str = Form(...),
    responsavel_id: str = Form(""),
    observacoes: str = Form(""),
):
    _, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    if status not in STATUS_AGENTE_LABEL:
        return RedirectResponse("/admin/agentes", status_code=303)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """update agentes_ia
               set status = %s, responsavel_id = %s, observacoes = %s, atualizado_em = now()
               where id = %s""",
            (status, responsavel_id or None, observacoes or None, agente_id),
        )
        conn.commit()
    return RedirectResponse("/admin/agentes", status_code=303)


@app.get("/admin/tarefas")
def admin_tarefas(request: Request):
    pessoa, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    hoje = date.today()
    with get_conn() as conn, conn.cursor() as cur:
        garantir_tarefas_do_dia(cur, hoje)
        conn.commit()

        cur.execute(
            """select t.*, pe.nome as pessoa_nome, pr.nome as projeto_nome
               from tarefas t
               join pessoas pe on pe.id = t.pessoa_id
               left join projetos pr on pr.id = t.projeto_id
               where t.data_referencia = %s
               order by (t.status = 'concluida'), pe.nome""",
            (hoje,),
        )
        tarefas = cur.fetchall()

        cur.execute("select id, nome, skills from pessoas where ativo = true order by nome")
        pessoas = cur.fetchall()
        cur.execute("select id, nome from projetos where ativo = true order by nome")
        projetos = cur.fetchall()

    return templates.TemplateResponse(
        "admin_tarefas.html",
        {
            "request": request,
            "pessoa": pessoa,
            "tarefas": tarefas,
            "pessoas": pessoas,
            "projetos": projetos,
            "status_label": STATUS_LABEL,
            "hoje": hoje,
        },
    )


@app.post("/admin/tarefas")
def admin_criar_tarefa(
    request: Request,
    titulo: str = Form(...),
    descricao: str = Form(""),
    pessoa_id: str = Form(...),
    projeto_id: str = Form(""),
):
    _, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into tarefas (titulo, descricao, pessoa_id, projeto_id)
               values (%s, %s, %s, %s)""",
            (titulo, descricao or None, pessoa_id, projeto_id or None),
        )
        conn.commit()
    return RedirectResponse("/admin/tarefas", status_code=303)


@app.post("/admin/tarefas/{tarefa_id}/reatribuir")
def admin_reatribuir_tarefa(request: Request, tarefa_id: str, pessoa_id: str = Form(...)):
    _, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("update tarefas set pessoa_id = %s where id = %s", (pessoa_id, tarefa_id))
        conn.commit()
    return RedirectResponse("/admin/tarefas", status_code=303)


@app.post("/admin/tarefas/{tarefa_id}/status")
def admin_status_tarefa(request: Request, tarefa_id: str, status: str = Form(...)):
    _, redirect = exigir_chefe(request)
    if redirect:
        return redirect
    if status not in STATUS_ORDEM:
        return RedirectResponse("/admin/tarefas", status_code=303)
    with get_conn() as conn, conn.cursor() as cur:
        concluida_em = "now()" if status == "concluida" else "null"
        cur.execute(
            f"update tarefas set status = %s, concluida_em = {concluida_em} where id = %s",
            (status, tarefa_id),
        )
        conn.commit()
    return RedirectResponse("/admin/tarefas", status_code=303)


@app.get("/dashboard")
def dashboard(request: Request):
    pessoa, redirect = exigir_chefe(request)
    if redirect:
        return redirect

    dias = int(request.query_params.get("dias", 30))
    desde = date.today() - timedelta(days=dias)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """select pe.nome as pessoa_nome,
                      count(*) filter (where t.status = 'concluida') as concluidas,
                      count(*) filter (where t.status = 'pendente') as pendentes,
                      count(*) filter (where t.status = 'em_andamento') as em_andamento,
                      count(*) as total
               from pessoas pe
               left join tarefas t on t.pessoa_id = pe.id and t.data_referencia >= %s
               where pe.eh_chefe = false
               group by pe.nome
               order by pe.nome""",
            (desde,),
        )
        resumo_pessoas = cur.fetchall()

        cur.execute(
            """select t.titulo, t.data_referencia, t.concluida_em, pe.nome as pessoa_nome,
                      pr.nome as projeto_nome
               from tarefas t
               join pessoas pe on pe.id = t.pessoa_id
               left join projetos pr on pr.id = t.projeto_id
               where t.status = 'concluida' and t.data_referencia >= %s
               order by t.concluida_em desc
               limit 100""",
            (desde,),
        )
        concluidas_recentes = cur.fetchall()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "pessoa": pessoa,
            "resumo_pessoas": resumo_pessoas,
            "concluidas_recentes": concluidas_recentes,
            "dias": dias,
        },
    )
