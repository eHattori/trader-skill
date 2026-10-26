# The Trader skill (edição Brasil)

12 skills do Claude para a B3 e para os EUA: copiam a carteira de fundos e gestores, acompanham fatos relevantes, insiders e o Congresso americano, dimensionam cada boleta ao seu orçamento, apuram o IR e nunca enviam uma ordem sem o seu sim.

Fork de [Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill)
adaptado ao mercado brasileiro. Grátis, MIT, ferramentas em Python padrão
(nada para instalar com pip) que leem dados públicos: CVM (dados.cvm.gov.br),
B3, brapi.dev, Google Notícias, SEC EDGAR, Câmara dos EUA.

O que muda na edição Brasil:

- **Copiar fundos brasileiros** pela CDA mensal da CVM, seguindo o FIC até o master.
- **Insiders da B3**: compras e vendas de controladores e administradores (CVM 44, VLMO).
- **Fatos relevantes** e avisos aos acionistas pelo IPE da CVM, manchetes em português.
- **Resultados** pela DRE do ITR e da DFP na CVM.
- **Boletas da B3**: lote padrão e fracionário, ordem limitada, calendário e
  horário do pregão, conferência de day trade e da isenção de R$ 20 mil.
- **IR brasileiro**: preço médio, isenção, compensação de prejuízo, DARF 6015,
  ações nos EUA pela Lei 14.754.
- **Cotações** pela brapi.dev (Yahoo como reserva).
- Tudo que já existia para os EUA (13F, Pelosi, Alpaca, IBKR) continua lá.

Nenhuma ordem é enviada sem você dizer sim. Na B3 quem digita a boleta no home
broker é você; nos EUA o padrão é paper trading.

## Instalação

Cole no Claude:

```
https://github.com/eHattori/trader-skill

install skill
```

Ou como plugin, no Claude Code:

```
/plugin marketplace add eHattori/trader-skill
/plugin install trader-skill@trader-skill
```

Como plugin, as skills aparecem com prefixo (`/trader-skill:trader-copycat`).
Para ter `/trader-copycat` puro, copie as pastas:

```bash
git clone https://github.com/eHattori/trader-skill.git
cp -r trader-skill/trader-* ~/.claude/skills/
```

As ferramentas pedem Python 3.8 ou mais novo. Para a SEC (parte dos EUA),
ponha seu nome e e-mail em `trader/config.json` (`"sec_user_agent": "Seu Nome
voce@exemplo.com"`) ou em `SEC_USER_AGENT`. Para cotações da B3 além dos
ativos de teste, crie uma chave grátis em brapi.dev e exporte `BRAPI_TOKEN`.

## Um mercado por pasta

Cada projeto tem uma pasta `trader/` e um `trader/config.json` com
`"market": "br"` ou `"us"`. Comece pelo exemplo do mercado:
`trader-budget/config_br.example.json` (B3) ou `config.example.json` (EUA).
Para operar os dois, use duas pastas de projeto.

## As doze

| comando | papel | o que faz |
| --- | --- | --- |
| `/trader-copycat` | Engenheiro Reverso | Reconstrói a carteira de um fundo brasileiro pela CDA da CVM, ou de um gestor americano pelo 13F, com o que mudou desde o último documento. |
| `/trader-insiders` | Rastreador de Insiders | Lê os informes mensais em que controladores, conselheiros e diretores contam à CVM o que negociaram das próprias ações. |
| `/trader-news` | Monitor de Notícias | Fatos relevantes, comunicados e avisos aos acionistas pela CVM e manchetes em português (B3); manchetes e 8-Ks (EUA). |
| `/trader-budget` | Gestor de Orçamento | Dimensiona cada posição ao orçamento, com caixa e teto por ativo; na B3, em lote padrão + fracionário. |
| `/trader-pelosi` | Rastreador do Congresso | Lê as divulgações de negócios dos membros da Câmara dos EUA assim que saem. |
| `/trader-analyst` | Analista de Resultados | Receita, margens, lucro e LPA trimestre a trimestre, pela CVM (ITR/DFP) ou pela SEC (XBRL). |
| `/trader-screener` | Filtro de Ações | Confere empresas contra as suas regras e ranqueia as que passam. |
| `/trader-risk` | Gestor de Risco | Confere cada boleta contra os seus limites; na B3, também lote, day trade e isenção. |
| `/trader-broker` | Executor de Ordens | Mostra a boleta pronta e registra o seu sim; na B3 você executa no home broker, nos EUA vai para a Alpaca ou a IBKR. |
| `/trader-tax` | Otimizador de Impostos | IR brasileiro de renda variável (preço médio, isenção, DARF) e exterior; lotes e wash sale para contribuinte americano. |
| `/trader-alerts` | Alertas de Preço | Toca no alvo, no stop ou na abertura do pregão, com o calendário da B3 e da NYSE. |
| `/trader-rebalance` | Rebalanceador | Traz a carteira de volta aos pesos-alvo quando ela sai da banda. |

## Como usar

Tudo vai para a pasta `trader/` do projeto, e cada skill lê o que a anterior gravou:

```
copycat -> budget -> risk -> broker            (copiar um fundo ou gestor)
news / insiders / pelosi / alerts              (acompanhar, numa tarefa agendada)
analyst -> screener -> budget -> risk -> broker (escolher por conta própria)
rebalance / tax -> risk -> broker              (manter)
```

Exemplo na B3, com R$ 20.000:

1. **`/trader-copycat`** "copiar o top 5 do fundo X". A `busca` acha o CNPJ na
   CDA mais recente; a carteira mostra a data, o que está em sigilo e o master;
   `copiar` grava `trader/targets.json`.
