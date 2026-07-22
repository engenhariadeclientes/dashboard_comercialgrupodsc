-- ad_insights — investimento por criativo (para CPL) — spec seção 4.4
CREATE TABLE ad_insights (
  id           SERIAL PRIMARY KEY,
  plataforma   TEXT NOT NULL,     -- meta | google
  data         DATE NOT NULL,
  campanha_id  TEXT, campanha_nome TEXT,
  conjunto_id  TEXT, conjunto_nome TEXT,
  anuncio_id   TEXT, anuncio_nome TEXT,
  gasto        NUMERIC(12,2),
  impressoes   BIGINT,
  cliques      BIGINT,
  leads_plataforma INTEGER,       -- leads reportados pela plataforma
  UNIQUE (plataforma, data, anuncio_id)
);
CREATE INDEX ON ad_insights (data);
CREATE INDEX ON ad_insights (campanha_nome);
