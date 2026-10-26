---
name: trader-tax
description: >-
  O Otimizador de Impostos. Para quem mora no Brasil: apura o IR de renda
  variável mês a mês pelas regras da Receita (preço médio, operações comuns a
  15%, day trade a 20%, FII a 20%, isenção de vendas de ações até R$ 20 mil
  no mês, prejuízo compensado por grupo, IRRF dedo-duro, DARF 6015 com
  vencimento e a regra dos R$ 10), mostra a posição a custo para Bens e
  Direitos, lista prejuízos não realizados e calcula ações no exterior pela
  Lei 14.754/2023 (15% ao ano). Para quem paga imposto nos EUA: lotes de
  custo, curto ou longo prazo, tax-loss harvesting e wash sale. Não é
  assessoria tributária. Use quando o usuário disser "quanto de IR eu pago",
  "DARF", "preço médio", "isenção de 20 mil", "compensar prejuízo", "day
  trade", "declarar ações", "IR das ações dos EUA", "tax lots", "wash sale".
argument-hint: "[apurar|posicao|prejuizo|exterior] [ticker]"
---

# trader-tax

O Otimizador faz a conta de imposto sobre as operações do usuário para
ninguém vender às cegas. Ele não decide o que vale para a situação fiscal de
ninguém. **Não é assessoria tributária**: quem decide é o contador do
usuário. Diga isso uma vez, logo no começo, em toda resposta que usar esta skill.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

## Qual regra

- **Residente fiscal no Brasil** (o caso padrão deste fork): `ir_br.py`, para
  as operações na B3 e para as ações nos EUA (`exterior`).
- **Contribuinte americano**: `lots.py` (lotes, wash sale, curto e longo
  prazo). As regras americanas **não** valem para residente no Brasil: no
  Brasil não existe wash sale nem lote para imposto, o custo é preço médio.

## Brasil: ir_br.py

```bash
python3 "${CLAUDE_SKILL_DIR}/ir_br.py" apurar --ano 2026                  # mês a mês e DARF
python3 "${CLAUDE_SKILL_DIR}/ir_br.py" apurar --ano 2026 --mes 10 --json
python3 "${CLAUDE_SKILL_DIR}/ir_br.py" apurar --trades notas.csv          # importa execuções (data;ticker;lado;quantidade;preco;taxas)
python3 "${CLAUDE_SKILL_DIR}/ir_br.py" posicao --em 2026-12-31            # preço médio e custo, para Bens e Direitos
python3 "${CLAUDE_SKILL_DIR}/ir_br.py" prejuizo --precos trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/ir_br.py" exterior --ano 2026 --trades exterior.csv   # data;ticker;lado;quantidade;preco;cambio;taxas
```

Entradas: `trader/portfolio.json`, lista `trades` (gravada pelo `ticket.py
fill` do trader-broker) e `opening` (posições que o usuário já tinha, com
quantidade e custo total); ou um CSV das notas de corretagem. No
`trader/config.json`: `prejuizo_acumulado` (`comum`, `daytrade`, `fii`) com
o saldo do início do ano, `irrf_saldo` e `asset_types` para corrigir um ativo.
Se faltar uma compra antiga ou o custo, pergunte. Nunca invente custo.

### As regras que aplica (lidas em 26/10/2026)

- **Preço médio**: compras mais taxas divididas pela quantidade; vender não
  muda o preço médio. Não é FIFO.
- **Day trade**: compra e venda do mesmo ativo no mesmo dia; a quantidade
  casada é day trade, ao preço médio do dia de cada lado, o resto segue como
  operação comum.
- **Operações comuns** (ações, units, ETFs, BDRs): 15% sobre o lucro do mês.
- **Isenção**: vendas de **ações** (e units) no mercado à vista de até R$
  20.000 no mês tornam o lucro com ações isento. O teste usa o total vendido,
  não o lucro. ETFs, BDRs e FIIs não têm isenção. O prejuízo de um mês isento
  continua compensável; o prejuízo acumulado não abate lucro isento.
- **Day trade**: 20%, grupo próprio. **FII**: 20% sobre o lucro na venda de
  cotas, grupo próprio. Cada grupo só compensa o seu prejuízo, sem prazo.
- **IRRF**: 0,005% das vendas comuns (retido quando passa de R$ 1) e 1% do
  lucro de day trade; abate do imposto e o que sobra passa adiante. A
  ferramenta estima: os valores certos estão nas notas de corretagem.
- **DARF 6015**: até o último dia útil do mês seguinte. Abaixo de R$ 10 não se
  paga: acumula para o próximo. Atraso: multa de 0,33% ao dia (até 20%) mais
  Selic; recalcule no Sicalc da Receita.
