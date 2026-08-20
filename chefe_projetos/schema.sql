-- Schema do "Chefe de Projetos" — banco próprio, separado do Motor Comercial.
-- Rodar com: python seed.py (cria as tabelas e popula os dados iniciais)

create extension if not exists pgcrypto;

create table if not exists pessoas (
    id uuid primary key default gen_random_uuid(),
    nome text not null,
    cargo text not null,
    eh_chefe boolean not null default false,
    pin_hash text,                -- null até a pessoa definir o PIN no primeiro acesso
    criado_em timestamptz not null default now()
);

create table if not exists projetos (
    id uuid primary key default gen_random_uuid(),
    nome text not null,
    tipo text not null default 'campanha',  -- 'campanha' | 'operacao' | 'carteira'
    ativo boolean not null default true,
    criado_em timestamptz not null default now()
);

-- Modelos de tarefa recorrente (ex.: "monitorar agentes de IA", diária, da Daniela)
create table if not exists tarefas_recorrentes (
    id uuid primary key default gen_random_uuid(),
    titulo text not null,
    descricao text,
    pessoa_id uuid not null references pessoas(id),
    projeto_id uuid references projetos(id),
    frequencia text not null default 'diaria',  -- 'diaria' por enquanto
    ativa boolean not null default true,
    criado_em timestamptz not null default now()
);

-- Tarefas reais (avulsas ou instâncias geradas a partir de um modelo recorrente)
create table if not exists tarefas (
    id uuid primary key default gen_random_uuid(),
    titulo text not null,
    descricao text,
    pessoa_id uuid not null references pessoas(id),
    projeto_id uuid references projetos(id),
    origem_recorrente_id uuid references tarefas_recorrentes(id),
    data_referencia date not null default current_date,
    status text not null default 'pendente',  -- 'pendente' | 'em_andamento' | 'concluida'
    criado_em timestamptz not null default now(),
    concluida_em timestamptz,
    unique (origem_recorrente_id, data_referencia)
);

create index if not exists idx_tarefas_pessoa_data on tarefas (pessoa_id, data_referencia);
create index if not exists idx_tarefas_status on tarefas (status);
