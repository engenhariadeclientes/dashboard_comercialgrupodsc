-- Guarda um retrato consultável dos campos personalizados do BotConversa mais
-- relevantes pro acompanhamento comercial (temperatura, perfil, resumo da
-- conversa, agendamento solicitado, motivo de desqualificação). Diferente do
-- payload dos eventos (histórico, não sobrescreve), esta coluna sempre reflete
-- o estado mais recente — pedido da Stella (22/07/2026) pra dar visão de "em
-- conversa com IA" além do número.
ALTER TABLE leads ADD COLUMN dados_botconversa JSONB;
