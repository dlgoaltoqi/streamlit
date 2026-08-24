# Cola de apresentação — Painel de Comissões

Roteiro de respostas para apresentação ao vivo (não scriptada). Uma frase-síntese
por pergunta + detalhes para quando puxarem o fio.

## Para que ele é útil?

**Síntese:** "É a fonte oficial e transparente da comissão variável: cada pessoa
vê quanto vai receber no mês e — principalmente — por quê."

- Substitui a Calculadora de Comissões no Excel: mesmas regras, sem planilha
  compartilhada, sem versão desencontrada, sem fórmula quebrada por acidente.
- Cobre todos os modelos: MRR (Ares/B2B/Farmer/FSB), Saving (patamares),
  GD (Opps), Governo (dois eixos + ajuste trimestral) e recuperação de
  cancelamentos.

## O que ele ajuda?

- **Vendedor:** elimina o "de onde veio esse número" — cada card tem a fórmula
  embaixo, e a Composição do Realizado lista deal a deal com link para o HubSpot.
- **Gestor:** visão Minha Equipe com todos os consultores, totais e exportação.
- **Admin/financeiro:** exportação por equipe pronta para folha e fechamento
  congelado do mês.
- **Todos:** menos contestação e menos chamados — a pessoa confere sozinha.

## O que ele responde?

- "Quanto vou receber este mês e como chegou nesse valor?"
- "Quais negócios contaram no meu realizado? Por que aquele deal não entrou?"
  (ex.: deal ≥ 400k, item sem MRR)
- "Quanto falta para o próximo acelerador / patamar / OTE tier 2?" — os cards
  mostram o próximo degrau
- "Bati o trimestre? Quanto de bônus?"
- "Quanto recebi nos meses anteriores?" (histórico + meses fechados congelados)

## O que ele possibilita?

- **Autonomia** do vendedor e do gestor — consulta a qualquer hora, dado do dia.
- **Administração sem depender de TI:** metas, parâmetros, OTEs, multiplicadores,
  patamares, overrides e as regras do cálculo (tela Configurações, com vigência
  e auditoria de quem alterou o quê) — tudo por telas.
- **Fechamento oficial:** ao fechar o mês, o resultado congela (snapshot
  imutável); o pago não muda retroativamente mesmo que os dados mudem depois.
- **Suporte com "Visualizar como":** admin enxerga exatamente o que qualquer
  pessoa vê.

## O que tem de diferente do painel do Paulo (Revenue Intelligence)?

**Síntese:** "São complementares: o Revenue Intelligence responde *como está a
receita da empresa*; este responde *quanto cada pessoa recebe e por quê*."

- **Nível de visão:** o RI é agregado — Net MRR, growth, churn, forecast,
  atingimento por pipeline/vertical, safra. Este é **individual**: pessoa a
  pessoa, com RLS (cada consultor vê só a si; gestor, só sua equipe).
- **Regra embutida:** o RI mostra o resultado; este aplica a **política de
  remuneração** em cima dele — cliffs, aceleradores, tiers de OTE, patamares
  Saving, ponderações do Governo, bônus trimestral. Nenhum dashboard analítico
  faz essa conta.
- **Oficialidade:** o RI é foto viva com forecast; este tem **fechamento com
  valor congelado** — dimensão de folha de pagamento, não de análise.
- **Eles conversam:** o Painel de Comissões consome dados do próprio Revenue
  Intelligence (as metas de Opps do GD vêm de lá).

⚠️ **Aviso útil na apresentação:** os números dos dois painéis **não batem de
propósito** — o RI trabalha Net MRR (desconta churn/retração) e visões por
pipeline; a comissão usa o realizado individual da regra de cada equipe (Farmer
conta New+Expansão; deals ≥ 400k saem por padrão; GD conta Opps; Governo conta
Booking/ARR). Não deixe alguém tentar conciliar os valores ao vivo.

## O que NÃO é para fazer?

- Não é ferramenta de análise de vendas/pipeline — para isso, o BI.
- **Não se corrige venda aqui:** deal errado (valor, forma de pagamento, dono)
  corrige-se no HubSpot — o painel só reflete a origem.
- Não tratar mês aberto como valor final: até o fechamento o número é parcial.
  O oficial é o mês fechado (selo 🔒).
- Não usar exportação de mês aberto como folha.
- Admins: não alterar parâmetros/configurações sem alinhamento — mexe no
  pagamento do mês aberto na hora (tudo auditado, com nome e data).

## Quais as limitações?

- **A qualidade é a da origem:** o cálculo roda em cima do HubSpot/Snowflake;
  venda mal cadastrada = comissão errada (correção na origem).
- **Mês corrente é sempre parcial** até o fechamento.
- **Cache de até ~50 min:** alteração admin aparece na hora para quem salvou;
  outro usuário pode ver dado de até 50 min atrás — "↻ Recalcular" força.
- **Cobertura:** VPs e Atingimento de Meta fora do escopo por ora; histórico
  começa em abril/2026.
- **Primeira carga do dia é mais lenta** (aquecimento de cache); depois voa.
- **Sem estorno automático:** o ajuste trimestral só paga diferença positiva —
  regra de negócio, não defeito.

## O que depende dos usuários?

- **Vendedores:** cadastrar a venda certa no HubSpot — forma de pagamento,
  parcelas, categoria do item, vertical e proprietário são os campos que o
  cálculo usa.
- **Admin:** manter cadastros no prazo — metas do mês, parâmetros ("copiar mês
  anterior"), OTEs por cargo, multiplicadores, acessos (RLS) de quem entra/sai,
  marcar deals ≥ 400k pagos, e **fechar o mês** na época certa (sem fechamento
  não existe valor oficial congelado).
- **Todos:** divergência não se discute no grito — abre-se a Composição do
  Realizado, confere-se o deal; se persistir, pede-se recálculo/correção pelo
  canal combinado.
