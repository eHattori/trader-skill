---
name: trader-copycat
description: >-
  O Engenheiro Reverso. Reconstrói a carteira de um gestor a partir do que ele
  é obrigado a mostrar e escreve pesos para copiar em trader/targets.json. No
  Brasil, lê a CDA mensal da CVM (Composição e Diversificação das Aplicações)
  de qualquer fundo: ações, units, FIIs, ETFs e BDRs no fim do mês, seguindo o
  FIC até o fundo master, com as posições em sigilo e o que mudou contra o mês
  anterior. Nos EUA, lê o 13F-HR trimestral na SEC (Berkshire, Pershing Square
  e outros). Use quando o usuário disser "copiar a carteira da Dynamo", "o que
  o fundo Verde tem", "carteira do SPX Falcon", "copiar o top 5 de um fundo",
  "o que o fundo comprou no mês", "copy Buffett", "copy Berkshire", "13F",
  ou citar qualquer fundo ou gestor.
argument-hint: "[fundo, gestor, CNPJ ou CIK] [--top N]"
---

# trader-copycat

Copiar um gestor começa pelo que a lei obriga ele a mostrar. No Brasil, todo
fundo entrega à CVM, todo mês, a carteira do último dia útil (a CDA). Nos EUA,
todo gestor com mais de US$ 100 milhões em ações americanas entrega o 13F-HR
todo trimestre. Esta skill lê o documento oficial, reconstrói a carteira e
transforma em pesos para a sua conta.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill (onde está este SKILL.md).

## Qual mercado

- Fundo brasileiro (CNPJ, "FIA", "FIC", gestora brasileira): **CDA da CVM**, `fundos.py`.
- Gestor americano (Berkshire, Ackman, Burry, CIK): **13F da SEC**, `edgar13f.py`.
- Use uma pasta de projeto por mercado: o `trader/config.json` de cada uma
  tem `"market": "br"` ou `"us"`, e cada skill segue esse valor.

## Brasil: CDA da CVM

```bash
python3 "${CLAUDE_SKILL_DIR}/fundos.py" busca "dynamo cougar"        # nome -> CNPJ e PL, mês mais recente
python3 "${CLAUDE_SKILL_DIR}/fundos.py" meses                        # meses já publicados
python3 "${CLAUDE_SKILL_DIR}/fundos.py" carteira <CNPJ> --top 15     # posições no fim do mês
python3 "${CLAUDE_SKILL_DIR}/fundos.py" diff <CNPJ>                  # contra o mês anterior
python3 "${CLAUDE_SKILL_DIR}/fundos.py" copiar <CNPJ> --top 5 --out trader/targets.json
python3 "${CLAUDE_SKILL_DIR}/fundos.py" colunas                      # cabeçalhos dos CSVs, se algo quebrar
```

`gestoras.json` nesta pasta lista nomes de fundos de ações conhecidos para a
busca. Ele não traz CNPJs: o CNPJ sempre vem da própria CDA, pela `busca`.
Mostre os resultados e deixe o usuário escolher a classe certa: um mesmo
gestor costuma ter FIC, master, previdência e classes para investidor
qualificado.

O arquivo é https://dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS/cda_fi_AAAAMM.zip,
com algumas centenas de MB, baixado uma vez e guardado em `trader/cache/cvm/`.

### As regras (Brasil)

- **Diga a data, sempre.** "Carteira de 30/09/2026, publicada pela CVM em outubro."
  A CDA é a foto do último dia do mês, não a carteira de hoje.
- **Sigilo.** Fundos podem esconder posições por meses. Na CDA real de
  julho de 2026, a SPX Falcon tinha toda a carteira de ações em sigilo até
  27/01/2027, e o mês mais recente revelado da Dynamo Cougar era março. As
  posições escondidas aparecem só como um total no arquivo CONFID, com a data
  de liberação; a ferramenta mostra os dois. **Sem `--mes`, ela volta mês a
  mês até a carteira mais recente já revelada** e lista os meses que pulou.
  Diga ao usuário de que mês é a carteira: com grandes gestores, costuma ter
  4 a 7 meses. Uma posição que "sumiu" pode ter entrado em sigilo, e não sido vendida.
- **FIC e master.** Quase todo fundo de varejo é um FIC que investe num
  master. Com o padrão (`--seguir-master` implícito) a ferramenta segue até o
  master e avisa. `--sem-master` desliga.
