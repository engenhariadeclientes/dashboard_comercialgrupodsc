# Chefe de Projetos

App simples para tirar da Stella a gestão de projetos do dia a dia: cada pessoa
vê e atualiza suas próprias tarefas, e a Stella tem uma visão geral de tudo
("chefe") sem precisar cobrar manualmente.

## O que já faz

- Login por nome + PIN (cada pessoa define o próprio PIN no primeiro acesso).
- Quadro pessoal: tarefas do dia, com status Pendente / Em andamento / Concluída.
- Tarefas recorrentes diárias já cadastradas (ex.: Daniela monitorar os agentes
  de IA, Leonardo monitorar automações, Gustavo stories) — são recriadas
  automaticamente todo dia.
- Cada pessoa pode adicionar tarefas avulsas no próprio quadro.
- Visão geral (`/chefe`, só para Stella): status de todo o time e contagem de
  pendências por projeto/campanha no dia.
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
2. Adicionar um Postgres ao projeto (pode ser um banco novo, não precisa ser o
   mesmo do Motor Comercial).
3. Configurar as variáveis de ambiente do serviço: `DATABASE_URL` (o Railway
   preenche sozinho se você linkar o Postgres) e `SESSION_SECRET` (gerar um
   valor aleatório e fixo).
4. O `railway.json` já roda `seed.py` antes de subir o servidor — o primeiro
   deploy cria as tabelas e popula os dados iniciais automaticamente.

## Próximos passos sugeridos

1. **Gestão de Carteira**: hoje é só um projeto cadastrado sem fluxo próprio.
   Quando vocês definirem como organizar isso (relacionamento com clientes,
   apresentação de resultados), dá pra criar um módulo específico e depois
   plugar relatórios automáticos vindos do Motor Comercial.
2. **Perfil com voz**: não é algo que dá pra plugar neste app de graça — é um
   projeto à parte (app com microfone, transcrição de voz e a Claude API
   respondendo, podendo até falar de volta). Faz sentido tocar depois que o
   quadro de tarefas estiver validado no dia a dia do time.
3. **Alertas automáticos**: dá pra evoluir para a Stella (ou o próprio
   sistema) avisar automaticamente quando uma tarefa recorrente não foi feita
   até um horário (ex.: WhatsApp ou e-mail), em vez de precisar abrir a visão
   geral manualmente.
