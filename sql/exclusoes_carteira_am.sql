-- Exclusoes administrativas globais da carteira Account Manager.
-- O contrato cadastrado deixa de compor o MRR Inicial e o MRR Evoluido ao vivo.
-- Periodos ja fechados exigem reabertura e novo fechamento para refletir a regra.

CREATE TABLE IF NOT EXISTS SUPERSET.COMISSOES.EXCLUSOES_CARTEIRA_AM (
    ID_CONTRATO   STRING         NOT NULL,
    SOLICITADO_POR STRING        NOT NULL,
    MOTIVO        STRING         NOT NULL,
    CREATED_BY    STRING         NOT NULL,
    CREATED_AT    TIMESTAMP_NTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
