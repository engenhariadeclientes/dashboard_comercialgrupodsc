# Motor Comercial DSC/Duplique

Sistema de rastreabilidade de leads (do anúncio à venda). Especificação completa em
[`docs/ESPECIFICACAO_Motor_Comercial_DSC_Duplique.md`](docs/ESPECIFICACAO_Motor_Comercial_DSC_Duplique.md)
— fonte única de verdade do projeto.

**Stack:** PostgreSQL + Python 3.12 (workers/importers) + Metabase, tudo no Railway.

## Estrutura

- `sql/` — migrations (rodar com `python sql/run_migrations.py`, requer `DATABASE_URL`)
- `workers/` — processos agendados (cron Railway), ex.: `sync_agendor.py`
  - `workers/common/` — normalização, matching, eventos, config — compartilhado por workers e importers
- `importers/` — scripts de carga inicial (rodados uma vez, manualmente)
- `config/` — `form_field_map.yml`, `rd_exclusoes.yml` e `prospeccao_google.yml`, editáveis sem mexer em código
- `docs/` — especificação

## Setup local

```
python -m venv .venv   # opcional
pip install -r requirements.txt
export DATABASE_URL=postgresql://...   # ou variável do Railway
python sql/run_migrations.py
```

## Dados sensíveis

Arquivos de carga inicial (exports do Agendor, RD Station, BotConversa, Meta) contêm
PII real de leads/clientes e **nunca são commitados** (ver `.gitignore`). Ficam só
localmente ou no volume do Railway.

## Fases

Este repositório implementa a **Fase 1** (Postgres + schema + importers de carga
inicial + worker `sync_agendor` + Metabase). Fases 2-4 (Meta, Google Ads API,
BotConversa, RD Station, endpoint `/api/lead`) estão descritas na seção 12 da spec.
