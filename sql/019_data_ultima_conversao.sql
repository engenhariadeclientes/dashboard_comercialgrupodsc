-- Última conversão/toque real de cada lead — distinto de `atualizado_em`, que muda
-- a cada ciclo de sync (30 min) mesmo sem nenhuma novidade real. Atualizado em
-- workers/common/eventos.py toda vez que um evento é registrado de fato (não em
-- refresh de rotina). Pedido da Stella (12/08/2026): pra análise de gestão, a
-- última conversão deve vir antes do primeiro toque — um lead que entrou numa
-- jornada em julho e reconverteu por outro canal em agosto deve aparecer como
-- recente, não como "de julho".
ALTER TABLE leads ADD COLUMN data_ultima_conversao TIMESTAMPTZ;

UPDATE leads l
SET data_ultima_conversao = COALESCE(
  (SELECT MAX(e.data_evento) FROM eventos e WHERE e.lead_id = l.id),
  l.data_entrada
);

CREATE INDEX ON leads (data_ultima_conversao);
