---
name: trader-broker
description: >-
  O Executor de Ordens. Leva uma boleta APROVADA até a corretora, uma por vez,
  e nunca sem o seu sim explícito. Na B3 não existe conector de corretora
  brasileira: a skill mostra a boleta pronta para o home broker (ativo, lote
  padrão ou fracionário, limitada, preço, validade), registra o seu "sim"
  palavra por palavra, você envia, e depois registra a execução com as taxas
  da nota de corretagem, a preço médio. Nos EUA, monta o JSON exato do
  place_stock_order da Alpaca (paper por padrão) ou do conector da
  Interactive Brokers, e o cartão Allow once / Deny do Claude pergunta de
  novo. Use quando o usuário disser "manda as ordens", "pode comprar",
  "executar", "boleta", "registrar a nota de corretagem", "place the orders",
  "connect Alpaca", ou depois que o /trader-risk aprovar.
argument-hint: "[número da boleta]"
---

# trader-broker

O Executor é a única skill deste pacote que leva a uma ordem real, então é a
mais rígida. Uma boleta só sai depois de travas separadas, toda vez, para
cada boleta:

1. **O trader-risk aprovou esta boleta exata hoje** (pela impressão digital).
2. **O usuário digitou um sim explícito para esta boleta** no chat.
3. **B3:** o próprio usuário digita e envia no home broker. **EUA:** o usuário
   clica em Allow once no cartão do Claude, que aparece porque a ferramenta de
   ordem está em "Needs approval".

Sem sim, sem ordem.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                       # todas as boletas, PRONTA ou não
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "sim"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed            # B3: você enviou
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol PETR4 --side buy --qty 100 --price 37.40 --fees 1.12
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

O `ticket.py` nunca fala com corretora. Ele mostra as boletas, confere se a
resposta é um sim de verdade para aquela boleta e guarda o registro em
`trader/state/broker.json`.

## B3: boleta manual no home broker

Nenhuma corretora brasileira tem conector para o Claude hoje. O fluxo:

1. `ticket.py show`. Só boletas PRONTAS vão para o usuário; NÃO PRONTA ou
   BLOQUEADA volta para o `/trader-risk`.
2. Mostre UMA boleta e pergunte: "Aprova esta boleta? Responda sim ou não."
   Uma por pergunta. Nunca ofereça "sim para todas".
3. `ticket.py approve --index N --reply "<a resposta do usuário, palavra por palavra>"`.
   "Não registrado" significa que a resposta não foi um sim explícito para
   esta boleta ("pode", "ok", "sim para todas", um sim que cita outro ativo ou
   outro valor). Pergunte de novo. Nunca transforme uma resposta em sim.
4. O usuário digita no home broker exatamente o que a boleta diz: compra ou
   venda, ticker (PETR4 no lote padrão, PETR4F no fracionário), quantidade,
   tipo limitada, preço e validade.
5. `ticket.py result --index N --status placed` (enviou), `denied` (desistiu)
   ou `failed --note "motivo"` (o home broker rejeitou). Uma rejeitada não é
   reenviada sem nova checagem e novo sim.
6. Quando executar, `ticket.py fill` com a quantidade, o preço executado e as
   taxas da nota de corretagem (corretagem + emolumentos + liquidação). A
   execução vai para `trader/portfolio.json` a **preço médio** (a regra do IR
   brasileiro) e para a lista `trades`, que o `/trader-tax` usa para apurar o
   imposto do mês.

Boleta de exemplo:

```
BOLETA 2 de 7, B3, você executa no home broker da sua corretora
  COMPRA 32 PETR4F (fracionário), limitada a R$ 37,61, validade: hoje (dia)
  ativo: ação PETR4
  valor máximo: R$ 1.203,52 (sem corretagem e emolumentos)
  PRONTA: trader-risk aprovou, aguardando o seu sim
  Na boleta do home broker: Compra, quantidade 32, tipo limitada, preço R$ 37,61, validade dia.
```

