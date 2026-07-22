"""Cliente HTTP para a API v3 do Agendor.

⚠️ ATENÇÃO — PRECISA DE VALIDAÇÃO CONTRA A API REAL ANTES DE RODAR EM PRODUÇÃO:
Não consegui confirmar, via documentação pública (a doc v3 oficial e a coleção
Postman são SPAs que não expõem o JSON pra scraping; o único schema completo
encontrado publicamente é da API v1, que é diferente), os nomes exatos dos campos
de resposta de GET /v3/deals (ex.: se a etapa vem como `stage.name` ou `dealStage`,
se o funil vem como `funnel.name` ou outro formato, como pessoas/organizações
vinculadas aparecem no payload). O que está confirmado: base URL
https://api.agendor.com.br/v3, autenticação via header Authorization: Token <token>.

A função `_mapear_deal_bruto` abaixo é o único lugar que decodifica o JSON bruto —
foi escrita com um shape plausível (baseado no padrão da v1 e nas descrições da
seção 5.5 da spec), mas DEVE ser conferida contra uma resposta real (ex.: uma
chamada de teste com AGENDOR_TOKEN) antes do primeiro sync em produção. Ajustar
apenas esta função caso os nomes de campo reais sejam diferentes — o resto do
worker (sync_agendor.py) trabalha só com o dict já normalizado.
"""
import os
from datetime import datetime
from typing import Iterator, Optional

import requests

BASE_URL = "https://api.agendor.com.br/v3"


def _headers() -> dict:
    token = os.environ["AGENDOR_TOKEN"]
    return {"Authorization": f"Token {token}", "Accept": "application/json"}


def _parse_data(valor) -> Optional[datetime]:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None


def _mapear_deal_bruto(bruto: dict) -> dict:
    """Único ponto de decodificação do JSON de um deal — ver aviso no topo do arquivo."""
    stage = bruto.get("stage") or bruto.get("dealStage") or {}
    funnel = bruto.get("funnel") or bruto.get("dealFunnel") or {}
    status = bruto.get("dealStatus") or bruto.get("status") or {}
    owner = bruto.get("user") or bruto.get("userOwner") or {}
    pessoa_bruta = bruto.get("person") or {}
    organizacao_bruta = bruto.get("organization") or {}

    status_nome = status.get("name") if isinstance(status, dict) else str(status)

    pessoa = None
    if pessoa_bruta:
        pessoa = {
            "nome": pessoa_bruta.get("name"),
            "telefone": pessoa_bruta.get("mobile") or pessoa_bruta.get("phone") or pessoa_bruta.get("whatsapp"),
            "email": pessoa_bruta.get("email"),
        }

    return {
        "agendor_negocio_id": bruto.get("id") or bruto.get("dealId"),
        "titulo": bruto.get("title"),
        "funil": funnel.get("name") if isinstance(funnel, dict) else funnel,
        "etapa": stage.get("name") if isinstance(stage, dict) else stage,
        "consultor": owner.get("name") if isinstance(owner, dict) else owner,
        "valor": bruto.get("value"),
        "status_nome": status_nome,
        "motivo_perda": bruto.get("lossReason") or bruto.get("motiveLoss"),
        "data_criacao": _parse_data(bruto.get("createTime") or bruto.get("createdAt")),
        "data_fechamento": _parse_data(bruto.get("endTime") or bruto.get("dealDoneDate")),
        "atualizado_em_agendor": _parse_data(bruto.get("updateTime") or bruto.get("updatedAt")),
        "pessoa": pessoa,
        "organizacao_nome": organizacao_bruta.get("name") if isinstance(organizacao_bruta, dict) else None,
        "payload_bruto": bruto,
    }


def listar_deals(atualizado_apos: Optional[datetime] = None) -> Iterator[dict]:
    """Pagina GET /deals e devolve cada deal já normalizado por _mapear_deal_bruto."""
    pagina = 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/deals",
            headers=_headers(),
            params={"page": pagina, "per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        corpo = resp.json()
        itens = corpo.get("data", corpo if isinstance(corpo, list) else [])
        if not itens:
            break

        for bruto in itens:
            yield _mapear_deal_bruto(bruto)

        paginacao = corpo.get("pagination") if isinstance(corpo, dict) else None
        if not paginacao or pagina >= paginacao.get("totalPages", pagina):
            break
        pagina += 1
