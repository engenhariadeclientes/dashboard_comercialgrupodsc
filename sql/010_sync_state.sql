-- sync_state — controle de sync incremental por worker (spec seção 7)
CREATE TABLE sync_state (
  worker        TEXT PRIMARY KEY,   -- ex.: 'sync_agendor'
  ultimo_sync   TIMESTAMPTZ,
  detalhes      JSONB,              -- espaço livre p/ cursores/paginação específicos do worker
  atualizado_em TIMESTAMPTZ DEFAULT NOW()
);