## EUA, opção A: Alpaca (servidor MCP oficial, Claude Desktop)

O servidor da própria Alpaca é github.com/alpacahq/alpaca-mcp-server (MIT).
Roda no computador do usuário dentro do Claude Desktop, não está no diretório
de conectores e opera em conta **paper** salvo instrução em contrário.

1. O usuário cria uma conta na Alpaca e chaves de API de **paper trading**.
2. Instala o `uv` (que traz o `uvx`), de docs.astral.sh/uv.
3. No Claude Desktop: Settings > Developer > Edit Config abre o
   `claude_desktop_config.json`. O usuário acrescenta o bloco de
   `claude_desktop_config.example.json` desta pasta e digita as próprias chaves
   no arquivo. **Chaves nunca vão para o chat.** Nunca peça, nunca leia esse
   arquivo de volta na conversa; se o usuário colar uma chave, diga para
   apagar a mensagem e gerar chaves novas na Alpaca.
4. Reinicia o Claude Desktop.
5. **Permissões**: em Customize > Connectors, alpaca: `place_stock_order` em
   **Needs approval** (nunca Always allow); tudo que cancela, fecha ou altera
   também em Needs approval; opções, cripto, `close_all_positions` e
   `cancel_all_orders` em **Blocked**; consultas podem ficar em Always allow.
6. Confira: peça as informações da conta (só leitura) e confirme no painel da
   Alpaca que é a conta paper.

No Claude Code, deixe a ferramenta de ordem em ask no `.claude/settings.json`:
`"permissions": {"ask": ["mcp__alpaca__place_stock_order"]}`.

## EUA, opção B: Interactive Brokers (conector do diretório)

A Interactive Brokers publica um conector verificado:
claude.ai/directory/interactive-brokers (URL `https://api.ibkr.com/v1/api/mcp`).
Adicione em Customize > Connectors e faça login na IBKR lá, não no chat. O
Claude rascunha a instrução de ordem, que vai para a conta IBKR para revisão
e aprovação do usuário; nada vai direto ao mercado. `"broker": "ibkr"` no config.

## EUA: passos por ordem

`show`, uma ordem por pergunta ("Place this order? Reply yes or no."),
`approve --reply` palavra por palavra, e só depois de "Recorded your yes" a
chamada a `place_stock_order` com exatamente o JSON da boleta; o cartão Allow
once / Deny aparece. Depois `result --status placed --broker-id <id>`,
`denied` ou `failed`, e `fill` quando a execução for conhecida.

## O que ele nunca faz

- Nunca leva uma boleta adiante sem todas as travas, e nunca duas com um sim.
- Nunca envia nada por tarefa agendada ou em segundo plano: não há ninguém
  para dizer sim.
- Nunca pede, lê, guarda ou repete chaves de API, senhas, assinatura
  eletrônica ou token da corretora.
- Nunca troca `ALPACA_PAPER_TRADE` ou `"paper"` para conta real. O usuário faz isso.
- Nunca chama `close_all_positions`, `cancel_all_orders`, ordens de opção ou
  cripto por conta própria.

## Segurança

- Educação e ferramenta, não recomendação de investimento (not financial
  advice). Nenhuma boleta aqui é recomendação e nada promete retorno.
- B3: quem envia a ordem é sempre você, no seu home broker, depois do seu "sim"
  registrado para aquela boleta e da aprovação do `/trader-risk` hoje.
- EUA: só com as três travas: aprovação do `/trader-risk` hoje, o seu "yes"
  explícito para aquela ordem e o clique em Allow once (ferramenta em "Needs
  approval", nunca "Always allow"). Paper trading é o padrão.
- Sem opções, margem, venda a descoberto ou alavancagem, a menos que o config
  permita e você confirme.
- Chaves ficam em variáveis de ambiente ou no config do Claude Desktop, nunca no chat.
