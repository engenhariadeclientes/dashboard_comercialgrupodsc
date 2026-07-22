-- leads — 1 linha por pessoa (estado consolidado) — spec seção 4.1
CREATE TABLE leads (
  id                    SERIAL PRIMARY KEY,
  nome                  TEXT,
  telefone              TEXT,          -- normalizado E.164 BR (+55...)
  telefone_variacoes    TEXT[],        -- com/sem 9º dígito, para matching
  email                 TEXT,          -- lowercase
  cidade                TEXT,
  uf                    CHAR(2),
  regiao                TEXT,          -- derivada da UF/cidade
  profissao_funcao      TEXT,          -- síndico, conselheiro, administrador...
  marca                 TEXT,          -- 'Duplique' | 'DSC' — DERIVADA da localização (regra 4.1.1)
  uf_derivada_por_ddd   BOOLEAN DEFAULT FALSE,  -- confiança menor; qualquer fonte posterior com cidade real sobrescreve (regras 4.1.1 e 8.1)

  -- primeiro toque (aquisição)
  canal_entrada         TEXT NOT NULL,
  campanha_entrada      TEXT,
  origem_detalhe_entrada TEXT,
  tipo_captura          TEXT,
  data_entrada          TIMESTAMPTZ,

  -- camada IA
  passou_ia             BOOLEAN DEFAULT FALSE,
  status_ia             TEXT,          -- em_conversa | qualificado | desqualificado | sem_resposta
  qualificado_sql       BOOLEAN DEFAULT FALSE,
  data_qualificacao     TIMESTAMPTZ,

  -- comercial (espelho do estado atual no Agendor)
  agendor_negocio_id    BIGINT,
  consultor             TEXT,
  etapa_atual           TEXT,
  gerou_proposta        BOOLEAN DEFAULT FALSE,
  valor_orcamento       NUMERIC(12,2),
  status_final          TEXT DEFAULT 'aberto',  -- aberto | ganho | perdido
  data_fechamento       TIMESTAMPTZ,

  criado_em             TIMESTAMPTZ DEFAULT NOW(),
  atualizado_em         TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX ON leads (telefone) WHERE telefone IS NOT NULL;
CREATE INDEX ON leads (email);
CREATE INDEX ON leads (canal_entrada, campanha_entrada);
CREATE INDEX ON leads USING gin (nome gin_trgm_ops);
