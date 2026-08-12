"""Cliente HTTP para a API v3 do Agendor.

Schema confirmado com chamada real em 22/07/2026 (GET /v3/deals e GET
/v3/people/{id} contra a conta de produção). Ver estrutura real abaixo — nada
aqui é mais suposição.
"""
import os
from datetime import datetime
from typing import Iterator, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://api.agendor.com.br/v3"
TIMEOUT = 60  # segundos — a API do Agendor às vezes demora em páginas grandes

# a API do Agendor volta a responder normal após um timeout pontual (visto em
# produção 12/08/2026: crash do worker inteiro por 1 ReadTimeout em meio a ~10k
# deals) — retry com backoff em vez de derrubar o processo
_retry = Retry(
    total=4,
    connect=4,
    read=4,
    backoff_factor=2,
    status_forcelist=(500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
)
_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def _headers() -> dict:
    token = os.environ["AGENDOR_TOKEN"]
    return {"Authorization": f"Token {token}", "Accept": "application/json"}


def _parse_data(valor) -> Optional[datetime]:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None


def buscar_pessoa(pessoa_id: int) -> Optional[dict]:
    """GET /v3/people/{id} — usado para telefone (contact.mobile) e cidade/UF
    (address.city/state), que não vêm no objeto `person` resumido de /deals."""
    resp = _session.get(f"{BASE_URL}/people/{pessoa_id}", headers=_headers(), timeout=TIMEOUT)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    d = resp.json().get("data", {})
    contato = d.get("contact") or {}
    endereco = d.get("address") or {}
    return {
        "nome": d.get("name"),
        "email": d.get("email") or contato.get("email"),
        "telefone": contato.get("mobile") or contato.get("whatsapp") or contato.get("work"),
        "cidade": endereco.get("city"),
        "uf": endereco.get("state"),
        "profissao_funcao": d.get("role"),
        "organizacao_nome": (d.get("organization") or {}).get("name"),
    }


def buscar_organizacao(organizacao_id: int) -> Optional[dict]:
    """GET /v3/organizations/{id} — usado quando o negócio não tem pessoa vinculada,
    só organização (achado real 22/07/2026: "laurita sasse" cadastrada como
    organização, não como pessoa — contact/leadOrigin ficam só aqui)."""
    resp = _session.get(f"{BASE_URL}/organizations/{organizacao_id}", headers=_headers(), timeout=TIMEOUT)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    d = resp.json().get("data", {})
    contato = d.get("contact") or {}
    endereco = d.get("address") or {}
    lead_origin = d.get("leadOrigin") or {}
    return {
        "nome": d.get("name"),
        "email": d.get("email") or contato.get("email"),
        "telefone": contato.get("mobile") or contato.get("whatsapp") or contato.get("work"),
        "cidade": endereco.get("city"),
        "uf": endereco.get("state"),
        "origem_detalhe": lead_origin.get("name"),
    }


def _mapear_deal_bruto(bruto: dict) -> dict:
    dealStage = bruto.get("dealStage") or {}
    funnel = dealStage.get("funnel") or {}
    dealStatus = bruto.get("dealStatus") or {}
    owner = bruto.get("owner") or {}
    pessoa_resumo = bruto.get("person") or {}
    organizacao = bruto.get("organization") or {}
    loss_reason = bruto.get("lossReason")
    if isinstance(loss_reason, dict):
        loss_reason = loss_reason.get("name")

    data_fechamento = _parse_data(bruto.get("wonAt")) or _parse_data(bruto.get("lostAt")) or _parse_data(bruto.get("endTime"))

    return {
        "agendor_negocio_id": bruto.get("id"),
        "titulo": bruto.get("title"),
        "funil": funnel.get("name"),
        "etapa": dealStage.get("name"),
        "consultor": owner.get("name"),
        "valor": bruto.get("value"),
        "status_nome": dealStatus.get("name"),
        "motivo_perda": loss_reason,
        "data_criacao": _parse_data(bruto.get("createdAt")),
        "data_fechamento": data_fechamento,
        "atualizado_em_agendor": _parse_data(bruto.get("updatedAt")),
        "pessoa_id": pessoa_resumo.get("id"),
        "pessoa_nome_resumo": pessoa_resumo.get("name"),
        "pessoa_email_resumo": pessoa_resumo.get("email"),
        "organizacao_id": organizacao.get("id"),
        "organizacao_nome": organizacao.get("name"),
        "payload_bruto": bruto,
    }


def listar_deals() -> Iterator[dict]:
    """Pagina GET /deals via `links.next` e devolve cada deal já normalizado."""
    url = f"{BASE_URL}/deals"
    params = {"page": 1, "per_page": 100}

    while url:
        resp = _session.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        corpo = resp.json()

        for bruto in corpo.get("data", []):
            yield _mapear_deal_bruto(bruto)

        url = (corpo.get("links") or {}).get("next")
        params = None  # a URL de "next" já vem com os query params corretos
