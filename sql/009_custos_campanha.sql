-- custos_campanha — custos que não vêm de API (para ROI) — spec seção 4.5
CREATE TABLE custos_campanha (
  id          SERIAL PRIMARY KEY,
  canal       TEXT NOT NULL,        -- taxonomia da seção 3
  campanha    TEXT,                 -- NULL = custo do canal como um todo
  marca       TEXT,                 -- 'DSC' | 'Duplique' | NULL (rateado)
  competencia DATE NOT NULL,        -- mês de referência
  valor       NUMERIC(12,2) NOT NULL,
  descricao   TEXT,
  criado_em   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON custos_campanha (canal, campanha, competencia);
