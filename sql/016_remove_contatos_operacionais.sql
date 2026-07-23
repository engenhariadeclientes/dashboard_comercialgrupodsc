-- Remove leads criados por engano nas primeiras sincronizações do BotConversa
-- antes do filtro de "Contato_Operacional" existir (decisão da Stella,
-- 22/07/2026: contatos não comerciais não devem virar lead). Confirmado antes
-- de apagar: nenhum tem negócio vinculado.
DELETE FROM eventos WHERE lead_id IN (5004, 5489, 5491, 5673);
DELETE FROM matching_pendente WHERE lead_id_candidato IN (5004, 5489, 5491, 5673);
DELETE FROM leads WHERE id IN (5004, 5489, 5491, 5673);
