-- matching_pendente — fila de revisão manual do matching por nome fuzzy (spec seção 6, item 3)
CREATE TABLE matching_pendente (
  id                  SERIAL PRIMARY KEY,
  lead_id_candidato   INTEGER REFERENCES leads(id),  -- lead existente que pode ser a mesma pessoa
  nome_recebido       TEXT,
  telefone_recebido   TEXT,
  email_recebido      TEXT,
  fonte               TEXT,
  similaridade        NUMERIC(4,3),   -- score de similaridade (pg_trgm)
  payload             JSONB,          -- dado bruto recebido, para auditoria
  status              TEXT DEFAULT 'pendente',  -- pendente | confirmado | rejeitado
  revisado_por        TEXT,
  revisado_em         TIMESTAMPTZ,
  criado_em           TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON matching_pendente (status);
