---
name: trader-budget
description: >-
  O Gestor de Orçamento. Dimensiona cada posição ao seu orçamento antes de
  qualquer compra: guarda um caixa, limita o peso de cada ativo (o excesso vai
  para os outros), descarta fatias abaixo da ordem mínima e arredonda para
  usar cada real. Na B3: quantidades inteiras, lote padrão (100 ações) mais o
  fracionário (ticker + F), ordem limitada com folga sobre a cotação, valores
  em reais. Nos EUA: dólares fracionados no formato do place_stock_order da
  Alpaca. Grava as boletas propostas em trader/orders.json; nada é enviado.
  Use quando o usuário disser "tenho R$ 20 mil", "quanto compro de cada",
  "dividir meu dinheiro", "manter 10% em caixa", "nenhuma ação acima de 25%",
  "dimensionar", "I have $5,000", "size my trades", ou depois do /trader-copycat.
argument-hint: "[orçamento]"
---

# trader-budget

O Gestor de Orçamento transforma "copiar esta carteira" em "comprar
exatamente isto de cada ativo", dentro de regras definidas uma vez. Ele só
escreve propostas: o `/trader-risk` confere e o `/trader-broker` pede o seu
sim para cada uma.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                             # trader/targets.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --budget 20000 --write      # grava trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --weights PETR4=30,VALE3=25,ITUB4=20,BOVA11=15,MXRF11=10 --budget 20000
python3 "${CLAUDE_SKILL_DIR}/size.py" --market us --weights AAPL=22.04,AXP=17.14 --budget 5000 --json
```

## O que lê e grava

| arquivo | o quê |
| --- | --- |
| `trader/config.json` | as regras (`config_br.example.json` para a B3, `config.example.json` para os EUA) |
| `trader/targets.json` | os pesos a copiar, do trader-copycat |
| `trader/prices.json` | cotações (o trader-alerts grava); **obrigatório na B3** |
| `trader/orders.json` | as boletas propostas, com `--write` |

`b3.py` e `b3_ativos.json` nesta pasta guardam as regras da B3 (tipo de ativo,
lote, calendário); `asset_types` e `round_lots` no config corrigem qualquer ativo.

## Passo 1: as regras, uma vez

Se `trader/config.json` não existe, copie o exemplo do mercado e pergunte cada
valor em palavras simples:

- **market**: `"br"` (B3) ou `"us"`. Uma pasta de projeto por mercado.
- **budget**: quanto dinheiro é para isto. Só o que pode perder.
- **cash_buffer_pct**: quanto fica em caixa (padrão 10).
- **max_position_pct**: o máximo de um ativo, em % do orçamento (padrão 25).
- **min_order / max_order** (`min_order_brl`, `max_order_brl` na B3;
  `min_order_usd`, `max_order_usd` nos EUA): a menor e a maior boleta.
- **limit_buffer_pct** (B3): folga do preço limite sobre a cotação (padrão 0,5%).
- **blocked**: tickers que o usuário nunca quer ter.
- EUA: **fractional** (Alpaca compra fração) e **paper** true até ver funcionar.

## Passo 2: dimensionar

A conta, em ordem: o caixa sai primeiro; os pesos voltam a somar 100 entre os
ativos que ficaram; quem passa do teto fica no teto e o excesso é dividido
entre os outros, até ninguém passar; uma fatia abaixo da ordem mínima é
descartada e o peso dela redistribuído; o arredondamento sobra para o maior
ativo fora do teto, para nada ficar parado por acaso.

**Na B3**: não existe compra por valor. A ferramenta usa o preço limite
(cotação + folga) para calcular quantas ações inteiras cabem, sem nunca passar
do orçamento, e divide a quantidade em lote padrão + fracionário: 132 PETR4
viram 100 PETR4 + 32 PETR4F. Ações e units têm lote de 100; FIIs, ETFs e BDRs,
de 1 (sem fracionário). Um "11" fora da lista conhecida é tratado como FII e
marcado "tipo deduzido, confirme": confirme com o usuário.

## Passo 3: mostrar ao usuário

Mostre a tabela: ticker, tipo, peso, valor, preço limite, quantidade, lote,
quem bateu no teto, o caixa e a sobra. Diga de onde vêm os pesos e a idade
deles (CDA de um mês, 13F de até 45 dias). Depois passe para o `/trader-risk`.

## Exemplo (B3)

R$ 20.000, caixa de 10%, teto de 25%, PETR4 30 / VALE3 25 / ITUB4 20 / BOVA11
15 / MXRF11 10, cotações 37,42 / 58,10 / 36,05 / 141,20 / 9,71:

```
PETR4   ação   30.00%  R$ 4.964,52   R$ 37,61    132   100  no teto de 25%
VALE3   ação   25.00%  R$ 4.612,81   R$ 58,39     79   100
ITUB4   ação   20.00%  R$ 3.695,46   R$ 36,23    102   100
BOVA11  ETF    15.00%  R$ 2.838,20  R$ 141,91     20     1
MXRF11  FII    10.00%  R$ 1.883,68    R$ 9,76    193     1  tipo deduzido, confirme
  COMPRA 100 PETR4 + 32 PETR4F, 79 VALE3F, 100 ITUB4 + 2 ITUB4F, 20 BOVA11, 193 MXRF11
```

## Exemplo (EUA)

13F da Berkshire do 2º tri de 2026, top 5 (30,67 / 23,85 / 17,56 / 15,11 /
12,80), US$ 5.000, caixa 10%, teto 25%: AAPL US$ 1.250 (no teto), AXP US$
1.119, GOOGL US$ 823, KO US$ 708, BAC US$ 600, US$ 500 em caixa. A primeira
ordem é `{"symbol": "AAPL", "side": "buy", "notional": "1250", "type":
"market", "time_in_force": "day"}`.

## Regras

- Só propostas. Esta skill nunca chama corretora.
- Nunca dimensione um dinheiro que o usuário não disse que é para isto.
- Todo número vem do config, dos pesos ou das cotações. Nada é chutado.
- Sem projeções: nunca diga quanto as posições vão valer ou render.
- Na B3 (e nos EUA com ações inteiras), preço real em `trader/prices.json`;
  nunca invente uma cotação.

## O que ele nunca faz

Nunca envia, aprova ou agenda uma ordem, nunca aumenta um limite sozinho e
nunca dimensiona opções, margem ou venda a descoberto.

## Segurança

- Educação e ferramenta, não recomendação de investimento (not financial advice).
- B3: nenhuma skill envia ordem. Cada boleta só vai para o seu home broker
  depois que o `/trader-risk` aprovou aquela boleta hoje e você disse "sim" a
  ela no chat; quem digita e envia é você.
- EUA: só o `/trader-broker` leva a uma ordem, depois do `/trader-risk`, do seu
  "yes" explícito para aquela ordem e do clique em Allow once (ferramenta da
  corretora em "Needs approval", nunca "Always allow"). Paper trading é o
  padrão (`"paper": true`); ir para conta real é decisão sua.
- Sem opções, margem, venda a descoberto ou alavancagem, a menos que o config
  permita e você confirme.
- Chaves (Alpaca, `BRAPI_TOKEN`) ficam em variáveis de ambiente ou no config do
  Claude Desktop, nunca no chat.