- **Só a ponta comprada à vista.** Entram ações, ações cedidas em aluguel
  (continuam do fundo), units (certificados de depósito) e BDRs. Ficam fora
  debêntures (que têm códigos parecidos com ticker, como CSAN33), opções,
  futuros, termo e ações tomadas em aluguel. A ferramenta mostra quanto ficou
  fora. ETFs e FIIs que o fundo tenha aparecem como cotas de fundo, sem
  ticker, e também ficam fora.
- **O fundo, não a pessoa.** Diga "o fundo tinha", nunca "o gestor comprou".

## EUA: 13F na SEC

```bash
python3 "${CLAUDE_SKILL_DIR}/edgar13f.py" find buffett
python3 "${CLAUDE_SKILL_DIR}/edgar13f.py" filings 1067983
python3 "${CLAUDE_SKILL_DIR}/edgar13f.py" holdings 1067983 --combine --top 15
python3 "${CLAUDE_SKILL_DIR}/edgar13f.py" diff 1067983
python3 "${CLAUDE_SKILL_DIR}/edgar13f.py" copy 1067983 --top 5 --out trader/targets.json
```

A SEC pede que todo programa se identifique: `"sec_user_agent": "Seu Nome
voce@exemplo.com"` em `trader/config.json` (ou `SEC_USER_AGENT`), com o nome
e o e-mail reais do usuário. Pergunte; nunca invente. `filers.json` lista 23
gestores conhecidos com CIK conferido na SEC.

Regras do 13F: é a foto do fim do trimestre, entregue até 45 dias depois; só
ações americanas compradas (sem vendidos, caixa, bonds ou ações fora dos
EUA); Berkshire Hathaway entrega o 13F, não Warren Buffett (Greg Abel é CEO
desde 01/01/2026); opções e bonds (PUT, CALL, PRN) nunca são copiados; um
ticker com `*` é palpite e precisa de conferência (`--figi` ou
`trader/tickers.json`) antes de copiar.

## O que ele grava

`trader/targets.json`, no formato que todas as skills leem:
`{"source", "market", "as_of", "weights": [{"ticker", "name", "weight"}], "caveats"}`,
pesos em % com 2 casas somando 100. Guarde as 2 casas: o dimensionamento usa.
`targets.example.json` aqui é uma rodada real do 13F da Berkshire (top 5).

## Passos

1. Ache o fundo (`busca` ou `find`) e confirme com o usuário qual é.
2. Mostre a carteira (`carteira` ou `holdings`) com a data, o PL, o que está
   em sigilo ou fora da cópia.
3. Mostre o que mudou (`diff`), em quantidades em duas datas: "tinha mais
   ações em 30/09 do que em 31/08", nunca "comprou no dia".
4. Grave os pesos (`copiar` ou `copy`) com o `--top` e as exclusões que o
   usuário quiser, e passe para `/trader-budget`.

## Exemplo

Com a CDA real (lida em 26/10/2026): `busca "dynamo cougar"` acha o FIC
(73.232.530/0001-39) e o master (37.916.879/0001-26). `carteira` do FIC pula
abril a julho, em sigilo, e mostra a carteira do master em 31/03/2026: PL
R$ 11,26 bi, 97,4% em ações da B3, ENEV3 21,6%, VBBR3 11,2%, ITSA4 9,8%,
RDOR3 9,7%, RENT3 8,5%, WEGE3 6,1%... A resposta diz: "Carteira de
31/03/2026, a mais recente que o fundo já revelou; os meses seguintes estão
em sigilo." Depois, `copiar --top 5` e o /trader-budget.

## O que ele nunca faz

- Nunca diz que o fundo ainda tem a posição hoje, nem por que comprou.
- Nunca promete retorno. Copiar compra meses depois do fundo, ao preço de hoje.
- Nunca envia ordem: grava pesos; dimensionamento, risco e o seu sim vêm depois.
- Nunca passa dos limites de acesso: a SEC pede no máximo 10 requisições por
  segundo, e a CVM é baixada uma vez por mês e guardada em cache.

## Segurança

- Educação e ferramenta, não recomendação de investimento (not financial advice).
- B3: nenhuma skill deste pacote envia ordem. Cada boleta só chega ao seu home
  broker depois que o `/trader-risk` aprovou aquela boleta hoje e você disse
  "sim" a ela no chat; quem digita e envia é você.
- EUA: só o `/trader-broker` leva a uma ordem, depois do `/trader-risk`, do seu
  "yes" explícito e do clique em Allow once (ferramenta da corretora em "Needs
  approval", nunca "Always allow"). Paper trading é o padrão (`"paper": true`).
- Sem opções, margem, venda a descoberto ou alavancagem, a menos que o config
  permita e você confirme.
- A CDA é mensal e o 13F é trimestral, ambos com semanas de atraso. Diga isso.