2. **`/trader-alerts`** atualiza as cotações em `trader/prices.json`.
3. **`/trader-budget`** com R$ 20.000, 10% de caixa e teto de 25%: quantidades
   inteiras, 100 PETR4 + 32 PETR4F, preço limite com folga de 0,5%.
4. **`/trader-risk`** confere lote, fracionário, tamanho, caixa e teto: OK ou BLOQ.
5. **`/trader-broker`** mostra uma boleta por vez. Você responde "sim", digita
   no home broker e depois registra a execução com as taxas da nota.
6. Numa tarefa agendada: **`/trader-news`** (fatos relevantes), **`/trader-insiders`**
   (semanal) e **`/trader-alerts`** (seus níveis).
7. Todo mês: **`/trader-copycat`** compara a nova CDA, **`/trader-rebalance`**
   propõe os ajustes e **`/trader-tax`** apura o IR e o DARF.

## As ferramentas

```bash
python3 trader-copycat/fundos.py busca "nome do fundo"           # CDA da CVM
python3 trader-copycat/edgar13f.py find buffett                  # 13F da SEC
python3 trader-insiders/vlmo.py novos --carteira                 # insiders na CVM
python3 trader-news/noticias.py --tickers PETR4 VALE3            # IPE + Google Notícias
python3 trader-analyst/demonstracoes.py WEGE3 --metrics trader/metrics.json
python3 trader-screener/screen.py trader/metrics.json --rules trader-screener/rules_br.example.json
python3 trader-alerts/alerts.py clock --market br                # B3 aberta ou fechada
python3 trader-alerts/alerts.py quote PETR4 BOVA11 --write       # brapi, Yahoo de reserva
python3 trader-budget/size.py --budget 20000 --write             # -> trader/orders.json
python3 trader-risk/check.py                                     # OK / BLOQ por boleta
python3 trader-broker/ticket.py show                             # as boletas, PRONTA ou não
python3 trader-tax/ir_br.py apurar --ano 2026                    # IR mês a mês e DARF
python3 trader-rebalance/rebalance.py --band 5                   # a tabela de desvios
```

```bash
python3 -m unittest discover -s tests -v
python3 tests/sync_b3.py     # depois de editar b3.py ou cvm.py, copia para todas as skills
```

Os testes rodam offline, com fixtures: recortes reais da SEC e da Câmara
para a parte americana e arquivos fictícios no formato da CVM para a parte
brasileira (empresas e fundos inventados).

## Letras miúdas

**Não é recomendação de investimento.** É software que lê dados públicos e faz
contas. Não conhece a sua situação, não prevê o futuro, e copiar um fundo não
copia o resultado dele. Você pode perder dinheiro. Decida por conta própria e,
se precisar, fale com um profissional certificado.

**Nenhuma ordem sai sem o seu sim.** Na B3, nenhuma skill envia nada: você
digita cada boleta no home broker depois que o `/trader-risk` a aprovou e você
disse "sim" a ela no chat. Nos EUA, só o `/trader-broker` leva a uma ordem,
depois do `/trader-risk`, do seu "yes" explícito e do cartão Allow once do
Claude (deixe a ferramenta da corretora em "Needs approval", nunca "Always
allow"). Sem opções, margem, venda a descoberto ou alavancagem, a menos que
você ligue.

**Os dados têm atraso.** A CDA é a carteira do fim do mês, publicada semanas
depois, com até 90 dias de sigilo para algumas posições. O informe de insiders
sai até 10 dias depois do mês. O 13F sai até 45 dias depois do trimestre. As
divulgações do Congresso americano, até 45 dias depois do negócio. Cotação
grátis tem uns 30 minutos de atraso. Nada disso é informação privilegiada.

**As regras da B3 e da Receita mudam.** O calendário de 2026 vem da B3; o de
2027 é provisório. O horário do pregão segue o horário de verão dos EUA e é
anunciado por ofício circular. As regras de IR foram lidas em 26/10/2026
(incluindo a Lei 15.270/2025 e a LC 224/2025). Confira na B3, na Receita e com
seu contador antes de agir.

**Impostos.** `/trader-tax` faz a conta do IR com preço médio, isenção e
compensação de prejuízos, e estima o IRRF. Não é assessoria tributária e não
emite DARF.

**Formatos dos dados abertos.** As colunas da CVM mudam com o tempo (por
exemplo, com a Resolução CVM 175). As ferramentas aceitam os nomes conhecidos
e, se um arquivo mudar, o comando `colunas` de cada uma mostra o cabeçalho
para ajustar.

## Arquivos

```
trader-copycat/    SKILL.md, fundos.py (CDA), edgar13f.py (13F), gestoras.json, filers.json, cvm.py, b3.py
trader-insiders/   SKILL.md, vlmo.py, cvm.py, b3.py
trader-news/       SKILL.md, noticias.py (B3), news.py (EUA), cvm.py, b3.py
trader-budget/     SKILL.md, size.py, b3.py, b3_ativos.json, config_br.example.json, config.example.json
trader-pelosi/     SKILL.md, ptr.py
trader-analyst/    SKILL.md, demonstracoes.py (CVM), facts.py (SEC), cvm.py, b3.py
trader-screener/   SKILL.md, screen.py, rules_br.example.json, rules.example.json
trader-risk/       SKILL.md, check.py, b3.py
trader-broker/     SKILL.md, ticket.py, b3.py, claude_desktop_config.example.json
trader-tax/        SKILL.md, ir_br.py (Brasil), lots.py (EUA), b3.py, portfolio.example.json
trader-alerts/     SKILL.md, alerts.py, b3.py, alerts.example.json
trader-rebalance/  SKILL.md, rebalance.py, b3.py
tests/             unittest + fixtures offline, sync_b3.py
```

MIT. Original de [Jake Schincariol](https://opusjake.ai); edição Brasil por Eduardo Hattori.
