-- negocios — espelho dos negócios do Agendor — spec seção 4.2
CREATE TABLE negocios (
  id                  SERIAL PRIMARY KEY,
  agendor_negocio_id  BIGINT UNIQUE NOT NULL,
  lead_id             INTEGER REFERENCES leads(id),
  titulo              TEXT,
  funil               TEXT,
  etapa_atual         TEXT,
  consultor           TEXT,
  valor               NUMERIC(12,2),   -- valor BRUTO do Agendor, como está lá (inconsistente: ora taxa, ora mensalidade)
  mensalidade_media   NUMERIC(12,2),   -- PRÉ-PREENCHIDA pelo worker com o valor bruto do Agendor; ajustável manualmente
  mensalidade_ajustada BOOLEAN DEFAULT FALSE,  -- vira TRUE quando alguém confere/ajusta o valor
  receita_para_roi    NUMERIC(12,2) GENERATED ALWAYS AS (mensalidade_media * 12) STORED,  -- horizonte fixo: 12 meses (DEFINIDO)
  status              TEXT,            -- aberto | ganho | perdido
  motivo_perda        TEXT,
  data_criacao        TIMESTAMPTZ,
  data_fechamento     TIMESTAMPTZ,
  atualizado_em       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON negocios (lead_id);
CREATE INDEX ON negocios (funil, etapa_atual);
CREATE INDEX ON negocios (status);
