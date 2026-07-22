"""Regras de negócio dos negócios do Agendor — spec seção 5.5.

Adaptado em 22/07/2026 (decisão da Stella) para o cenário real do Agendor:
- vale para TODOS os funis existentes na conta (não só Pré-Vendas/Vendas) — mesma
  concepção de regras aplicada a qualquer funil
- comparação de nome de etapa é flexível (case-insensitive, por conteúdo), pois a
  nomenclatura real varia (ex.: "Lead sem perfil" vs "Lead Sem Perfil"; "Aguardando
  Documentação para Contrato" vs "Aguardando Documentação")
"""
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
}


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
