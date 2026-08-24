-- Snapshot de fechamento de comissões
-- Escopo: por (ano, mês, equipe). Congela o resultado por pessoa + a composição
-- (realizado/deals, GD, cancelamentos, booking extra, ajustes). Vale de abr/2026 em diante.
-- Imutável: refechar gera nova VERSAO; a anterior vira STATUS='SUBSTITUIDO'.

CREATE TABLE IF NOT EXISTS SUPERSET.COMISSOES.FECHAMENTOS (
    FECHAMENTO_ID    STRING        NOT NULL,   -- ex: '2026-06-Governo-v1'
    ANO              NUMBER(4,0)   NOT NULL,
    MES              NUMBER(2,0)   NOT NULL,
    EQUIPE           STRING        NOT NULL,
    VERSAO           NUMBER        NOT NULL,    -- 1, 2, ... a cada refechamento
    STATUS           STRING        NOT NULL,    -- 'ATIVO' | 'SUBSTITUIDO'
    DATA_FECHAMENTO  TIMESTAMP_NTZ NOT NULL,
    USUARIO          STRING,
    N_PESSOAS        NUMBER,
    OBS              STRING
);

CREATE TABLE IF NOT EXISTS SUPERSET.COMISSOES.COMISSOES_FECHADAS (
    FECHAMENTO_ID    STRING        NOT NULL,
    ANO              NUMBER(4,0)   NOT NULL,
    MES              NUMBER(2,0)   NOT NULL,
    EQUIPE           STRING        NOT NULL,
    EMAIL            STRING        NOT NULL,
    CARGO            STRING,
    TOTAL            FLOAT,                     -- extraído p/ consulta rápida (fonte: DADOS)
    DADOS            VARIANT       NOT NULL,    -- resultado inteiro do calcular_comissao
    DATA_FECHAMENTO  TIMESTAMP_NTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS SUPERSET.COMISSOES.COMPOSICAO_FECHADA (
    FECHAMENTO_ID    STRING        NOT NULL,
    ANO              NUMBER(4,0)   NOT NULL,
    MES              NUMBER(2,0)   NOT NULL,
    EQUIPE           STRING        NOT NULL,
    EMAIL            STRING        NOT NULL,
    TIPO             STRING        NOT NULL,    -- 'REALIZADO' | 'GD' | 'CANCELAMENTO' | 'BOOKING_EXTRA' | 'AJUSTE'
    ORDEM            NUMBER,
    LINHA            VARIANT       NOT NULL     -- a linha original como JSON
);
