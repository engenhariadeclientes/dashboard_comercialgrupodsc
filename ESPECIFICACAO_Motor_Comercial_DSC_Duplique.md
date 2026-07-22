# ESPECIFICAÇÃO — Motor Comercial DSC/Duplique
## Sistema de rastreabilidade de leads: do anúncio à venda

**Versão:** 2.0 — **FINAL, validada por Stella em 21/07/2026. Pronta para implementação no Claude Code.**
**Stack:** PostgreSQL + Python workers + Metabase, tudo no Railway
**Status das pendências:** 11 de 11 resolvidas (seção 10 registra cada decisão)
**Regra de ouro:** o Claude Code implementa exatamente o que está aqui; qualquer desvio necessário volta para a Stella decidir antes de codar.

---

## 1. Objetivo

Uma base de dados única que responde, para cada lead:

1. De qual **canal** e **campanha** ele veio (e, se anúncio, de qual **criativo**)
2. Região, profissão/função e dados pessoais
3. Passou pela **IA (Júlia/BotConversa)**? Foi qualificado?
4. Foi distribuído para qual **consultor**?
5. Em qual **etapa do Agendor** está agora (com histórico de movimentação do cartão)
6. Gerou **proposta**? Qual **valor de orçamento** lançado?
7. **Deu venda?** (ganho/perdido/aberto)

Mais um dashboard (Metabase) com filtros e somatórias do momento atual.

---

## 2. Arquitetura

```
┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────┐
│  Meta Ads    │  │ BotConversa  │  │ RD Station  │  │   Agendor    │
│ (Graph API)  │  │    (API)     │  │  (API v2)   │  │   (API v3)   │
└──────┬───────┘  └──────┬───────┘  └──────┬──────┘  └──────┬───────┘
       │                 │                 │                │
   worker cron       worker cron       worker cron      worker cron
       │                 │                 │                │
       └────────────┬────┴────────┬───────┴───────┬────────┘
                    ▼             ▼               ▼
              ┌─────────────────────────────────────┐
              │      PostgreSQL (Railway)           │
              │  leads · negocios · eventos         │
              └──────────────────┬──────────────────┘
                                 ▼
              ┌─────────────────────────────────────┐
              │       Metabase (Railway)            │
              │  funil · filtros · somatórias       │
              └─────────────────────────────────────┘

Cargas manuais (CSV padronizado): leads de eventos presenciais,
histórico inicial do Agendor, bases antigas.
```

Repositório GitHub único com: `/workers`, `/importers`, `/sql`, `/docs`.

### 2.1 Inventário de contas (DEFINIDO)

| Plataforma | Contas | Observação |
|---|---|---|
| Meta Ads | **2** (Duplique + DSC) | worker `sync_meta` roda para as duas contas (dois tokens/ad_account_ids); `ad_insights` e leads carregam a conta de origem |
| BotConversa | **2** (Duplique + DSC) | worker `sync_botconversa` roda para as duas contas (duas API keys); mesmo mapeamento de campos da Júlia nas duas |
| Agendor | **1** (única para os dois grupos) | funis Pré-Vendas e Vendas compartilhados |
| RD Station | **1** (conta Duplique Santa Catarina) | com regras de exclusão (5.3) |
| Google Ads | a confirmar | histórico via planilha independe de conta |

---

## 3. Taxonomia de rastreabilidade (OBRIGATÓRIA)

Todo lead e todo evento carregam estes 3 campos. Valores fechados — nunca texto livre.

### 3.1 `canal` (enum)

| Valor | Significado |
|---|---|
| `meta_ads` | Anúncio Meta (form nativo ou clique p/ isca) |
| `google_ads` | Anúncio Google |
| `email_rd` | Campanha de e-mail via RD Station |
| `whatsapp_ativo` | Campanha de ativação/reativação via WhatsApp (BotConversa) |
| `evento` | Evento presencial (Jornada Porter, feiras, palestras, assembleias) |
| `site` | Cadastro espontâneo nos formulários dos sites institucionais (sem UTM de origem paga) |
| `indicacao` | Indicação/parceiro |
| `organico` | Demais entradas espontâneas (WhatsApp direto, telefone) |
| `outro` | Exceções (exige preenchimento de `origem_detalhe`) |

### 3.2 `campanha` (texto padronizado)

Nome da campanha na plataforma de origem. Para Meta/Google: nome exato da campanha na conta de anúncios. Para RD: nome da campanha de e-mail. Para WhatsApp ativo: nome interno da campanha (ex.: `Reativacao_Sindicos_Jul26`). Para eventos: nome do evento (ex.: `Jornada_Porter_Blumenau_2026`).

### 3.3 `origem_detalhe` (texto padronizado)

O nível mais granular: **criativo/anúncio** (id + nome) na Meta/Google; **assunto/nome do e-mail** no RD; **fluxo/etiqueta** no BotConversa; **atividade dentro do evento** (palestra, estande) quando aplicável.

### 3.4 Tipo de conversão de anúncio

