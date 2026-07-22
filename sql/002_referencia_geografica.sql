-- Tabelas de referência geográfica usadas na derivação de marca (regra 4.1.1 da spec)

CREATE TABLE municipios_ibge (
  id                SERIAL PRIMARY KEY,
  nome              TEXT NOT NULL,
  nome_normalizado  TEXT NOT NULL,  -- lowercase, sem acento — chave de busca
  uf                CHAR(2) NOT NULL
);
CREATE INDEX ON municipios_ibge (nome_normalizado);
CREATE INDEX ON municipios_ibge (uf);

CREATE TABLE ddd_uf (
  ddd  SMALLINT PRIMARY KEY,
  uf   CHAR(2) NOT NULL
);
