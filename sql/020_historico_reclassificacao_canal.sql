-- Registro de toda reclassificação de leads.canal_entrada feita pela correção
-- histórica (scripts/reclassificar_canais.py, pedido da Stella em 07/10/2026:
-- separar site / google_ads / meta_ads também no passado). Guarda o valor anterior
-- pra auditoria e pra desfazer, se preciso:
--   UPDATE leads l SET canal_entrada = h.canal_anterior
--   FROM leads_canal_reclassificacao h WHERE h.lead_id = l.id AND h.lote = '<lote>';
CREATE TABLE leads_canal_reclassificacao (
  id              SERIAL PRIMARY KEY,
  lote            TEXT NOT NULL,
  lead_id         INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  canal_anterior  TEXT NOT NULL,
  canal_novo      TEXT NOT NULL,
  motivo          TEXT NOT NULL,
  aplicado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON leads_canal_reclassificacao (lote);
CREATE INDEX ON leads_canal_reclassificacao (lead_id);
