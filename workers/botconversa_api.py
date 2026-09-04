"""Cliente HTTP para a API do BotConversa.

Schema confirmado com chamadas reais em 22/07/2026 contra as duas contas
(DSC e Duplique): host backend.botconversa.com.br, basePath /api/v1/webhook,
autenticação via header API-KEY. `variables` vem como objeto estruturado
{nome_do_campo: valor}, diferente do que a documentação Swagger pública sugere
(ela descreve como string genérica) — validado direto na resposta real.

Endpoints de escrita (criar subscriber, custom fields, tags, disparar fluxo)
confirmados via swagger real (backend.botconversa.com.br/swagger/?format=openapi)
em 04/09/2026, na implementação do webhook de formulário (seção 5.4 da spec).
"""
import os
from typing import Iterator, Optional

import requests

BASE_URL = "https://backend.botconversa.com.br/api/v1/webhook"


def _headers(api_key: str) -> dict:
    return {"API-KEY": api_key, "Accept": "application/json", "Content-Type": "application/json"}


def _listar_paginado(url: str, api_key: str, timeout: int = 30) -> Iterator[dict]:
    """GET genérico para listas do BotConversa. O swagger declara algumas
    (custom_fields, tags, flows) como array simples, mas na prática passam a
    paginar (estilo DRF: {"count","next","results"}) acima de ~100 itens —
    confirmado em 03/09/2026 na conta do DSC Cobrança. Segue 'next' até o fim
    e também aceita o caso array simples, pra não repetir esse bug aqui."""
    params = {"page": 1}
    while url:
        resp = requests.get(url, headers=_headers(api_key), params=params, timeout=timeout)
        resp.raise_for_status()
        corpo = resp.json()
        if isinstance(corpo, dict):
            for item in corpo.get("results", []):
                yield item
            url = corpo.get("next")
        else:
            for item in corpo:
                yield item
            url = None
        params = None


def listar_subscribers(api_key: str) -> Iterator[dict]:
    """Pagina GET /subscribers/."""
    yield from _listar_paginado(f"{BASE_URL}/subscribers/", api_key)


def buscar_subscriber_por_telefone(api_key: str, telefone_e164: str) -> Optional[dict]:
    telefone_sem_mais = telefone_e164.lstrip("+")
    resp = requests.get(f"{BASE_URL}/subscriber/get_by_phone/{telefone_sem_mais}/", headers=_headers(api_key), timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def criar_subscriber(api_key: str, telefone_e164: str, first_name: str, last_name: str = "",
                      has_opt_in_whatsapp: bool = True) -> dict:
    """POST /subscriber/. Cria um inscrito novo; retorna o objeto criado (com 'id')."""
    payload = {
        "phone": telefone_e164,
        "first_name": first_name,
        "last_name": last_name,
        "has_opt_in_whatsapp": has_opt_in_whatsapp,
    }
    resp = requests.post(f"{BASE_URL}/subscriber/", headers=_headers(api_key), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def listar_custom_fields(api_key: str) -> Iterator[dict]:
    """Pagina GET /custom_fields/. Cada item tem 'id' e 'key'."""
    yield from _listar_paginado(f"{BASE_URL}/custom_fields/", api_key)


def definir_campo_personalizado(api_key: str, subscriber_id: int, custom_field_id: int, valor: str) -> None:
    """POST /subscriber/{id}/custom_fields/{field_id}/ — grava o valor de um campo."""
    resp = requests.post(
        f"{BASE_URL}/subscriber/{subscriber_id}/custom_fields/{custom_field_id}/",
        headers=_headers(api_key), json={"value": valor}, timeout=30,
    )
    resp.raise_for_status()


def listar_flows(api_key: str) -> Iterator[dict]:
    """Pagina GET /flows/. Cada item tem 'id' e 'name'."""
    yield from _listar_paginado(f"{BASE_URL}/flows/", api_key)


def disparar_flow(api_key: str, subscriber_id: int, flow_id: int) -> None:
    """POST /subscriber/{id}/send_flow/ — dispara um fluxo de conversa pro inscrito."""
    resp = requests.post(
        f"{BASE_URL}/subscriber/{subscriber_id}/send_flow/",
        headers=_headers(api_key), json={"flow": flow_id}, timeout=30,
    )
    resp.raise_for_status()
