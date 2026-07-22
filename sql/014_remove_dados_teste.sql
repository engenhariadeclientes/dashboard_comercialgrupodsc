-- Remove registros de teste/QA identificados em 22/07/2026 — não são leads/negócios
-- reais, são dados de validação de formulário/import deixados no Agendor e no RD.
-- Confirmado antes de apagar: nenhum dos 5 leads tem negócio vinculado; nenhum dos
-- 12 negócios tem lead vinculado nem evento associado (todos com lead_id/valor nulos).

DELETE FROM eventos WHERE lead_id IN (671, 673, 708, 1735, 1736);
DELETE FROM matching_pendente WHERE lead_id_candidato IN (671, 673, 708, 1735, 1736);
DELETE FROM leads WHERE id IN (671, 673, 708, 1735, 1736);

DELETE FROM negocios WHERE id IN (7644, 7646, 15200, 15358, 15359, 15360, 15361, 15371, 15372, 15420, 15421, 22268);
