-- Backfill único: sincroniza os campos-espelho de `leads` (seção 4.1) a partir de
-- `negocios`, para os leads importados antes da correção que passou a manter esse
-- espelho atualizado nos importers/workers (22/07/2026). Quando um lead tem mais de
-- um negócio, usa o mais recentemente atualizado.
WITH negocio_mais_recente AS (
  SELECT DISTINCT ON (lead_id)
    lead_id, agendor_negocio_id, consultor, etapa_atual, valor, status, data_fechamento
  FROM negocios
  WHERE lead_id IS NOT NULL
  ORDER BY lead_id, atualizado_em DESC
)
UPDATE leads SET
  agendor_negocio_id = n.agendor_negocio_id,
  consultor = n.consultor,
  etapa_atual = n.etapa_atual,
  gerou_proposta = leads.gerou_proposta
    OR (n.valor IS NOT NULL AND n.valor > 0)
    OR (n.etapa_atual ILIKE '%proposta enviada%'),
  valor_orcamento = CASE WHEN n.valor IS NOT NULL AND n.valor > 0 THEN n.valor ELSE leads.valor_orcamento END,
  status_final = n.status,
  data_fechamento = n.data_fechamento,
  atualizado_em = NOW()
FROM negocio_mais_recente n
WHERE leads.id = n.lead_id;
