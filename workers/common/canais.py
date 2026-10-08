"""Classificação de canal de entrada (taxonomia da seção 3.1 da spec) a partir dos
sinais do BotConversa, e regra de precedência quando um lead já tem canal.

Fonte única usada pelo worker sync_botconversa e pela correção histórica
(sql/020 + scripts/reclassificar_canais.py), pra os dois nunca divergirem.

Decisões da Stella (07/10/2026):
- separar site / google_ads / meta_ads também no histórico
- anúncio pago (google_ads/meta_ads) prevalece sobre site e demais canais: se o
  lead chegou ao site por um anúncio, a origem é o anúncio
- "como nos conheceu" respondido no formulário do site (google, facebook...) é
  autodeclarado, não rastreio — o lead continua 'site'
"""
from typing import Iterable, Optional

CANAIS_PAGOS = {"google_ads", "meta_ads"}

# valores reais do campo "Canal de Aquisição" do BotConversa (levantados em
# 22/07/2026 e revisados em 07/10/2026 contra a base inteira); comparação em minúsculas
CANAL_AQUISICAO_MAP = {
    "facebook ads": "meta_ads",
    "anúncio": "meta_ads",
    "anuncio": "meta_ads",
    "anúncio instagram": "meta_ads",
    "anuncio instagram": "meta_ads",
    "anuncio meta": "meta_ads",
    "anúncio meta": "meta_ads",
    "google ads": "google_ads",
    "google": "google_ads",
    "anúncio google": "google_ads",
    "anuncio google": "google_ads",
    "site": "site",
    "cadastro no site dsc": "site",
    "formulário site": "site",
    "formulario site": "site",
    "orgânico - site": "site",
    "organico - site": "site",
}

# etiquetas que a automação de anúncios aplica no BotConversa (ex.: "Meta_ADS_06.26",
# "Anúncios DSC") — sinal de Meta mesmo quando "Canal de Aquisição" vem vazio
_PREFIXOS_TAG_META = ("meta_ads", "anúncios", "anuncios")


def mapear_canal_botconversa(canal_raw: Optional[str], tags: Iterable[str] = ()) -> Optional[str]:
    """Canal concreto revelado pelo BotConversa, ou None se não houver sinal."""
    canal = None
    if canal_raw:
        chave = canal_raw.strip().lower()
        canal = CANAL_AQUISICAO_MAP.get(chave)
        if canal is None and chave.startswith("calculadora"):
            canal = "site"  # iscas calculadora-* ficam nos sites institucionais
    if canal not in CANAIS_PAGOS and any(
        (t or "").strip().lower().startswith(_PREFIXOS_TAG_META) for t in tags
    ):
        canal = "meta_ads"
    return canal


def deve_substituir_canal(canal_atual: Optional[str], canal_novo: Optional[str]) -> bool:
    """Precedência: sem canal/organico aceita qualquer canal concreto; canal pago
    substitui qualquer canal não pago; entre dois canais concretos do mesmo nível
    mantém o primeiro toque (atribuição de origem)."""
    if not canal_novo or canal_novo == canal_atual:
        return False
    if canal_atual in (None, "organico"):
        return True
    return canal_novo in CANAIS_PAGOS and canal_atual not in CANAIS_PAGOS
