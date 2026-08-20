# CEO — Grupo DSC

App de gestão interna: cada pessoa vê e atualiza suas próprias tarefas, e a
Stella (CEO) tem uma visão geral de tudo, cadastra pessoas/projetos/agentes de
IA e pode reatribuir qualquer tarefa — sem precisar cobrar manualmente.

Banco de dados próprio, totalmente separado do Motor Comercial (que é um
sistema de um cliente, não da Engenharia de Clientes).

## O que já faz

- Login por nome + PIN (cada pessoa define o próprio PIN no primeiro acesso).
- Quadro pessoal: tarefas do dia, com status Pendente / Em andamento / Concluída.
- Tarefas recorrentes diárias já cadastradas (ex.: Daniela monitorar os agentes
  de IA, Leonardo monitorar automações, Gustavo stories) — são recriadas
  automaticamente todo dia.
- Cada pessoa pode adicionar tarefas avulsas no próprio quadro.
- Visão geral (`/chefe`, só para a CEO): status de todo o time, agentes de IA
  monitorados pela CS e pendências por projeto/campanha no dia.
- **Admin** (`/admin`, só para a CEO):
  - Pessoas: cadastrar novos usuários, editar cargo/skills/status.
  - Projetos/campanhas: cadastrar e ativar/desativar.
  - Agentes de IA: cadastrar os agentes monitorados pela CS (cliente,
    responsável, status ativo/com erro/pausado, observações).
  - Tarefas: ver todas as tarefas do dia de qualquer pessoa, reatribuir
    responsável e mudar status. Ao criar uma tarefa nova, o sistema sugere um
    responsável comparando o texto da tarefa com as skills cadastradas de
    cada pessoa (sugestão automática, mas você sempre pode trocar).
- **Dashboard** (`/dashboard`, só para a CEO): resumo de tarefas concluídas /
  em andamento / pendentes por pessoa, e lista das concluídas recentemente —
  filtro por 7/30/90 dias.
- Projetos/campanhas já cadastrados no seed: Assistente de Cobrança em IA,
  Consultoria de IA para Empresários, Método EP, Imersão Geração IA
  (prospecção de escolas), Operação de CS, Automações/Suporte, Gestão de
  Carteira.

## Rodando localmente

```
cd chefe_projetos
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://...   # banco próprio, separado do Motor Comercial
export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
python seed.py            # cria tabelas + popula pessoas/projetos/tarefas recorrentes
uvicorn app:app --reload
```

Acesse `http://localhost:8000`.

## Deploy no Railway

1. Criar um novo projeto no Railway apontando para este diretório
   (`chefe_projetos/`) como root do serviço.
2. Adicionar um Postgres ao projeto (banco novo, não é o do Motor Comercial).
3. Configurar as variáveis de ambiente do serviço: `DATABASE_URL` (o Railway
   preenche sozinho se você linkar o Postgres) e `SESSION_SECRET` (gerar um
   valor aleatório e fixo).
4. O `railway.json` já roda `seed.py` antes de subir o servidor — o primeiro
   deploy cria as tabelas e popula os dados iniciais automaticamente.

## Próximos passos sugeridos (na ordem que faz mais sentido)

1. **Módulo Financeiro**: evoluir a partir do CRM próprio da Engenharia de
   Clientes (não o Motor Comercial, que é de cliente) — puxar faturamento e
   receita de lá em vez de recriar do zero.
2. **Gestão de Carteira**: hoje é só um projeto cadastrado sem fluxo próprio.
   Quando definirem como organizar isso (relacionamento com clientes,
   apresentação de resultados), dá pra criar um módulo específico.
3. **Módulo de Marketing**: escopar separadamente — provavelmente conectado
   ao mesmo CRM/dados de campanhas.
4. **Repositório próprio**: hoje este app vive dentro do repo do Motor
   Comercial (que é de um cliente) só porque foi onde a sessão tinha acesso.
   Vale migrar para um repositório da própria Engenharia de Clientes assim
   que possível, para não misturar código interno com o de cliente.
5. **Perfil com voz**: projeto à parte (app com microfone, transcrição de voz
   e a Claude API respondendo, podendo até falar de volta). Fica para depois
   que o núcleo estiver validado no dia a dia do time.
6. **Alertas automáticos**: avisar automaticamente (WhatsApp/e-mail) quando
   uma tarefa recorrente não foi feita até um horário, em vez de depender de
   alguém abrir a visão geral manualmente.
