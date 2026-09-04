"""Webhook HTTP: recebe leads de formularios (Google Forms via Apps Script,
LPs, sites institucionais) e entra com eles no BotConversa em tempo real —
cria/atualiza o inscrito, preenche os campos personalizados que a Julia le
e dispara o fluxo de qualificacao.

Nao grava nada no Postgres do Motor Comercial: o worker `sync_botconversa`
(workers/sync_botconversa.py) ja varre todos os inscritos das contas a cada
hora e cria o lead sozinho na primeira vez que ve um telefone novo (secao
5.2 da spec). Este webhook so cuida da entrada em tempo real no BotConversa.

Servico HTTP separado dos workers (cron) deste mesmo repositorio — roda
continuamente, nao tem cronSchedule. Ver README/railway.json: os workers
compartilham startCommand via WORKER; este servico tem o proprio start
command configurado direto no Railway (gunicorn api.app:app).
"""
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workers.botconversa_api import (  # noqa: E402
    buscar_subscriber_por_telefone,
    criar_subscriber,
    definir_campo_personalizado,
    disparar_flow,
    listar_custom_fields,
    listar_flows,
)
from workers.common.normalizacao import (  # noqa: E402
    extrair_telefone_valido,
    gerar_variacoes_telefone,
    normalizar_email,
    normalizar_nome,
    normalizar_texto_busca,
)

app = Flask(__name__)

CONTAS = {
    "DSC": "BOTCONVERSA_API_KEY_DSC",
    "Duplique": "BOTCONVERSA_API_KEY_DUP",
}

# nome exato do fluxo (Fluxos de conversa no BotConversa) disparado pro lead
# novo, por conta — confirmado com a Stella em 04/09/2026. Duplique ainda nao
# tem fluxo equivalente definido.
FLOW_POR_CONTA = {
    "DSC": "JULIA - IA DSC - RECEPTIVO Site",
}

CANAL_AQUISICAO_FORMULARIO = "Formulário Google"


def _api_key(conta: str) -> str:
    env_var = CONTAS.get(conta)
    if not env_var:
        raise ValueError(f"conta desconhecida: {conta!r} (esperado: {list(CONTAS)})")
    api_key = os.environ.get(env_var)
    if not api_key:
        raise RuntimeError(f"variável {env_var} não configurada no Railway")
    return api_key


def _buscar_ou_criar_subscriber(api_key: str, telefone_e164: str, nome: str) -> dict:
    for variacao in gerar_variacoes_telefone(telefone_e164):
        sub = buscar_subscriber_por_telefone(api_key, variacao)
        if sub:
            return sub

    partes = (nome or "").split(" ", 1)
    first_name = partes[0] if partes and partes[0] else "Lead"
    last_name = partes[1] if len(partes) > 1 else ""
    return criar_subscriber(api_key, telefone_e164, first_name, last_name)


def _mapa_custom_fields(api_key: str) -> dict:
    """Mapa chave-exata -> id, mais um indice normalizado (sem acento/caixa) como
    fallback — a grafia real na conta as vezes diverge da documentada (ja visto
    com 'Canal de Aquisição' vs 'canal-aquisicao', 'primeiro_nome' vs
    'primeiro-nome'), entao um campo so falha de verdade se nem a forma
    normalizada bater com nada."""
    campos = list(listar_custom_fields(api_key))
    exato = {c["key"]: c["id"] for c in campos}
    normalizado = {normalizar_texto_busca(c["key"]): c["id"] for c in campos}
    return exato, normalizado


def _preencher_campos(api_key: str, subscriber_id: int, campos: dict) -> dict:
    """Aplica os campos que existirem no mapa (exato ou normalizado); retorna
    {aplicados: [...], ausentes: [...]}."""
    exato, normalizado = _mapa_custom_fields(api_key)
    aplicados, ausentes = [], []
    for chave, valor in campos.items():
        if valor in (None, ""):
            continue
        campo_id = exato.get(chave) or normalizado.get(normalizar_texto_busca(chave))
        if campo_id is None:
            ausentes.append(chave)
            continue
        definir_campo_personalizado(api_key, subscriber_id, campo_id, str(valor))
        aplicados.append(chave)
    return {"aplicados": aplicados, "ausentes": ausentes}


def _disparar_flow_por_nome(api_key: str, subscriber_id: int, nome_flow: str) -> bool:
    for flow in listar_flows(api_key):
        if flow.get("name") == nome_flow:
            disparar_flow(api_key, subscriber_id, flow["id"])
            return True
    return False


@app.route("/", methods=["GET"])
def raiz():
    return jsonify({"servico": "botconversa-webhooks-comercial", "status": "ok"})


@app.route("/webhook/formulario-lead", methods=["POST"])
def webhook_formulario_lead():
    """
    Recebe o POST do Apps Script vinculado ao Google Form. Corpo esperado:
    {"nome", "email", "telefone", "cidade", "estado", "cargo"}.
    Query param opcional ?conta=DSC|Duplique (default DSC).
    """
    data = request.get_json(force=True, silent=True) or {}
    conta = request.args.get("conta") or data.get("conta") or "DSC"

    try:
        api_key = _api_key(conta)
    except (ValueError, RuntimeError) as e:
        return jsonify({"erro": str(e)}), 400

    nome = normalizar_nome(data.get("nome"))
    email = normalizar_email(data.get("email"))
    telefone_raw = data.get("telefone")
    cidade = (data.get("cidade") or "").strip()
    estado = (data.get("estado") or "").strip()
    cargo = (data.get("cargo") or "").strip()

    telefone, invalido = extrair_telefone_valido(telefone_raw)
    if invalido or not telefone:
        return jsonify({"erro": "telefone inválido ou ausente", "telefone_recebido": telefone_raw}), 400

    try:
        sub = _buscar_ou_criar_subscriber(api_key, telefone, nome or "")
        subscriber_id = sub["id"]

        regiao = " - ".join(p for p in (cidade, estado) if p) or None
        campos = {
            "primeiro_nome": (nome or "").split(" ", 1)[0] or None,
            "Email": email,
            "Canal de Aquisição": CANAL_AQUISICAO_FORMULARIO,
            "cargo-funcao": cargo or None,
            "REGIÃO": regiao,
        }
        resultado_campos = _preencher_campos(api_key, subscriber_id, campos)

        flow_nome = FLOW_POR_CONTA.get(conta)
        flow_disparado = False
        if flow_nome:
            flow_disparado = _disparar_flow_por_nome(api_key, subscriber_id, flow_nome)
    except Exception as e:
        app.logger.exception("falha ao processar lead no BotConversa")
        return jsonify({"erro": f"falha ao falar com o BotConversa: {e}"}), 502

    return jsonify({
        "sucesso": True,
        "conta": conta,
        "subscriber_id": subscriber_id,
        "campos": resultado_campos,
        "flow_nome": flow_nome,
        "flow_disparado": flow_disparado,
    })


@app.route("/debug-flows", methods=["GET"])
def debug_flows():
    """Lista os fluxos e campos personalizados exatamente como estao gravados
    no BotConversa — para conferir grafia antes de configurar FLOW_POR_CONTA."""
    conta = request.args.get("conta") or "DSC"
    try:
        api_key = _api_key(conta)
    except (ValueError, RuntimeError) as e:
        return jsonify({"erro": str(e)}), 400

    return jsonify({
        "conta": conta,
        "flows": [{"id": f["id"], "name": f["name"]} for f in listar_flows(api_key)],
        "custom_fields": [{"id": c["id"], "key": c["key"]} for c in listar_custom_fields(api_key)],
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