Campo adicional `tipo_captura` para leads de anúncio: `form_nativo` | `isca_calculadora` | `clique_whatsapp` | `lp_formulario`.

### 3.5 Regra de UTMs (obrigatória para LPs)

Toda LP que recebe tráfego pago (Google Ads e Meta quando apontar pra LP) precisa:
1. Receber as UTMs na URL: `utm_source`, `utm_medium`, `utm_campaign`, `utm_content` (criativo/anúncio), `utm_term` (palavra-chave, Google)
2. Gravar as UTMs em **campos ocultos do formulário** (via script na LP — padrão GTM que já foi trabalhado na estratégia de pursuit Meta+Google)
3. No Google Ads, usar template de rastreamento com `{campaignid}`, `{creative}`, `{keyword}` para preencher automaticamente

Mapeamento na base: `utm_source/medium` → `canal` · `utm_campaign` → `campanha` · `utm_content`/`utm_term` → `origem_detalhe`.

**Lead de LP sem UTM** entra com `canal=organico` e flag `atribuicao_incompleta=true` no payload — assim o dash mostra o % de leads órfãos e dá pra corrigir a LP que estiver vazando atribuição.

---

## 4. Schema do banco

### 4.1 `leads` — 1 linha por pessoa (estado consolidado)

```sql
CREATE TABLE leads (
  id                    SERIAL PRIMARY KEY,
  nome                  TEXT,
  telefone              TEXT,          -- normalizado E.164 BR (+55...)
  telefone_variacoes    TEXT[],        -- com/sem 9º dígito, para matching
  email                 TEXT,          -- lowercase
  cidade                TEXT,
  uf                    CHAR(2),
  regiao                TEXT,          -- derivada da UF/cidade
  profissao_funcao      TEXT,          -- síndico, conselheiro, administrador...
  marca                 TEXT,          -- 'Duplique' | 'DSC' — DERIVADA da localização (regra 4.1.1)

  -- primeiro toque (aquisição)
  canal_entrada         TEXT NOT NULL,
  campanha_entrada      TEXT,
  origem_detalhe_entrada TEXT,
  tipo_captura          TEXT,
  data_entrada          TIMESTAMPTZ,

  -- camada IA
  passou_ia             BOOLEAN DEFAULT FALSE,
  status_ia             TEXT,          -- em_conversa | qualificado | desqualificado | sem_resposta
  qualificado_sql       BOOLEAN DEFAULT FALSE,
  data_qualificacao     TIMESTAMPTZ,

  -- comercial (espelho do estado atual no Agendor)
  agendor_negocio_id    BIGINT,
  consultor             TEXT,
  etapa_atual           TEXT,
  gerou_proposta        BOOLEAN DEFAULT FALSE,
  valor_orcamento       NUMERIC(12,2),
  status_final          TEXT DEFAULT 'aberto',  -- aberto | ganho | perdido
  data_fechamento       TIMESTAMPTZ,

  criado_em             TIMESTAMPTZ DEFAULT NOW(),
  atualizado_em         TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX ON leads (telefone) WHERE telefone IS NOT NULL;
CREATE INDEX ON leads (email);
CREATE INDEX ON leads (canal_entrada, campanha_entrada);
```

#### 4.1.1 Regra de marca (DEFINIDO — regra de negócio central)

A marca do lead é **derivada da localização do condomínio**, nunca preenchida à mão:

- `uf = 'SC'` → **Duplique**
- qualquer outra UF do Brasil → **DSC**
- localização desconhecida → `marca = NULL` (estado "pendente"); resolvida assim que qualquer fonte trouxer cidade/UF (form, Júlia via `REGIAO`, Agendor, RD). Card no dash mostra leads com marca pendente

A cidade informada nos forms (texto livre, ex.: "Barra do Sul") é resolvida para UF via tabela de municípios do IBGE embarcada no sistema; ambiguidade (cidades homônimas em estados diferentes) → prioriza SC se houver município em SC com o nome, senão marca pendente para revisão. **Fallback adicional (leads sem cidade — ex.: eventos):** UF derivada do **DDD do telefone** (47/48/49 → SC; mapa completo DDD→UF embarcado), com flag `uf_derivada_por_ddd=true` — confiança menor; qualquer fonte posterior com cidade real sobrescreve.

Nota: a origem da campanha **não** define a marca (um anúncio da Duplique pode captar lead de fora de SC — ele entra como DSC). A marca da campanha e a marca do lead são dados distintos: `custos_campanha.marca`/nomenclatura identificam quem pagou a campanha; `leads.marca` identifica quem atende o lead.

### 4.2 `negocios` — espelho dos negócios do Agendor

