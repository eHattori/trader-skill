---
name: trader-risk
description: >-
  O Gestor de Risco. Confere cada boleta proposta contra os seus limites antes
  de ela chegar à corretora e bloqueia o que passa deles: tickers bloqueados,
  tamanho máximo e mínimo, peso máximo depois da execução, caixa mínimo,
  margem, venda a descoberto, opções, duplicadas e limite diário. Na B3
  também confere lote padrão e fracionário, tipo e validade da ordem, preço
  limite longe da cotação, horário do pregão, day trade (IR de 20%) e vendas
  de ações acima de R$ 20 mil no mês (fim da isenção). Grava os veredictos
  para o /trader-broker só mostrar boletas aprovadas. Use quando o usuário
  disser "confere minhas ordens", "isso é seguro?", "passa nas minhas
  regras?", "checagem de risco", "risk check", e sempre antes do /trader-broker.
argument-hint: "[caminho do orders.json]"
---

# trader-risk

O Gestor de Risco é a porta entre a proposta e a corretora. Toda boleta
escrita pelo trader-budget, trader-rebalance ou trader-tax passa por ele. Um
BLOQ é definitivo para aquela boleta: ela não vai para o sim do usuário nem
para a corretora.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"             # arquivos em trader/; grava trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write  # só olhar, sem registrar
```

## O que lê e grava

| arquivo | o quê |
| --- | --- |
| `trader/orders.json` | as boletas propostas (o mercado vem do arquivo ou do ticker) |
| `trader/config.json` | os limites (`config_br.example.json` / `config.example.json` no trader-budget) |
| `trader/portfolio.json` | caixa e posições; se não existe, uma conta nova com o orçamento |
| `trader/prices.json` | cotações, para valorar posições e boletas por quantidade |
| `trader/state/broker.json` | o que foi enviado hoje e no mês (duplicadas, limite diário, day trade, isenção) |
| `trader/state/risk.json` | os veredictos, com a impressão digital de cada boleta exata |

## As checagens

As boletas são conferidas na ordem do arquivo, como se cada aprovada tivesse
executado, então um lote que passa boleta a boleta mas quebra uma regra junto
é pego.

| checagem | bloqueia quando |
| --- | --- |
| formato | sem ticker, lado que não é compra nem venda, quantidade e valor juntos ou nenhum, limitada sem preço |
| ativo | símbolo de opção com `allow_options` falso; na B3, algo que não é ação, unit, FII, ETF ou BDR; nos EUA, algo que não parece ação ou ETF americano |
| bloqueado | o ticker está na lista `blocked` |
| tamanho | abaixo da ordem mínima ou acima da máxima |
| posição | o ativo passaria do `max_position_pct` da conta |
| caixa | a compra deixaria menos que o caixa mínimo, ou exigiria margem |
| descoberto | venda maior que a posição (`allow_short` falso) |
| duplicada | mesmo ticker e lado duas vezes no lote, ou já enviado hoje |
| limite diário | mais de `max_orders_per_day` enviadas hoje |
| **B3: lote** | quantidade não inteira; lote padrão que não é múltiplo do lote (100 para ações e units); fracionário fora de 1 a 99; fracionário de ativo com lote 1 |
| **B3: tipo** | algo além de mercado, limitada ou stop limitada; validade fora de dia, até cancelar, executa ou cancela, tudo ou nada; ordem por valor (notional) |

Avisos não bloqueiam, mas diga ao usuário. Na B3: boleta executada à mão no
home broker; fora do horário do pregão (a ordem espera a abertura); limite
mais de 5% longe da última cotação; **day trade** (vender hoje o que comprou
hoje ou o contrário: IR de 20%, sem isenção); **vendas de ações no mês acima
de R$ 20.000** (o lucro comum do mês passa a pagar 15%). Nos EUA: conta real,
número enviado como número em vez de texto, ordem avançada.

## Passos

1. Garanta `trader/prices.json` recente (trader-alerts: `alerts.py quote --holdings --write`).
2. Rode `check.py`. Código 0 = tudo aprovado, 1 = alguma bloqueada.
3. Conte o resultado em palavras simples, boleta por boleta. Para um BLOQ, dê o
   motivo e a correção (outro valor, outro ativo, ou uma regra que o usuário
   pode decidir mudar). Nunca mude um limite você mesmo.
4. Se as boletas mudarem de qualquer jeito, rode de novo. O trader-broker liga
   cada boleta ao veredicto pela impressão digital: uma boleta editada só fica
   pronta depois de passar de novo, e um veredicto de ontem não vale hoje.

## Exemplos

B3: as boletas do exemplo do trader-budget (100 PETR4 + 32 PETR4F, 79 VALE3F,
100 ITUB4 + 2 ITUB4F, 20 BOVA11, 193 MXRF11) numa conta nova de R$ 20.000:
`7 aprovadas, 0 bloqueadas. Caixa depois das aprovadas: R$ 2.005,33.` Uma
boleta de 150 PETR4 é bloqueada (lote de 100: use PETR4 100 + PETR4F 50) e
uma de 150 PETR4F também (fracionário vai de 1 a 99).

EUA: as cinco compras do exemplo (AAPL US$ 1.250, AXP 1.119, GOOGL 823, KO
708, BAC 600) numa conta paper de US$ 5.000 passam; AAPL fica exatamente no
teto de 25%, o que é permitido. Mais US$ 100 de AAPL seriam bloqueados três
vezes: caixa mínimo, teto e duplicada.

## O que ele nunca faz

Nunca envia ordem, nunca edita uma boleta para ela passar, nunca afrouxa um
limite e nunca trata uma aprovação como o sim do usuário. Aprovado só quer
dizer que a boleta pode ser mostrada a ele.

## Segurança

- Educação e ferramenta, não recomendação de investimento (not financial
  advice). Uma aprovação é conferência de regras, não recomendação.
- B3: nenhuma skill envia ordem. Cada boleta só vai para o seu home broker
  depois de aprovada aqui hoje e do seu "sim" no chat; quem digita é você.
- EUA: só o `/trader-broker` leva a uma ordem, depois desta aprovação, do seu
  "yes" explícito e do clique em Allow once (ferramenta da corretora em "Needs
  approval", nunca "Always allow"). Paper trading é o padrão.
- Sem opções, margem, venda a descoberto ou alavancagem, a menos que o config
  permita e você confirme.
- Chaves ficam em variáveis de ambiente ou no config do Claude Desktop, nunca no chat.
