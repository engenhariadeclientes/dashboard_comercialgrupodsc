"""Regras de negócio dos negócios do Agendor — spec seção 5.5.

Adaptado em 22/07/2026 (decisão da Stella) para o cenário real do Agendor:
- vale para TODOS os funis existentes na conta (não só Pré-Vendas/Vendas) — mesma
  concepção de regras aplicada a qualquer funil
- comparação de nome de etapa é flexível (case-insensitive, por conteúdo), pois a
  nomenclatura real varia (ex.: "Lead sem perfil" vs "Lead Sem Perfil"; "Aguardando
  Documentação para Contrato" vs "Aguardando Documentação")
"""
import re
from typing import Optional

STATUS_MAP = {
    "em andamento": "aberto",
    "ganho": "ganho",
    "perdido": "perdido",
}

# Mapeamento de 'Origem do cliente' (campo próprio do Agendor) para a taxonomia da
# seção 3.1, usado só na carga histórica (negócio sem nenhum canal rastreado ainda).
# O que não mapear cai em 'organico' (decisão da Stella, 22/07/2026); o valor
# original do Agendor é sempre preservado em origem_detalhe_entrada.
ORIGEM_CLIENTE_PARA_CANAL = {
    "site": "site",
    "indicação de clientes duplique e dsc": "indicacao",
    "eventos participantes": "evento",
    "eventos patrocinados": "evento",
    "redes sociais": "meta_ads",  # confirmado pela Stella (22/07/2026): é como o Agendor rotula leads vindos de Meta Ads
    "link patrocinado": "google_ads",  # anúncio Google (07/10/2026, separação site/google/meta)
}

# Sinais de evento no Agendor além do nome "JP-<região>" (levantados em 07/10/2026
# na base inteira): categoria da pessoa e funil do negócio
CATEGORIAS_PESSOA_EVENTO = {"jornada porter": "Jornada_Porter", "porter summit": "Porter_Summit"}
FUNIS_EVENTO = {"funil de leads jornadas porter": "Jornada_Porter", "funil de leads summit": "Porter_Summit"}


def canal_concreto_origem_agendor(origem_raw: Optional[str]) -> Optional[str]:
    """Como mapear_canal_origem_agendor, mas None (em vez de 'organico') quando a
    origem não revela um canal da taxonomia — pra regra de precedência decidir."""
    if not origem_raw:
        return None
    return ORIGEM_CLIENTE_PARA_CANAL.get(origem_raw.strip().lower())


def campanha_evento_agendor(categoria_pessoa: Optional[str], funil: Optional[str]) -> Optional[str]:
    """Nome do evento (campanha_entrada) se categoria da pessoa ou funil indicarem evento."""
    for valor, mapa in ((categoria_pessoa, CATEGORIAS_PESSOA_EVENTO), (funil, FUNIS_EVENTO)):
        if valor and valor.strip().lower() in mapa:
            return mapa[valor.strip().lower()]
    return None


def mapear_status(status_raw: Optional[str]) -> str:
    if not status_raw:
        return "aberto"
    chave = status_raw.strip().lower()
    return STATUS_MAP.get(chave, chave)


def mapear_canal_origem_agendor(origem_raw: Optional[str]) -> str:
    if not origem_raw:
        return "organico"
    return ORIGEM_CLIENTE_PARA_CANAL.get(origem_raw.strip().lower(), "organico")


def _contem(etapa: Optional[str], termo: str) -> bool:
    return bool(etapa) and termo in etapa.strip().lower()


def eh_etapa_proposta_enviada(etapa: Optional[str]) -> bool:
    return _contem(etapa, "proposta enviada")


def eh_etapa_lead_sem_perfil(etapa: Optional[str]) -> bool:
    return _contem(etapa, "sem perfil")


def eh_etapa_assinatura_contrato(etapa: Optional[str]) -> bool:
    return _contem(etapa, "assinatura de contrato")


# Decisão 22/07/2026 (Stella): no Agendor, o nome da pessoa/negócio costuma
# carregar "JP" (Jornada Porter) + a região do evento (ex.: "Anna - Jp Brasília-p",
# "Demilson Guilhem - Jp Alphaville", "Maria Leal-jp-manaus") quando o lead entrou
# via esse evento — sinal usado pra classificar canal_entrada='evento' mesmo
# quando o primeiro toque registrado foi o sync do Agendor (que sozinho não sabe
# a origem real do contato).
_RE_JP_MARCADOR = re.compile(r"\bj\.?\s?p\.?\b", re.IGNORECASE)
_RE_SUFIXO_RUIDO_JP = re.compile(r"[\s\-]*(adm|m|p)(-(adm|m|p))*$", re.IGNORECASE)


def eh_nome_jornada_porter(nome: Optional[str]) -> bool:
    return bool(nome) and bool(_RE_JP_MARCADOR.search(nome))


def extrair_regiao_jornada_porter(nome: Optional[str]) -> Optional[str]:
    if not nome:
        return None
    m = _RE_JP_MARCADOR.search(nome)
    if not m:
        return None
    resto = nome[m.end():].strip(" -")
    resto = _RE_SUFIXO_RUIDO_JP.sub("", resto).strip(" -")
    return resto.title() if resto else None
