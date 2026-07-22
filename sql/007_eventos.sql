-- eventos — 1 linha por toque (trilha de auditoria completa) — spec seção 4.3
CREATE TABLE eventos (
  id              SERIAL PRIMARY KEY,
  lead_id         INTEGER REFERENCES leads(id),
  fonte           TEXT NOT NULL,   -- meta_ads | google_ads | botconversa | rd_station | agendor | importacao
  tipo_evento     TEXT NOT NULL,   -- lead_capturado, email_enviado, email_aberto, email_clicado, conversao_email,
                                   -- ia_iniciou_conversa, ia_qualificou, ia_desqualificou, negocio_criado,
                                   -- mudou_etapa, mudou_funil, proposta_gerada, valor_lancado, ganho, perdido,
                                   -- checkin_evento, importado
  canal           TEXT,            -- taxonomia da seção 3
  campanha        TEXT,
  origem_detalhe  TEXT,
  payload         JSONB,           -- dado bruto da API (auditoria)
  data_evento     TIMESTAMPTZ NOT NULL,
  criado_em       TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (fonte, tipo_evento, lead_id, data_evento)  -- anti-duplicação
);
CREATE INDEX ON eventos (lead_id);
CREATE INDEX ON eventos (tipo_evento);
CREATE INDEX ON eventos (data_evento);
