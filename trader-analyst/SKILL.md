---
name: trader-analyst
description: >-
  O Analista de Resultados. Lê os números que a empresa entregou ao regulador
  e resume o que mudou: receita, margens bruta, EBIT e líquida, lucro e lucro
  por ação, trimestre a trimestre, cada um contra o mesmo trimestre do ano
  anterior, e os últimos 12 meses. Na B3, pela DRE consolidada do ITR e da
  DFP nos dados abertos da CVM (4º trimestre derivado do ano menos 9 meses).
  Nos EUA, pelos fatos XBRL da SEC e o release do 8-K. Grava um arquivo de
  métricas para o screener. Use quando o usuário disser "como foi o
  resultado da WEG", "analisa o balanço", "o lucro cresceu?", "compara as
  margens", "o que mudou no trimestre", "3T26", "how did Apple's earnings
  look", "check the 10-Q".
argument-hint: "[tickers]"
---

# trader-analyst

Temporada de resultados mexe com as ações, e o release é escrito para pôr o
melhor número primeiro. Esta skill lê os números que a companhia de fato
entregou ao regulador, alinha trimestre a trimestre e diz com clareza o que mudou.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

## Brasil: ITR e DFP na CVM

```bash
python3 "${CLAUDE_SKILL_DIR}/demonstracoes.py" WEGE3                      # últimos 4 trimestres
python3 "${CLAUDE_SKILL_DIR}/demonstracoes.py" WEGE3 ITUB4 --trimestres 8
python3 "${CLAUDE_SKILL_DIR}/demonstracoes.py" WEGE3 VALE3 PETR4 --metrics trader/metrics.json
python3 "${CLAUDE_SKILL_DIR}/demonstracoes.py" colunas                    # cabeçalhos (depuração)
```

Lê `itr_cia_aberta_AAAA.zip` e `dfp_cia_aberta_AAAA.zip`
(`https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR|DFP/DADOS/`), arquivo
`DRE_con`, só a versão mais recente de cada entrega e só o exercício atual
(`ÚLTIMO`). O ticker vira CNPJ pelo FCA. Valores na escala "MIL" viram reais.

Contas: 3.01 receita, 3.03 resultado bruto, 3.05 EBIT (resultado antes do
financeiro e dos tributos), 3.11 lucro consolidado do período (procurado
também pelo nome), 3.99 lucro por ação (diluído; por classe ON e PN; a
ferramenta usa a PN quando existe, a classe mais negociada).

## EUA: XBRL na SEC

```bash
python3 "${CLAUDE_SKILL_DIR}/facts.py" AAPL
python3 "${CLAUDE_SKILL_DIR}/facts.py" AAPL AXP GOOGL KO BAC --metrics trader/metrics.json
python3 "${CLAUDE_SKILL_DIR}/facts.py" --help                              # --quarters, --json, --cik
```

Lê `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`, a lista
de entregas (o 10-Q ou 10-K mais novo e o 8-K com item 2.02) e o release
(EX-99.1). Precisa do `sec_user_agent`; recusa chamar a SEC sem ele.
`metrics.example.json` é uma rodada real de 2026-10-13.

## As regras

- **Número entregue primeiro.** A tabela vem da DRE (CVM) ou do XBRL (SEC). O
  release (no IPE da CVM, via `/trader-news`, ou o EX-99.1 da SEC) dá
  contexto: guidance, segmentos. Diga de onde veio cada número.
- **Compare igual com igual.** Crescimento é contra o mesmo trimestre do ano
  anterior. Varejo e indústria têm sazonalidade forte; o trimestre contra o
  anterior engana.
- **Diga o que é derivado.** Ninguém entrega ITR do 4º trimestre: ele é a DFP
  do ano menos os 9 meses e vem marcado "derivado". LPA derivado é aproximado.
- **Diga quando o dado atrasa.** A CVM publica o ITR em até 45 dias depois do
  trimestre (a DFP em até 3 meses); os fatos da SEC podem ficar atrás do 10-Q.
  Se o trimestre que o usuário quer ainda não está lá, diga e leia o documento.
- **Marque o não recorrente.** Lucro acima do EBIT significa resultado
  financeiro ou um evento fora da operação (venda de ativo, crédito
  tributário, equivalência). A ferramenta avisa.
- **Bancos e seguradoras** usam outro plano de contas: sem margem bruta, e a
  "receita" é a da intermediação financeira. Em branco, não zero.

## Passos

1. Rode para as empresas em questão (ou todos os tickers de `trader/targets.json`).
2. Leia o release e, se os números pedirem, o ITR/DFP completo (notas
   explicativas) para entender um salto.
3. Escreva o resumo: uma linha do trimestre (receita, lucro, LPA, crescimento),
   uma das margens, uma do que é incomum (não recorrente, trimestre derivado,
   dado atrasado) e os links. Palavras simples, números reais, nenhum
   adjetivo que os números não sustentem.

## Exemplo (dados fictícios dos testes)

`demonstracoes.py EXMP4`: trimestre de 30/09/2026, receita R$ 1,38 bi
(+15,0% sobre o 3T25), lucro R$ 300,0 mi (+76,5%), LPA PN R$ 0,66; margem
EBIT 20,3%; o lucro passou o EBIT, então há resultado financeiro ou não
recorrente relevante. 4T25 derivado (DFP menos 9 meses). Últimos 12 meses:
receita R$ 5,08 bi, lucro R$ 830,0 mi, LPA R$ 1,84.

## O que ele nunca faz

- Nunca diz que uma ação está barata, cara, que é compra ou venda. Conta o
  que a empresa entregou.
- Nunca inventa um número que os documentos não têm, nem estima um trimestre
  que não consegue derivar.
- Nunca chama a SEC sem User-Agent, e fica bem abaixo de 10 requisições por segundo.

## Segurança

Educação e ferramenta, não recomendação de investimento (not financial
advice). Esta skill só lê demonstrações. Nada envia ordem: na B3 você digita
cada boleta no home broker depois do `/trader-risk` e do seu "sim"; nos EUA
só o `/trader-broker` envia, depois do `/trader-risk` e do seu "yes" explícito.
