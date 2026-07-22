"""Cliente HTTP para a API do BotConversa.

Schema confirmado com chamadas reais em 22/07/2026 contra as duas contas
(DSC e Duplique): host backend.botconversa.com.br, basePath /api/v1/webhook,
autenticação via header API-KEY. `variables` vem como objeto estruturado
{nome_do_campo: valor}, diferente do que a documentação Swagger pública sugere
(ela descreve como string genérica) — validado direto na resposta real.
"""
import os
from typing import Iterator, Optional

import requests

BASE_URL = "https://backend.botconversa.com.br/api/v1/webhook"


def _headers(api_key: str) -> dict:
    return {"API-KEY": api_key, "Accept": "application/json"}


def listar_subscribers(api_key: str) -> Iterator[dict]:
    """Pagina GET /subscribers/."""
    url = f"{BASE_URL}/subscribers/"
    params = {"page": 1}
    while url:
        resp = requests.get(url, headers=_headers(api_key), params=params, timeout=30)
        resp.raise_for_status()
        corpo = resp.json()
        for item in corpo.get("results", []):
            yield item
        url = corpo.get("next")
        params = None


def buscar_subscriber_por_telefone(api_key: str, telefone_e164: str) -> Optional[dict]:
    telefone_sem_mais = telefone_e164.lstrip("+")
    resp = requests.get(f"{BASE_URL}/subscriber/get_by_phone/{telefone_sem_mais}/", headers=_headers(api_key), timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()
