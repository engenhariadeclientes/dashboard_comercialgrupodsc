-- Mais 3 leads de teste encontrados (pedido da Stella, 23/07/2026): nomes
-- começando com "Teste" (ex.: "Teste Rd Dsc", "Teste Cargo Cidade Dsc",
-- "Teste Digito Dsc") — confirmado sem negócio vinculado antes de apagar.
DELETE FROM eventos WHERE lead_id IN (5661, 5662, 5667);
DELETE FROM matching_pendente WHERE lead_id_candidato IN (5661, 5662, 5667);
DELETE FROM leads WHERE id IN (5661, 5662, 5667);
