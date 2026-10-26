---
name: trader-pelosi
description: >-
  O Rastreador do Congresso americano. Acompanha as negociações de ações que
  os membros do Congresso dos EUA são obrigados a divulgar pelo STOCK Act: lê
  os Periodic Transaction Reports (PTRs) da Câmara assim que são publicados,
  avisa uma vez por documento novo e transforma cada PDF em linhas limpas
  (quem, titular, ativo, ticker, compra ou venda, strike e vencimento de
  opções, data, faixa de valor, dias até divulgar). Marca negócios em ações
  que você tem. O Senado tem uma rota manual documentada. Use quando o
  usuário disser "o que a Pelosi está comprando", "trades do Congresso",
  "Nancy Pelosi", "deputado americano comprou X", "me avise quando a Pelosi
  divulgar". Para insiders de empresas brasileiras, use /trader-insiders.
argument-hint: "[nome do membro] [--read]"
---

# trader-pelosi

Membros do Congresso americano precisam informar as negociações deles, do
cônjuge e dos filhos dependentes. A Câmara publica cada relatório em PDF e
lista todos num índice por ano. Esta skill lê o índice, percebe na hora
quando um relatório novo aparece e lê o relatório para você.

É rápido, não é antecipado. O PTR vence 30 dias depois de o membro saber do
negócio e nunca mais de 45 dias depois dele, então quando alguém consegue ler
o negócio já tem dias ou semanas. Não há informação privilegiada aqui: só
documentos públicos, lidos depressa. Diga isso sempre.

Equivalente brasileiro: `/trader-insiders` (controladores e administradores
de companhias da B3, pela CVM). Não existe divulgação parecida para
parlamentares brasileiros.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill. Ferramenta em Python padrão
(`pdftotext`, do poppler, é opcional, para ler os PDFs localmente):

```bash
python3 "${CLAUDE_SKILL_DIR}/ptr.py" --help
python3 "${CLAUDE_SKILL_DIR}/ptr.py" index --member pelosi
python3 "${CLAUDE_SKILL_DIR}/ptr.py" index --since 2026-10-01        # todos os membros
python3 "${CLAUDE_SKILL_DIR}/ptr.py" index --member "Josh Gottheimer" --year 2025
python3 "${CLAUDE_SKILL_DIR}/ptr.py" new --member pelosi --read      # só os novos, lidos
python3 "${CLAUDE_SKILL_DIR}/ptr.py" fetch 20035143
python3 "${CLAUDE_SKILL_DIR}/ptr.py" parse ptr.txt --filed 2026-08-21 --json
```

## O que lê e grava

- `https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<ANO>FD.zip`
  (um registro por documento: nome, distrito, tipo, data, DocID) e cada PTR em
  `.../public_disc/ptr-pdfs/<ANO>/<DocID>.pdf`.
- Grava `trader/state/pelosi.json` (DocIDs já mostrados) e guarda os PDFs em
  `trader/state/ptr-pdfs/`.
- Lê `trader/portfolio.json` para marcar negócios em ações que você tem.

## As regras

- **Cite o documento, não um rastreador.** Toda linha vem do PDF da Câmara,
  com DocID e link. O Capitol Trades mostrou as datas da Pelosi um dia antes
  das dos PTRs: o PTR vale.
- **Valores são faixas.** "US$ 1.000.001 a US$ 5.000.000", nunca "US$ 3 milhões".
- **Titular importa.** SP é o cônjuge, JT conjunto, DC filho dependente, vazio
  é o próprio membro. Os negócios de 2026 da Pelosi são todos SP (Paul Pelosi).
- **Diga a defasagem.** Cada linha mostra os dias entre o negócio e a
  divulgação; acima de 45 é marcado como atrasado.
- **Opção é opção.** Uma call com strike e vencimento não é compra de ações.

## Passos

1. `index` para ver o que já foi entregue (`--member` aceita sobrenome, "Nome
   Sobrenome" ou "Sobrenome, Nome"; `--type ''` lista todos os tipos).
2. `new --member pelosi --read` mostra só os PTRs ainda não vistos (na
   primeira vez, os últimos 45 dias), baixa e lê. Código 1 = nada novo. Em
   janeiro também olha o índice do ano anterior. A Câmara refaz o índice
   cerca de uma vez por dia: checar de hora em hora em dias úteis basta.
3. `fetch` salva o PDF e, com `pdftotext`, imprime as linhas; sem ele, abra o
   PDF salvo e leia. `parse` transforma o texto de `pdftotext -layout` em
   linhas. Confira o número de linhas contra o PDF em relatórios longos.

## O Senado: a rota manual

Os relatórios ficam em `https://efdsearch.senate.gov`. Antes de buscar, o
site pede que se marque a concordância com os limites legais de uso. Essa
concordância é da pessoa, então esta skill não clica nem automatiza. O
usuário abre `https://efdsearch.senate.gov/search/`, aceita, escolhe "Periodic
Transactions", digita o sobrenome, define as datas, abre o relatório e cola a
tabela (ou uma captura) no chat; você escreve no mesmo formato das linhas da
Câmara, com o link e o mesmo aviso de 45 dias.

## Exemplo

```
NEW Periodic Transaction Report: Hon. Nancy Pelosi (CA11) filed 2026-08-21, doc 20035143
  - spouse purchase, Bloom Energy Corporation Class A Common Stock (BE): 100 call
    options, $100 strike, expires 2027-06-17, $1,000,001 - $5,000,000, traded
    2026-07-24, disclosed 28 days later
```

O mesmo PTR mostra 10.000 e 5.000 ações BE, um segundo bloco de 100 calls BE
em 28/07, ações da Intel e 50 calls da Intel (strike US$ 50, 17/06/27) e uma
LLC imobiliária sem ticker. Depois: "É uma divulgação pública feita 28 dias
depois do negócio. Diz o que Paul Pelosi comprou em julho, não o que alguém
vai comprar."

Para agir, o caminho é o longo: só ações (o config tem `allow_options:
false`), dimensionadas pelo `/trader-budget`, conferidas pelo `/trader-risk`
e enviadas pelo `/trader-broker` só depois do sim do usuário.

## O que ele nunca faz

- Nunca diz ou insinua que um membro tem informação privilegiada, nem que
  copiar um político bate o mercado. Sem promessa de retorno.
- Nunca apresenta faixa como valor exato, nem a data de um rastreador como data do negócio.
- Nunca envia ordem e nunca copia operações com opções.
- Nunca automatiza a concordância do Senado nem qualquer login.

## Segurança

- Educação e ferramenta, não recomendação de investimento (not financial advice).
- Nada neste pacote envia ordem, exceto o `/trader-broker` (EUA), e só depois
  que o `/trader-risk` aprovou aquela ordem, você disse um "yes" explícito
  para ela no chat e clicou em Allow once no cartão do Claude (ferramenta da
  corretora em "Needs approval", nunca "Always allow"). Na B3, você mesmo
  digita cada boleta no home broker depois do seu "sim".
- Paper trading é o padrão (`"paper": true`).
- Sem opções, margem, venda a descoberto ou alavancagem, a menos que o config
  permita e você confirme.
- Os negócios do Congresso são divulgações PÚBLICAS feitas até 45 dias depois
  (STOCK Act). Esta skill lê depressa; não tem informação privilegiada, e diz isso.
