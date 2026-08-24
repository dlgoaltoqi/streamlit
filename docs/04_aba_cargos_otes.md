# Aba: Cargos e OTEs

## Contexto

OTE = **On-Target Earnings** — a comissão mensal que o vendedor recebe se atingir 100% da meta.
Esta aba define o OTE de cada cargo para cada mês. É preenchida manualmente pelo administrador.

Não há fonte de dados externa — tudo é cadastrado no app.

## Estrutura

| Coluna | Nome | Tipo | Descrição |
|--------|------|------|-----------|
| A | Ano | int | Ano de referência |
| B | Mês | int | Mês de referência (número) |
| C | Cargo | string | Nome do cargo |
| D | OTE | decimal | Valor do OTE mensal para esse cargo/mês |

- Sem fórmulas — dados puros
- Chave única: `Ano + Mês + Cargo`
- Um cargo pode não ter OTE preenchido (ex: Account Executive B2G Jr/Pl em abr/mai 2026)

## Lista de Cargos (referência maio/2026)

| Cargo |
|-------|
| Account Executive Jr |
| Account Executive Pl |
| Account Executive Sr |
| Inside Sales Jr |
| Inside Sales Pl |
| Inside Sales Sr |
| Farmer Jr |
| Farmer Pl |
| Farmer Sr |
| Sales Development Representative (SDR) I |
| Sales Development Representative (SDR) II |
| Inside Sales B2G Jr |
| Inside Sales B2G Pl |
| Inside Sales B2G Sr |
| Key Account B2G I |
| Key Account B2G II |
| Key Account B2G Sr |
| Key Account II |
| Key Account Corporate B2G Sr |
| Account Executive B2G Jr |
| Account Executive B2G Pl |
| Account Executive B2G Sr |
| Technical Pre-Sales Engineer |
| Customer Success Saver Analyst Jr |
| Customer Success Saver Analyst Pl |
| Customer Success Saver Analyst Sr |
| Customer Success Saver Specialist |
| Customer Success Renewals Coordinator |
| Sales Manager B2g |
| Demand Generation Coordinator |
| Sales Coordinator B2B - E |
| Sales Coordinator B2B - C |
| Sales Coordinator Fsb |
| Sales Manager Fsb |

> A lista de cargos pode mudar mês a mês — novos cargos são adicionados e outros podem sumir.
> Entre abril e maio/2026, por exemplo, foram adicionados: *Sales Coordinator B2B - C*, *Key Account B2G Sr*, *Key Account II*.

## Requisitos da Página de Administração

### Funcionalidades

1. **Listar** os cargos e OTEs do mês selecionado
2. **Cadastrar** novo cargo/OTE para um mês
3. **Editar** OTE de um cargo existente
4. **Excluir** cargo de um mês
5. **Copiar mês anterior** — duplica todos os registros do mês anterior para o mês selecionado, permitindo ajustes pontuais sem redigitar tudo

### Comportamento do "Copiar Mês Anterior"

- Ao clicar, copia todos os pares `Cargo + OTE` do mês imediatamente anterior para o mês atual
- Se já existirem registros no mês destino, exibir aviso: *"Já existem registros para este mês. Deseja sobrescrever ou mesclar?"*
  - **Sobrescrever:** apaga tudo do mês destino e copia do anterior
  - **Mesclar:** adiciona apenas os cargos que ainda não existem no mês destino
- Após a cópia, o usuário edita os OTEs que mudaram

### Armazenamento

Tabela Snowflake sugerida: `SUPERSET.COMISSOES.CARGOS_OTES`

```sql
CREATE TABLE SUPERSET.COMISSOES.CARGOS_OTES (
    ANO      INT            NOT NULL,
    MES      INT            NOT NULL,
    CARGO    VARCHAR(200)   NOT NULL,
    OTE      DECIMAL(12, 2),
    PRIMARY KEY (ANO, MES, CARGO)
);
```

## Uso nas Comissões

O OTE de cada cargo é usado para:
- Calcular a comissão esperada (base de cálculo)
- Determinar aceleradores (% do OTE pago em função do % de atingimento da meta)

A ligação com o vendedor individual é feita na aba **Metas**, que associa cada pessoa a um cargo.
