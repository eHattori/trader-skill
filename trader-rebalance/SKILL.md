---
name: trader-rebalance
description: >-
  O Rebalanceador. Traz a carteira de volta aos pesos-alvo quando ela se
  afasta: valora cada posição a preço atual, calcula o desvio de cada ativo em
  pontos percentuais, opera só quem saiu da banda (padrão 5 pontos), mantém o
  caixa e o teto por ativo, pula boletas pequenas, põe vendas antes das
  compras e grava as propostas em trader/orders.json. Na B3: quantidades
  inteiras, lote padrão mais fracionário, ordens limitadas, reais, e aviso
  quando as vendas de ações do mês passam de R$ 20 mil (fim da isenção de
  IR). Use quando o usuário disser "rebalancear", "minha carteira desviou",
  "voltar aos pesos", "coloquei mais dinheiro", "a nova CDA mudou os pesos",
  "estou acima do peso em", "rebalance", ou todo mês depois do /trader-copycat.
argument-hint: "[banda em pontos]"
---

# trader-rebalance

O Rebalanceador mantém a carteira parecida com o plano. Preços andam,
dinheiro novo entra e uma CDA ou 13F novo muda os pesos; esta skill acha os
ativos que se afastaram demais e propõe as operações que os trazem de volta.
Só escreve propostas: o `/trader-risk` confere e o `/trader-broker` pede o
sim do usuário para cada uma.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/rebalance.py"                    # a tabela de desvios, sem gravar nada
python3 "${CLAUDE_SKILL_DIR}/rebalance.py" --band 5 --write   # propostas -> trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/rebalance.py" --sell-untracked   # também vende o que não está nos alvos
python3 "${CLAUDE_SKILL_DIR}/rebalance.py" --json
```

O mercado vem de `"market"` no config, ou do `targets.json`, ou dos tickers.

## O que lê e grava

| arquivo | o quê |
| --- | --- |
| `trader/portfolio.json` | caixa e posições |
| `trader/prices.json` | preço de cada posição e de cada alvo (o trader-alerts grava) |
| `trader/targets.json` | os pesos-alvo (o trader-copycat grava) |
| `trader/config.json` | caixa, teto, boleta mínima e máxima, `rebalance_band_pct`, `limit_buffer_pct` |
| `trader/orders.json` | as propostas, com `--write`, vendas primeiro |

## Como decide

- **Valor da conta** = caixa + cada posição a preço atual.
- **Alvos**: os pesos sobre a parte em ações (conta menos o caixa), nenhum
  acima de `max_position_pct` da conta; o excesso é redistribuído como no
  trader-budget, para um ativo no teto não ser recomprado acima dele todo mês.
- **Desvio** = % atual da conta menos % alvo.
- **Banda**: só opera quem desviou MAIS que a banda; a operação leva o ativo
  de volta ao alvo inteiro. Banda pequena = mais operações e mais custo; banda
  larga = menos.
- **Vendas primeiro**, depois compras. As compras só gastam o caixa acima do
  mínimo; se não der, todas encolhem na mesma proporção.
- Boletas abaixo da mínima são puladas; acima da máxima, cortadas, com aviso
  para rodar de novo depois de executar.
- Posições fora dos alvos ficam como estão e são listadas, a menos que o
  usuário peça `--sell-untracked`.
- **B3**: ações inteiras, cada boleta dividida em lote padrão e fracionário,
  limitada com folga (`limit_buffer_pct`, compra acima e venda abaixo da
  cotação), validade do dia; se as vendas de ações passarem de R$ 20.000, o
  relatório avisa que o lucro do mês deixa de ser isento.

## Passos

1. Atualize as cotações: trader-alerts `alerts.py quote --holdings --write`.
2. Rode `rebalance.py` e conte a tabela em palavras simples: quem está acima
   ou abaixo, quantos pontos e o que seria operado.
3. Antes de qualquer venda, rode o trader-tax: na B3, `ir_br.py apurar` do mês
   com a venda somada (isenção de R$ 20 mil, imposto de 15%); nos EUA,
   `lots.py sell TICKER QTD`. Vender um ganho pode significar imposto.
4. Se o usuário quiser as operações: `rebalance.py --write`, depois
   `/trader-risk`, depois `/trader-broker`, um sim por boleta.

## Exemplo (B3)

Alvos PETR4 40 / VALE3 40 / BOVA11 20; carteira com 500 PETR4, 80 VALE3, 20
BOVA11 e R$ 500 em caixa; banda de 3 pontos. PETR4 está muito acima do alvo:
venda limitada de 100 PETR4 + 60 PETR4F (cortada no máximo de R$ 6.000 por
boleta, com aviso para rodar de novo); VALE3 e BOVA11 abaixo: compra de 22
VALE3F e 17 BOVA11, encolhidas a 65% porque o caixa livre acima do mínimo não
cobre tudo.

## Exemplo (EUA)

A carteira comprada em 13/10/2026 (AAPL US$ 1.250 no teto, AXP 1.119, GOOGL
823, KO 708, BAC 600, US$ 500 em caixa) está nos alvos: nada fora da banda.
Com mais US$ 2.000 em caixa, AAPL fica 7,1 pontos e AXP 6,4 abaixo do alvo,
fora da banda de 5: propõe comprar US$ 499 de AAPL e US$ 446 de AXP.

## O que ele nunca faz

Nunca envia ordem, nunca opera dentro da banda para correr atrás de
diferenças pequenas, nunca vende o que está fora dos alvos sem pedido e nunca
diz que rebalancear vai melhorar o retorno.

## Segurança

- Educação e ferramenta, não recomendação de investimento (not financial
  advice). Um rebalanceamento segue os alvos do próprio usuário, não uma previsão.
- B3: nenhuma skill envia ordem. Cada boleta só vai para o seu home broker
  depois do `/trader-risk` e do seu "sim" no chat; quem digita é você.
- EUA: só o `/trader-broker` leva a uma ordem, depois do `/trader-risk`, do seu
  "yes" explícito e do clique em Allow once (ferramenta em "Needs approval",
  nunca "Always allow"). Paper trading é o padrão (`"paper": true`).
- Sem opções, margem, venda a descoberto ou alavancagem, a menos que o config
  permita e você confirme.
- Chaves ficam em variáveis de ambiente ou no config do Claude Desktop, nunca no chat.
