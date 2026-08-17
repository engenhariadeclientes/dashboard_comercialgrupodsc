"""Worker prospeccao_google — spec seção 5.6. Roda sob demanda (cron manual/periódico).

Prospecção ativa outbound: busca empresas via Google Places API (categoria + cidade
definidas em config/prospeccao_google.yml) e entra na base como fila para abordagem
manual do consultor. NÃO dispara WhatsApp automaticamente (decisão 17/08/2026,
Stella — risco de bloqueio do número comercial em contato frio sem template
aprovado pela Meta).
"""
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workers.common.config import CONFIG_DIR  # noqa: E402
from workers.common.db import get_connection  # noqa: E402
from workers.common.eventos import registrar_evento  # noqa: E402
from workers.common.matching import resolver_ou_criar_lead  # noqa: E402
from workers.common.normalizacao import (  # noqa: E402
    derivar_marca,
    extrair_telefone_valido,
    gerar_variacoes_telefone,
    normalizar_nome,
)
from workers.common.sync_state import registrar_sync  # noqa: E402
from workers.google_places_api import buscar_empresas  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prospeccao_google")

WORKER = "prospeccao_google"
FONTE = "prospeccao_google"
CANAL = "prospeccao_google"


def _carregar_config() -> dict:
    with open(CONFIG_DIR / "prospeccao_google.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _extrair_cidade_uf(endereco_formatado: str) -> tuple[str | None, str | None]:
    """Extrai "Cidade" e "UF" do formattedAddress da Places API (formato BR padrão,
    ex.: "Rua X, 123 - Bairro, Blumenau - SC, 89010-000, Brasil")."""
    if not endereco_formatado:
        return None, None
    partes = [p.strip() for p in endereco_formatado.split(",")]
    for parte in partes:
        if " - " in parte:
            cidade, uf = parte.rsplit(" - ", 1)
            uf = uf.strip().upper()
            if len(uf) == 2:
                return cidade.strip(), uf
    return None, None


def _processar_lugar(conn, lugar: dict, categoria_id: str, cidade_busca: str) -> bool:
    """Retorna True se um lead novo foi criado."""
    nome = normalizar_nome((lugar.get("displayName") or {}).get("text"))
    telefone_raw = lugar.get("nationalPhoneNumber") or lugar.get("internationalPhoneNumber")
    telefone, invalido = extrair_telefone_valido(telefone_raw) if telefone_raw else (None, True)
    if invalido or not telefone:
        return False  # sem telefone válido não há como abordar — não entra na base

    cidade, uf = _extrair_cidade_uf(lugar.get("formattedAddress"))
    marca_info = derivar_marca(conn, cidade=cidade, uf_informada=uf, campanha=categoria_id)

    dados = {
        "nome": nome,
        "telefone": telefone,
        "telefone_variacoes": gerar_variacoes_telefone(telefone),
        "cidade": cidade or cidade_busca,
        "uf": marca_info["uf"],
        "regiao": marca_info["regiao"],
        "marca": marca_info["marca"],
        "uf_derivada_por_ddd": marca_info["uf_derivada_por_ddd"],
        "canal_entrada": CANAL,
        "campanha_entrada": categoria_id,
        "origem_detalhe_entrada": cidade_busca,
        "tipo_captura": "prospeccao_ativa",
        "data_entrada": datetime.now(timezone.utc),
    }

    lead_id, criado = resolver_ou_criar_lead(conn, dados, fonte=FONTE)
    if criado:
        registrar_evento(
            conn,
            lead_id=lead_id,
            fonte=FONTE,
            tipo_evento="lead_capturado",
            data_evento=dados["data_entrada"],
            canal=CANAL,
            campanha=categoria_id,
            origem_detalhe=cidade_busca,
            payload=lugar,
        )
    return criado


def rodar() -> None:
    api_key = os.environ["GOOGLE_PLACES_API_KEY"]
    config = _carregar_config()
    max_resultados = config.get("max_resultados_por_query", 60)

    total_novos = 0
    total_vistos = 0
    with get_connection() as conn:
        for categoria in config["categorias"]:
            for cidade in config["cidades"]:
                query = f"{categoria['query']} em {cidade}"
                logger.info("Buscando: %s", query)
                for lugar in buscar_empresas(api_key, query, max_resultados=max_resultados):
                    total_vistos += 1
                    try:
                        if _processar_lugar(conn, lugar, categoria["id"], cidade):
                            total_novos += 1
                    except Exception:
                        logger.exception("Falha processando resultado %r", lugar.get("displayName"))
                        conn.rollback()
                        continue
                    conn.commit()

        registrar_sync(
            conn,
            WORKER,
            datetime.now(timezone.utc),
            detalhes={"vistos": total_vistos, "novos": total_novos},
        )
        conn.commit()

    logger.info("Concluído: %d resultados vistos, %d leads novos criados.", total_vistos, total_novos)


if __name__ == "__main__":
    rodar()
