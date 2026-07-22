"""Carregamento dos arquivos de configuração editáveis em /config."""
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def carregar_form_field_map() -> dict:
    with open(CONFIG_DIR / "form_field_map.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def carregar_rd_exclusoes() -> list[str]:
    with open(CONFIG_DIR / "rd_exclusoes.yml", encoding="utf-8") as f:
        dados = yaml.safe_load(f)
    return [p.lower() for p in dados.get("padroes_exclusao", [])]


def texto_excluido_rd(texto: str, padroes: list[str]) -> bool:
    texto_lower = (texto or "").lower()
    return any(padrao in texto_lower for padrao in padroes)
