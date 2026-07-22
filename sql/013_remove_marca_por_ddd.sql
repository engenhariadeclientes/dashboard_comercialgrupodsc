-- Decisão 22/07/2026 (Stella): DDD do telefone deixou de ser fonte válida para
-- derivar marca (reverte o fallback original da regra 4.1.1) — indica onde a
-- linha foi ativada, não onde o condomínio fica. Leads cuja marca/UF só existiam
-- por causa do DDD (sem cidade real nem UF informada) voltam para "pendente".
UPDATE leads SET
  marca = NULL,
  uf = NULL,
  regiao = NULL,
  uf_derivada_por_ddd = false,
  atualizado_em = NOW()
WHERE uf_derivada_por_ddd = true;