```sql
CREATE TABLE negocios (
  id                  SERIAL PRIMARY KEY,
  agendor_negocio_id  BIGINT UNIQUE NOT NULL,
  lead_id             INTEGER REFERENCES leads(id),
  titulo              TEXT,
  funil               TEXT,
  etapa_atual         TEXT,
  consultor           TEXT,
  valor               NUMERIC(12,2),   -- valor BRUTO do Agendor, como está lá (inconsistente: ora taxa, ora mensalidade)
  mensalidade_media   NUMERIC(12,2),   -- PRÉ-PREENCHIDA pelo worker com o valor bruto do Agendor; ajustável manualmente
  mensalidade_ajustada BOOLEAN DEFAULT FALSE,  -- vira TRUE quando alguém confere/ajusta o valor
  receita_para_roi    NUMERIC(12,2) GENERATED ALWAYS AS (mensalidade_media * 12) STORED,  -- horizonte fixo: 12 meses (DEFINIDO)
  status              TEXT,            -- aberto | ganho | perdido
  motivo_perda        TEXT,
  data_criacao        TIMESTAMPTZ,
  data_fechamento     TIMESTAMPTZ,
  atualizado_em       TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.3 `eventos` — 1 linha por toque (trilha de auditoria completa)

```sql
CREATE TABLE eventos (
  id              SERIAL PRIMARY KEY,
  lead_id         INTEGER REFERENCES leads(id),
  fonte           TEXT NOT NULL,   -- meta_ads | google_ads | botconversa | rd_station | agendor | importacao
  tipo_evento     TEXT NOT NULL,   -- ver lista abaixo
  canal           TEXT,            -- taxonomia da seção 3
  campanha        TEXT,
  origem_detalhe  TEXT,
  payload         JSONB,           -- dado bruto da API (auditoria)
  data_evento     TIMESTAMPTZ NOT NULL,
  criado_em       TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (fonte, tipo_evento, lead_id, data_evento)  -- anti-duplicação
);
```

**`tipo_evento` (enum):** `lead_capturado`, `email_enviado`, `email_aberto`, `email_clicado`, `conversao_email`, `ia_iniciou_conversa`, `ia_qualificou`, `ia_desqualificou`, `negocio_criado`, `mudou_etapa` (payload: etapa_de → etapa_para), `mudou_funil` (payload: funil_de → funil_para), `proposta_gerada`, `valor_lancado`, `ganho`, `perdido`, `checkin_evento`, `importado`.

> Com `eventos` guardando cada `mudou_etapa`, o Metabase calcula tempo médio por etapa e mostra o "movimento do cartão" — o acompanhamento automático que você pediu.

### 4.4 `ad_insights` — investimento por criativo (para CPL)

```sql
CREATE TABLE ad_insights (
  id           SERIAL PRIMARY KEY,
  plataforma   TEXT NOT NULL,     -- meta | google
  data         DATE NOT NULL,
  campanha_id  TEXT, campanha_nome TEXT,
  conjunto_id  TEXT, conjunto_nome TEXT,
  anuncio_id   TEXT, anuncio_nome TEXT,
  gasto        NUMERIC(12,2),
  impressoes   BIGINT,
  cliques      BIGINT,
  leads_plataforma INTEGER,       -- leads reportados pela plataforma
  UNIQUE (plataforma, data, anuncio_id)
);
```

Sem esta tabela não existe CPL por criativo no dash — por isso ela é parte do escopo mínimo.

### 4.5 `custos_campanha` — custos que não vêm de API (para ROI)

**Três vias de entrada de custo (DECIDIDO):**

1. **Meta Ads** → automático via API (`ad_insights`), nada manual
2. **Google Ads** → relatórios enviados pela Stella (o sistema pede; ver 8.3 — importer com CSV padrão do relatório de campanhas do Google Ads)
3. **Eventos e demais custos manuais** → formulário de lançamento (Metabase ou planilha padrão) na tabela abaixo

```sql
CREATE TABLE custos_campanha (
  id          SERIAL PRIMARY KEY,
  canal       TEXT NOT NULL,        -- taxonomia da seção 3
  campanha    TEXT,                 -- NULL = custo do canal como um todo
  marca       TEXT,                 -- 'DSC' | 'Duplique' | NULL (rateado)
  competencia DATE NOT NULL,        -- mês de referência
  valor       NUMERIC(12,2) NOT NULL,
  descricao   TEXT,
  criado_em   TIMESTAMPTZ DEFAULT NOW()
);
```

**Custo total de um canal/campanha no período = `ad_insights.gasto` + `custos_campanha.valor`.**

**Regra do aviso de custo pendente (DECIDIDO):** ROI nunca é exibido "mentiroso". Se existir campanha com leads/vendas no período mas **sem custo lançado** (nenhuma linha em `ad_insights` nem em `custos_campanha` para aquele canal+campanha+competência), o Painel 5 exibe o indicador **"⚠ Custo pendente — preencha para calcular o ROI"** no lugar do número, e um card lista todas as campanhas nessa situação. Vale principalmente para `canal=evento` e para meses do Google sem relatório importado.

---

## 5. Fontes de dados e endpoints

### 5.1 Meta Ads (Graph API) — worker `sync_meta`, a cada 1h
- Leads de form nativo: `GET /{form_id}/leads` (ou `/{ad_id}/leads`) — traz `ad_id`, `campaign_id`, `field_data`
- Metadados: `GET /{ad_id}?fields=name,adset{name},campaign{name}` para nomear campanha/conjunto/criativo
- Insights (gasto): `GET /act_{account_id}/insights?level=ad&time_increment=1`
- Cada lead novo → upsert em `leads` + evento `lead_capturado` com `canal=meta_ads`

**Campos dos forms nativos (DEFINIDO — prints de 21/07/2026):**

Os forms usam **redações diferentes para a mesma pergunta** ao longo do tempo. O worker mapeia por **dicionário de sinônimos** (arquivo de configuração `form_field_map.yml`, editável sem mexer no código):

| Destino na base | Variações de pergunta já observadas |
|---|---|
| `leads.email` | `Email` |
| `leads.nome` | `First Name`, `Full name` |
| `leads.telefone` | `Phone Number`, `Phone number` |
| `leads.cidade` → `uf`/`regiao` | "Onde Está Localizado O Seu Condomínio", "Onde fica seu condomínio" |
| `leads.profissao_funcao` | "Você É" (raw ex.: `gestor_condominial_`), "Qual é sua relação com o condomínio?" (ex.: "Síndico (a) morador (a)") |
| `origem_detalhe` complementar | `Form Name`; `Identificação do formulário do lead` (id numérico) |

Regras: pergunta não mapeada → guarda no `payload` e registra em log de "pergunta desconhecida" para adicionar ao dicionário; campo ausente → NULL, nunca erro. Respostas de função/relação são normalizadas para um conjunto padrão (síndico, síndico morador, gestor condominial, conselheiro, morador, outro).

**Higienização de dados do form (OBRIGATÓRIA):** os forms nativos entregam dados sujos. Exemplos reais: telefone duplicado/concatenado (`+554499117706655449991177...`), nomes com sufixos estranhos ("...de Oliveira.ra"). A normalização de telefone deve: extrair o primeiro número válido BR (DDD + 8/9 dígitos) da string, descartar o excedente, validar DDD existente; telefone irrecuperável → lead entra com `telefone=NULL` e flag `telefone_invalido` no payload (matching cai para e-mail). Nomes: trim, remoção de sufixos não alfabéticos, capitalização.

### 5.2 BotConversa — worker `sync_botconversa`, a cada 1h
- Padrão já usado nos projetos DSC Cobrança e Stilo: busca de subscriber por telefone, leitura de campos personalizados e etiquetas

**Mapeamento dos campos da Júlia comercial (DEFINIDO — validar nomes exatos via API na implementação, pois a grafia no painel pode variar: ex. "RESUMO CONVERSA" com espaço, "Canal de Aquisição" com acento):**

| Campo BotConversa | Tipo | Destino na base |
|---|---|---|
| `primeiro-nome` | entrada | `leads.nome` (complemento) |
| `Email` | entrada | `leads.email` |
| `canal-aquisicao` (ex.: "Facebook Ads") | entrada | mapeia → `canal` da taxonomia (Facebook Ads → `meta_ads`) |
| `cargo-funcao` | entrada | `leads.profissao_funcao` |
| `regiao` (minúsculo) | entrada | `leads.regiao` |
| `data-inscricao` | entrada | data de entrada no fluxo |
| `REGIAO` (maiúsculo) | saída (Júlia confirma se entrada vazia) | sobrescreve `leads.regiao` se preenchido |
| `TEMPERATURA` | saída | payload do evento de qualificação (frio/morno/quente) |
| `PERFIL_CLIENTE` | saída | payload do evento |
| `DATA_SOLICITADA` + `HORARIO_SOLICITADO` | saída | payload (agendamento da reunião) |
| `TELEFONE_DECISOR` | saída | possível novo telefone → matching |
| `RESUMO_CONVERSA` | saída | payload do evento (contexto p/ consultor) |
| `MOTIVO_NAO_QUAL` | saída | payload do evento `ia_desqualificou` |

**Qualificação — fluxos de saída do agente:** `SUCESSO` → evento `ia_qualificou` (`qualificado_sql=true`) · `NAO_QUALIFICADO` → evento `ia_desqualificou` (motivo em `MOTIVO_NAO_QUAL`) · `INSUCESSO` → `status_ia=sem_resposta`, permanece elegível a reativação.

- Leads de campanha `whatsapp_ativo`: identificados por etiqueta da campanha
- Gera eventos `ia_iniciou_conversa`, `ia_qualificou`, `ia_desqualificou`

### 5.3 RD Station Marketing (API v2, OAuth2) — worker `sync_rd`, a cada 3h
- **Conta RD: Duplique Santa Catarina** (token público já registrado → `RD_API_KEY` no Railway). A marca do lead segue sempre a regra 4.1.1 (localização), independentemente da conta RD de origem. ⚠️ Se existir conta RD separada para DSC, o worker replica a estrutura com segundo conjunto de credenciais
- Eventos de e-mail por lead: envio, abertura, clique, conversão

**Regras de exclusão (DEFINIDO):** e-mails de relacionamento com clientes existentes **não entram** na base nem nas métricas do funil/ROI:
1. **Onboarding / boas-vindas** (fluxos de entrada de novos clientes)
2. **Pesquisa de satisfação** (NPS e similares)

Mecanismo: lista de exclusão configurável (`rd_exclusoes.yml`) por padrão de nome de campanha/e-mail — inicial: `onboarding`, `boas-vindas`, `bem-vindo`, `pesquisa de satisfação`, `satisfação`, `nps` (case-insensitive). E-mail excluído → nem evento é gravado. A lista é editável sem código; log mensal mostra o que foi excluído para conferência de que nada de aquisição caiu no filtro por engano.
- Contatos: `GET /platform/contacts` (email como chave)
- Conversões viram evento `conversao_email` com `canal=email_rd`, `campanha` = nome da campanha de e-mail, `origem_detalhe` = nome/assunto do e-mail
- Se o contato não existir na base → cria lead com `canal_entrada=email_rd`

### 5.4 Landing Pages e formulários dos sites institucionais — captura direta
- **Caminho preferido (LPs novas e sites):** o formulário envia POST para um endpoint próprio (`/api/lead` no Railway, mesmo padrão dos webhooks BotConversa já usados) com dados + UTMs → upsert em `leads` + evento `lead_capturado` em tempo real, sem depender de sync
- **Sites institucionais (DEFINIDO):** os formulários de cadastro dos sites (Duplique / DSC) entram no mesmo endpoint, com o mesmo script de captura de UTMs em campos ocultos. Regra de atribuição: **com UTM → canal/campanha das UTMs** (visitante veio de anúncio/e-mail e converteu no site); **sem UTM → `canal=site`**, `campanha` = domínio/página do formulário. A marca segue a regra 4.1.1 (localização), não o site de origem
- **Caminho alternativo:** se a LP/site já entrega os leads no RD Station, o worker `sync_rd` os traz — desde que as UTMs estejam mapeadas em campos do contato no RD
- Gasto do Google Ads para CPL: Google Ads API em `ad_insights` (`plataforma=google`) — modelo híbrido conforme 8.3

### 5.5 Agendor (API v3, token) — worker `sync_agendor`, a cada 30 min
- `GET /v3/deals` (paginação) — título, funil, etapa, valor, responsável, status, datas
- `GET /v3/deals/{id}` para detalhe; pessoas/organizações vinculadas para telefone/email
- Detecção de mudança de etapa: comparação com snapshot anterior em `negocios` → gera evento `mudou_etapa`

**Funis mapeados (DEFINIDO — prints de 21/07/2026):**

*Funil Pré-Vendas:*
Contato Pré-Vendas Efetivados → Contato de Apresentação → Follow Up → Lead Qualificado → [Lead Sem Perfil = desqualificação comercial] → Reunião com Síndico/Conselho → Solicitação de Documentação → **Proposta Enviada** → AGO/AGE/AGI → Aguardando Documentação → Análise Documentação → Assinatura de Contrato

*Funil Vendas:*
Prospecção PAP/Eventos/Outbound → Contato Inicial → Follow Up do Contato → Solicitação de Documentação → Reunião com Síndico/Conselho → **Proposta Enviada** → AGO/AGE/AGI → Aguardando Documentação → Análise Documentação → Assinatura de Contrato

**IMPORTANTE — sem amarração canal × funil:** qualquer lead, de qualquer canal (inclusive qualificado pela Júlia), pode nascer em qualquer um dos dois funis. O sistema apenas registra o funil onde o negócio está (`negocios.funil`) e o disponibiliza como filtro no dash. Nenhuma regra de validação ou alerta de "funil errado".

**Regras derivadas (DEFINIDO):**
- `gerou_proposta = true` quando o negócio atinge (ou já passou por) a etapa **Proposta Enviada**, em qualquer dos funis; `valor_orcamento` = valor do negócio nessa etapa
- Desqualificação comercial: etapa **Lead Sem Perfil** (funil Pré-Vendas) → evento próprio, distinto do `ia_desqualificou` da Júlia — o dash separa "IA descartou" de "comercial descartou"
- Venda: etapa **Assinatura de Contrato** ou status `ganho` no Agendor (o que ocorrer primeiro dispara o evento `ganho`)
- **Migração entre funis (DEFINIDO):** um negócio pode migrar do funil Pré-Vendas para o de Vendas. O worker detecta mudança de `funil` no snapshot e gera evento `mudou_funil` (payload: funil_de → funil_para, etapa de chegada). O histórico do negócio permanece contínuo — mesma linha em `negocios`, mesmo `agendor_negocio_id`; métricas de tempo por etapa consideram a troca sem zerar a contagem
- Proposta/orçamento: valor do negócio preenchido → `gerou_proposta=true` + evento `valor_lancado`

---

## 6. Matching (unificação de identidade)

Ordem de resolução ao receber um lead/evento de qualquer fonte:

1. **Telefone normalizado** (E.164 BR) — testar variações com/sem 9º dígito (padrão já validado no DSC Cobrança)
2. **E-mail** (lowercase, trim) — chave principal para RD Station
3. **Nome fuzzy** (similaridade ≥ 0.85 via `pg_trgm`) — nunca resolve sozinho: gera registro em fila de revisão manual (`matching_pendente`) para confirmação humana
4. Sem match → cria lead novo

Regra de conflito: se duas fontes divergirem em dado pessoal (ex.: cidade), vence a fonte mais recente, mas o valor anterior fica preservado no `payload` do evento.

---

## 7. Workers — regras gerais

- Python 3.12, um processo por fonte, agendados via Railway cron
- **Idempotentes**: rodar duas vezes não duplica nada (constraint UNIQUE em `eventos` + upsert por chave natural)
- **Incrementais**: cada worker guarda `ultimo_sync` em tabela `sync_state` e busca só o delta
- Logs estruturados: leads novos, eventos gerados, matches por tipo, pendências de revisão
- Falha de uma fonte não derruba as outras

---

## 8. Carga inicial (arquivos da pasta do Projeto Claude)

Fluxo: arquivos brutos na pasta do Projeto → Claude (chat) trata, valida e gera CSVs no padrão abaixo → importer no Claude Code insere no banco.

### 8.1 Importação de leads de eventos presenciais (DEFINIDO — baseado no modelo real "Jornada Porter Presidente Prudente 2026")

Formato real das listas de inscritos: bloco de **metadados no topo** (nome do evento, data/hora, local, cidade) + colunas `Ordem de inscrição; Nº ingresso; Nome; Sobrenome; Email; Telefone`.

O importer `importers/evento_inscritos.py` aceita esse formato diretamente:
- **Metadados do cabeçalho** → `canal=evento`, `campanha` = nome do evento (normalizado, ex.: `Jornada_Porter_PresidentePrudente_Jun26`), `data_entrada` = data do evento, `origem_detalhe` = cidade/local do evento
- **Nome + Sobrenome** → concatenados em `leads.nome`
- **Deduplicação obrigatória**: mesma pessoa pode ter 2+ ingressos (caso real no modelo) → dedupe por telefone normalizado
- **⚠ Matching em eventos é TELEFONE-primeiro**: e-mail NÃO é único por pessoa nessas listas (casos reais: 3 familiares com o mesmo e-mail, casais compartilhando) — e-mail só como apoio, nunca como chave de dedupe/matching sozinho em `canal=evento`
- **Localização/marca**: a planilha não traz a cidade do participante (só a do evento). Fallback: **UF derivada do DDD do telefone** (DDD 47/48/49 → SC → Duplique; demais DDDs → DSC), gravada com flag `uf_derivada_por_ddd=true` (confiança menor; qualquer fonte posterior com cidade real sobrescreve)
- Telefones chegam em formatos variados ("(18) 99771-2982", "18-98111-6479") → mesma normalização E.164 do restante do sistema
- Colunas extras (ordem, nº ingresso) → preservadas no `payload`

CSV alternativo (padrão genérico, para listas fora desse formato):
```
nome;telefone;email;cidade;uf;profissao_funcao;canal;campanha;origem_detalhe;tipo_captura;data_entrada
```

### 8.2 Arquivos previstos para a primeira carga
1. Export de negócios do Agendor (CSV nativo deles) → `importers/agendor_historico.py`
2. Exports de leads Meta (os já tratados: base geral + maio/26)
3. Listas de leads de eventos presenciais (planilha padrão 8.1, `canal=evento`)
4. Base de contatos RD Station (export CSV)

### 8.3 Google Ads — modelo híbrido (DECIDIDO)

**Histórico (incluindo mês passado):** relatórios em planilha enviados pela Stella → `importers/google_ads_report.py` → upsert em `ad_insights` (`plataforma=google`), idempotente por (data, campanha, anúncio). Formato: export padrão do Google Ads (relatório de campanhas, CSV) com pelo menos dia, campanha, grupo de anúncios, anúncio/criativo, custo, impressões, cliques, conversões. **Entra na Fase 1** — a visão do mês passado fica disponível já na primeira carga.

**Futuro (dados correntes):** worker `sync_google` via **Google Ads API** (Fase 2), mesmo padrão do `sync_meta`: gasto diário por campanha/grupo/anúncio em `ad_insights` + leads de extensão de formulário se houver.

**Pré-requisitos da API do Google (responsabilidade de setup, Fase 2):**
1. Projeto no Google Cloud com OAuth2 (client_id/secret + refresh token)
2. Developer token solicitado no Google Ads (nível básico é suficiente para conta própria)
3. Variáveis: `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`, `GOOGLE_ADS_CUSTOMER_ID`

**Transição:** quando o worker da API entrar, o importer de planilha continua existindo como fallback (meses antigos, correções). A constraint UNIQUE em `ad_insights` garante que API e planilha nunca dupliquem o mesmo dia/anúncio.

---

## 9. Dashboard (Metabase) — painéis mínimos

**Painel 1 — Visão do momento (home)**
Leads no período · em conversa com IA · SQLs · negócios abertos por etapa · propostas em aberto (soma R$) · ganhos no mês (soma R$) · taxa de conversão ponta a ponta.

**Painel 2 — Aquisição**
Leads por canal · por campanha · por criativo (Meta) · CPL por campanha e por criativo (join com `ad_insights`) · leads por região (mapa/UF) · por profissão/função · por tipo_captura (form nativo × isca × clique WhatsApp).

**Painel 3 — Funil e IA**
Funil visual: capturado → IA iniciou → SQL → negócio criado → proposta → ganho · taxa de qualificação da Júlia · tempo médio de primeira resposta · comparativo de conversão com IA × sem IA.

**Painel 4 — Comercial e Tempos**
Negócios por consultor (quantidade, valor, taxa de ganho) · motivos de perda · valor médio de orçamento por canal de origem.

**Métricas de tempo (DEFINIDO — todas derivadas da tabela `eventos`, comparáveis por canal, campanha, consultor e marca):**
- **Tempo de conversão ponta a ponta:** captura do lead → assinatura/ganho (a métrica-mãe)
- **Tempo de pipeline:** criação do negócio no Agendor → fechamento (ganho ou perdido)
- **Tempo por etapa:** média e mediana de permanência em cada etapa dos dois funis (via `mudou_etapa`) — revela onde o funil trava
- **Tempo de primeira resposta da IA:** captura → `ia_iniciou_conversa` (mede a promessa dos "5 minutos" da Júlia)
- **Tempo de qualificação:** captura → `ia_qualificou`
- **Tempo SQL → negócio:** qualificação pela IA → criação do card no Agendor
- **Tempo proposta → decisão:** Proposta Enviada → ganho/perdido
- **Aging do pipeline (momento atual):** para negócios abertos, há quantos dias estão parados na etapa atual — card de alerta para os que excedem o limite (limite configurável por etapa, sugestão inicial: 2× a mediana histórica)

Nota: mediana é a medida principal (médias distorcem com outliers — um negócio parado 8 meses arrasta a média); a média aparece como secundária.

**Painel 5 — ROI**
ROI e ROAS por canal, por campanha e por criativo · custo por SQL e custo por venda (CAC) · receita atribuída × investimento no período · payback (meses de receita recorrente para cobrir o CAC) · ranking de campanhas por ROI · % de leads com atribuição incompleta (qualidade do rastreio).

**Fórmulas (definição travada):**
- `Investimento = ad_insights.gasto + custos_campanha.valor` (por canal/campanha/período)
- `Receita atribuída = Σ receita_para_roi dos negócios GANHOS cujo lead tem canal_entrada/campanha_entrada correspondente` (atribuição de **primeiro toque** como modelo oficial; a tabela `eventos` permite análise de multi-toque como visão secundária)
- `ROI = (Receita atribuída − Investimento) / Investimento`
- `ROAS = Receita atribuída / Investimento`
- `CAC = Investimento / vendas ganhas no período`
- `receita_para_roi` **(DEFINIDO)** = `mensalidade_media × 12` — horizonte fixo de 1 ano, mesmo sem dado de LTV real. A `mensalidade_media` **nasce pré-preenchida com o valor bruto do Agendor** (que é inconsistente — ora taxa, ora mensalidade) e o ROI é calculado normalmente com ela; enquanto o negócio ganho tiver `mensalidade_ajustada = false`, o dash exibe junto ao ROI o aviso **"⚠ Contém valores não ajustados — confira a mensalidade para ROI preciso"** e um card lista os negócios ganhos aguardando conferência. Ajustou/confirmou → flag vira true e o aviso some. Regra de edição: ajuste manual da mensalidade **não** é sobrescrito pelo sync do Agendor (o worker só pré-preenche quando `mensalidade_ajustada = false`).

**Filtros globais em todos os painéis:** período, marca (DSC/Duplique), canal, campanha, região/UF, consultor, status.

---

## 10. Registro de decisões (todas as pendências resolvidas — sign-off de Stella em 21/07/2026)

| # | Pendência | Fonte |
|---|---|---|
| 1 | ~~Nomes dos campos da Júlia no BotConversa~~ **RESOLVIDO: mapeamento completo na seção 5.2** (entrada: primeiro-nome, Email, canal-aquisicao, cargo-funcao, regiao, data-inscricao · saída: REGIAO, TEMPERATURA, PERFIL_CLIENTE, DATA/HORARIO_SOLICITADO, TELEFONE_DECISOR, RESUMO_CONVERSA, MOTIVO_NAO_QUAL · fluxos: SUCESSO/INSUCESSO/NAO_QUALIFICADO). Worker deve listar os campos via API na implementação para capturar a grafia exata | BotConversa |
| 2 | ~~Etapas do funil no Agendor~~ **RESOLVIDO (5.5): dois funis — Pré-Vendas e Vendas — ambos com etapa Proposta Enviada onde nasce o orçamento. Leads de qualquer canal podem entrar em qualquer funil (sem amarração). Negócio pode migrar de Pré-Vendas → Vendas (evento `mudou_funil`)** | Agendor |
| 3 | ~~Campos dos formulários nativos da Meta~~ **RESOLVIDO (5.1): Email, First Name, Phone Number, Form Name, "Onde Está Localizado O Seu Condomínio" (→ cidade/região), "Você É" (→ profissão/função)** | Meta |
| 4 | ~~Padrão de nomenclatura de campanhas~~ **RESOLVIDO/APROVADO: `MARCA_Canal_Objetivo_MesAno` (ex.: `DUP_Meta_FormNativo_Jul26`). Vale para campanhas novas; antigas mantêm o nome original na base** | Governança |
| 5 | ~~Google Ads entra na fase 1 ou fase 2?~~ **RESOLVIDO: modelo híbrido — histórico via planilhas da Stella (Fase 1, importer 8.3) + API do Google Ads para dados correntes (Fase 2, worker `sync_google`)** | Escopo |
| 6 | ~~RD Station: acesso à API?~~ **RESOLVIDO: app privado OAuth2 criado por Stella em 21/07/2026 (categoria Marketing, callback localhost). `RD_CLIENT_ID` e `RD_CLIENT_SECRET` armazenados nas variáveis do Railway. Resta apenas gerar o `RD_REFRESH_TOKEN` via fluxo de autorização — script na Fase 3. API Key pública também registrada (`RD_API_KEY`)** | RD |
| 7 | ~~Leads de eventos: planilha padrão~~ **RESOLVIDO: modelo real recebido (lista de inscritos Jornada Porter — metadados no topo + ordem/ingresso/nome/sobrenome/email/telefone). Importer especificado na 8.1 com dedupe por telefone, matching telefone-primeiro (e-mails compartilhados são comuns) e UF por DDD como fallback de marca** | Eventos |
| 8 | ~~LPs: destino dos leads~~ **RESOLVIDO: serão criadas LPs NOVAS já no padrão do sistema — formulário com POST direto para o endpoint `/api/lead` no Railway (caminho preferido da 5.4)** | LPs |
| 9 | ~~LPs: captura de UTMs~~ **RESOLVIDO: as LPs novas nascem com o script de captura de UTMs em campos ocultos (regra 3.5) embutido desde o primeiro dia — sem passivo de retrofit** | LPs |
| 12 | **Cadastros dos sites institucionais — INCLUÍDO (21/07): formulários dos sites entram no endpoint `/api/lead` com script de UTMs. Com UTM → atribui ao canal de origem; sem UTM → `canal=site` (novo valor na taxonomia). Requer embutir o snippet do form nos sites — mesma tarefa das LPs** | Site |
| 10 | ~~ROI — definição de receita~~ **RESOLVIDO: `mensalidade_media` nasce pré-preenchida com o valor bruto do Agendor e o ROI calcula com ela (× 12 meses fixos); aviso "valores não ajustados" no dash até alguém conferir/ajustar (flag `mensalidade_ajustada`). Ajuste manual nunca é sobrescrito pelo sync** | ROI |
| 11 | ~~ROI — custos manuais~~ **RESOLVIDO: Meta via API · Google via relatório enviado pela Stella (importer 8.3) · eventos e demais custos via lançamento manual com aviso de "custo pendente" no dash (4.5)** | ROI |

---

## 11. Variáveis de ambiente (Railway)

```
DATABASE_URL
META_ACCESS_TOKEN_DUP, META_AD_ACCOUNT_ID_DUP, META_FORM_IDS_DUP
META_ACCESS_TOKEN_DSC, META_AD_ACCOUNT_ID_DSC, META_FORM_IDS_DSC
BOTCONVERSA_API_KEY_DUP, BOTCONVERSA_API_KEY_DSC
RD_CLIENT_ID, RD_CLIENT_SECRET, RD_REFRESH_TOKEN, RD_API_KEY
AGENDOR_TOKEN
```

⚠️ Tokens **nunca** vão para o repositório — somente nas variáveis do Railway.

---

## 12. Fases de implementação sugeridas (Claude Code)

**Fase 1:** Postgres + schema + importers de carga inicial (Agendor histórico, leads Meta tratados, eventos, planilhas Google Ads) + worker Agendor + Metabase instalado → já responde "onde está cada lead, quanto tem em proposta e qual foi o desempenho do mês passado por canal".
**Fase 2:** worker Meta (leads + insights) + worker Google (API — requer setup de credenciais 8.3) + matching completo → atribuição por criativo e CPL/ROI correntes nas duas plataformas.
**Fase 3:** worker BotConversa + worker RD Station → funil completo com IA e e-mail.
**Fase 4:** refinamentos: fila de revisão de matching, alertas (lead parado em etapa X há N dias), painel custom com identidade DSC/Duplique (opcional).