- **Proventos** (não entram na apuração mensal): dividendos isentos até R$
  50.000 por mês de cada empresa; acima disso a empresa retém 10% sobre o total
  (Lei 15.270/2025, desde 2026), e rendas acima de R$ 600 mil por ano entram no
  imposto mínimo anual. JCP: 17,5% retido na fonte (LC 224/2025, desde 2026).
  Rendimentos de FII listado com mais de 100 cotistas: isentos para pessoa física.
- **Exterior** (Lei 14.754/2023): 15% sobre o ganho realizado, em reais, apurado
  no ano e pago na declaração anual; sem isenção mensal; prejuízo compensa
  ganho do mesmo tipo. Cada operação precisa da cotação do dólar da data na
  regra da Receita: confirme qual cotação (compra ou venda, PTAX) com o contador.

## EUA: lots.py (contribuinte americano)

```bash
python3 "${CLAUDE_SKILL_DIR}/lots.py" report --lots
python3 "${CLAUDE_SKILL_DIR}/lots.py" sell KO 2 --price 90.11
python3 "${CLAUDE_SKILL_DIR}/lots.py" harvest --min-loss 100 [--write]
python3 "${CLAUDE_SKILL_DIR}/lots.py" wash KO
```

Longo prazo se vendido mais de um ano depois da compra; métodos `fifo`,
`hifo` e `specific`; wash sale: prejuízo não dedutível se o mesmo ativo (ou
substancialmente idêntico, GOOG e GOOGL juntos) for comprado 30 dias antes ou
depois. A ferramenta não vê IRA, cônjuge ou outra corretora: diga isso.
Formato dos lotes em `portfolio.example.json`.

## Passos

1. Diga que não é assessoria tributária.
2. Brasil: `apurar` do ano. Mostre, por mês com operação: vendas de ações e se
   o mês foi isento, resultado e base de cada grupo, prejuízo compensado, IRRF
   e o DARF com o vencimento. Termine com o saldo de prejuízo a compensar.
3. Antes de uma venda (rebalanceamento, stop, mudança de ideia), simule: some
   a venda às vendas de ações do mês. Se passar de R$ 20.000, diga que o lucro
   do mês inteiro com ações deixa de ser isento. Vender no mês seguinte ou
   dividir a venda é uma escolha do usuário; mostre os números.
4. `prejuizo` lista posições abaixo do preço médio. No Brasil não há wash
   sale, mas: recomprar no MESMO dia vira day trade; o prejuízo só abate lucro
   do mesmo grupo; vender e recomprar só para gerar prejuízo pode ser
   questionado pela Receita. Diga isso.
5. Para a declaração anual: `posicao --em AAAA-12-31` dá o custo de cada ativo
   para Bens e Direitos (pelo custo, nunca pelo valor de mercado).

## Exemplo (dados fictícios dos testes)

```
2026-03  vendas de ações R$ 12.000,00  (até R$ 20.000: lucro com ações isento)
    lucro isento (ações): R$ 1.194,00
2026-04  vendas de ações R$ 11.600,00  (isento) ... prejuízo a compensar R$ 1.403,00
2026-05  vendas de ações R$ 24.600,00
    comum 15%  resultado R$ 1.790,00  compensado R$ 1.403,00  base R$ 387,00  imposto R$ 58,05
    imposto R$ 58,05 - IRRF estimado R$ 1,23 = DARF 6015 R$ 56,82, vence 30/06/2026
2026-06  day trade 20%  imposto R$ 3,00 - IRRF R$ 0,15: abaixo de R$ 10, acumula R$ 2,85
2026-07  FII 20%  imposto R$ 60,00 + R$ 2,85 acumulado = DARF 6015 R$ 62,85, vence 31/08/2026
```

## O que ele nunca faz

Nunca entrega declaração, nunca emite DARF, nunca diz que o resultado é
definitivo, nunca envia ordem e nunca sugere venda e recompra para fabricar
prejuízo.

## Segurança

- Não é assessoria tributária, e é educação e ferramenta, não recomendação de
  investimento (not financial advice). Confira com um contador.
- B3: nenhuma skill envia ordem. Cada boleta só vai para o seu home broker
  depois do `/trader-risk` e do seu "sim" no chat; quem digita é você.
- EUA: só o `/trader-broker` leva a uma ordem, depois do `/trader-risk`, do seu
  "yes" explícito e do clique em Allow once (ferramenta em "Needs approval",
  nunca "Always allow"). Paper trading é o padrão (`"paper": true`).
- Sem opções, margem, venda a descoberto ou alavancagem, a menos que o config
  permita e você confirme.
- Chaves ficam em variáveis de ambiente ou no config do Claude Desktop, nunca no chat.
