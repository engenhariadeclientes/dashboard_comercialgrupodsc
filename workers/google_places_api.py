"""Cliente HTTP para a Google Places API (New) — busca de empresas por texto.

Usa o endpoint Text Search (places:searchText), autenticado via API key no
header X-Goog-Api-Key. Paginação por `nextPageToken` (a API exige um intervalo
antes do token ficar válido — ver `time.sleep` em `buscar_empresas`).
"""
import time
from typing import Iterator

import requests

BASE_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = "places.displayName,places.nationalPhoneNumber,places.internationalPhoneNumber,places.formattedAddress"


def _headers(api_key: str) -> dict:
    return {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }


def buscar_empresas(api_key: str, query: str, max_resultados: int = 60) -> Iterator[dict]:
    """Busca empresas por texto livre (ex.: "administradora de condomínios em Blumenau, SC").

    Retorna cada resultado bruto da API (dict com displayName, nationalPhoneNumber,
    formattedAddress). Não faz normalização — isso é responsabilidade de quem chama.
    """
    body = {"textQuery": query, "languageCode": "pt-BR"}
    coletados = 0
    proximo_token = None

    while coletados < max_resultados:
        if proximo_token:
            body["pageToken"] = proximo_token
            time.sleep(2)  # nextPageToken só fica válido após um pequeno intervalo

        resp = requests.post(BASE_URL, headers=_headers(api_key), json=body, timeout=30)
        resp.raise_for_status()
        corpo = resp.json()

        resultados = corpo.get("places", [])
        for lugar in resultados:
            if coletados >= max_resultados:
                return
            yield lugar
            coletados += 1

        proximo_token = corpo.get("nextPageToken")
        if not proximo_token:
            return
