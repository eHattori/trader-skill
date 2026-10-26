---
name: trader-alerts
description: >-
  Alertas de Preço. Toca quando um preço-alvo, um stop ou a abertura do
  pregão acontece: regras acima / abaixo / stop, variação percentual sobre o
  fechamento anterior e abertura do mercado, cada uma tocando uma vez. Na B3:
  cotações da brapi.dev (API v2, chave em BRAPI_TOKEN) com o Yahoo (PETR4.SA)
  como reserva, calendário de pregões de 2026 publicado pela B3 (2027
  provisório) e o horário do mercado à vista, que muda com o horário de verão
  dos EUA. Nos EUA: Yahoo e o calendário da NYSE. Grava trader/prices.json
  para as outras skills. Use quando o usuário disser "me avisa quando",
  "se PETR4 passar de", "coloca um stop", "a bolsa está aberta?", "que horas
  abre a B3", "atualiza as cotações", "alert me when", "is the market open".
argument-hint: "[ticker] [preço]"
---

# trader-alerts

Os Alertas olham os números para o usuário não precisar olhar. Um alerta é
informação, nunca ordem: quando um stop toca, nada é vendido. Se o usuário
quiser agir, o caminho normal roda (dimensionar, risco, o sim dele).

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock --market br              # B3 aberta ou fechada, próxima abertura
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock --market us              # NYSE
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote PETR4 VALE3 --write      # -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write       # tickers da carteira e dos alvos
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol PETR4 --above 42
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol VALE3 --stop 52 --note "meu stop"
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol ITUB4 --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell --market br
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                          # código 0 = algo tocou
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset petr4-above-42
```

Sem `--market`, vale o `"market"` de `trader/config.json` (padrão `us`).

## O que lê e grava

| arquivo | o quê |
| --- | --- |
| `trader/alerts.json` | as regras (`alerts.example.json` nesta pasta) |
| `trader/state/alerts.json` | quais regras tocaram e quando, para cada uma tocar uma vez |
| `trader/prices.json` | as últimas cotações, para trader-budget, trader-risk, trader-tax e trader-rebalance (tickers da B3 sem o `.SA`) |

## Tipos de regra

| tipo | toca quando | toca de novo |
| --- | --- | --- |
| `above` | preço igual ou acima de `price` | depois do `reset`, ou sozinho com `"rearm": true` quando o preço volta |
| `below` / `stop` | preço igual ou abaixo de `price` | igual |
| `pct_move` | variou `pct`% sobre o fechamento anterior (ou `ref`), `direction` up ou down opcional | no máximo uma vez por dia |
| `opening_bell` | o mercado abriu (`"market": "br"` para a B3) | uma vez por pregão |

## Cotações

- **B3, brapi.dev** (padrão): `https://brapi.dev/api/v2/stocks/quote?symbols=PETR4`,
  uma requisição por ticker. A chave vem da variável de ambiente `BRAPI_TOKEN`
  ou, se ela não existir, da primeira linha de `~/.config/trader-skill/brapi_token`
  (crie com `chmod 600`). É enviada no cabeçalho `Authorization: Bearer`, nunca
  na URL. Nunca peça a chave no chat; se o usuário colar uma, diga para gerar
  outra no painel da brapi. Sem chave, só os tickers de teste respondem (PETR4, VALE3,
  ITUB4, MGLU3, MXRF11, HGLG11). O plano gratuito tem cerca de 15 mil
  requisições por mês, uma por vez, cotação com uns 30 minutos de atraso; os
  planos pagos liberam proventos, fundamentos e histórico longo. Ticker
  renomeado (`changed`) é avisado.
- **B3, Yahoo** (reserva automática se a brapi falhar): `PETR4.SA`.
- **EUA, Yahoo** (padrão) e **Stooq** (`--source stooq`, fora do ar em 13/10/2026).
- Cotação grátis tem atraso. Serve para alerta e para conferir tamanhos, não
  para escolher o momento de uma ordem: o preço que executa é o da corretora.

## Os relógios

- **B3**, horário de Brasília: mercado à vista das 10h00 às **16h55** enquanto
  os EUA estão no horário de verão e às **17h55** fora dele (a B3 ajusta a
  grade quando Nova York muda o relógio e anuncia por ofício circular: 17h55
  desde 03/11/2025, 16h55 desde 09/03/2026). A ferramenta supõe a volta para
  17h55 depois do fim do horário de verão americano de 2026 (01/11); confirme
  no ofício circular da B3 antes de depender do horário. Sem pregão em
  2026: 1º/01, 16 e 17/02 (Carnaval), 03/04, 21/04, 01/05, 04/06, 07/09,
  12/10, 02/11, 20/11, 24/12, 25/12 e 31/12; Quarta-feira de Cinzas (18/02) só
  à tarde, a partir das 13h. 2027 está calculado pelos feriados nacionais e
  marcado provisório até a B3 publicar.
- **NYSE**, horário de Nova York: 9h30 às 16h00; feriados de 2026 e 2027 de
  nyse.com, com fechamento às 13h00 no dia seguinte ao Thanksgiving e na
  véspera de Natal. O horário de verão é calculado na ferramenta.

## Passos

1. Pergunte o que acompanhar, nas palavras do usuário ("me avisa se a Vale
   cair abaixo de R$ 52"), crie a regra e confirme: ticker, tipo, nível.
2. Rode `check` agora e, se o usuário quiser, numa tarefa agendada (a cada
   15 minutos no horário do pregão é suficiente). Cada rodada busca só os
   tickers das regras e toca cada alerta uma vez.
3. Conte o que tocou, uma linha cada. Para agir, mande para o dimensionamento
   e o `/trader-risk`. Nunca aja pelo usuário.

## O que ele nunca faz

Nunca envia, cancela ou altera ordem, nunca diz que uma cotação é em tempo
real e nunca prevê para onde o preço vai.

## Segurança

- Educação e ferramenta, não recomendação de investimento (not financial
  advice). Um alerta é um fato sobre um preço, não um sinal para operar.
- B3: nenhuma skill envia ordem. Cada boleta só vai para o seu home broker
  depois do `/trader-risk` e do seu "sim" no chat; quem digita é você.
- EUA: só o `/trader-broker` leva a uma ordem, depois do `/trader-risk`, do seu
  "yes" explícito e do clique em Allow once (ferramenta em "Needs approval",
  nunca "Always allow"). Paper trading é o padrão (`"paper": true`).
- Sem opções, margem, venda a descoberto ou alavancagem, a menos que o config
  permita e você confirme.
- Chaves (`BRAPI_TOKEN`, Alpaca) ficam em variáveis de ambiente ou no config do
  Claude Desktop, nunca no chat.
