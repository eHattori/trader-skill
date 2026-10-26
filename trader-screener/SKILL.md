---
name: trader-screener
description: >-
  O Filtro de Ações. Confere uma lista de empresas contra as regras do próprio
  usuário (crescimento de receita, margens, LPA, P/L, lucro sobre preço,
  setor, qualquer coluna do arquivo de métricas), diz exatamente qual regra
  cada empresa passa ou falha e por quanto, e ranqueia as aprovadas. Lê as
  métricas que o /trader-analyst grava (CVM para a B3, SEC para os EUA) ou
  qualquer CSV, inclusive no formato brasileiro 1.234,56. Use quando o
  usuário disser "filtrar ações", "achar empresas que", "quais passam nas
  minhas regras", "P/L abaixo de 10", "lucrativas e crescendo", "ranquear
  estas ações", "screen for stocks", "shortlist".
argument-hint: "[arquivo de métricas] [--rules regras.json]"
---

# trader-screener

Um filtro transforma "quero empresas lucrativas, ainda crescendo e não caras
demais" em regras que um computador confere, e mostra o trabalho: toda
aprovação e reprovação vem com o número e o limite.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill. Ferramenta em Python padrão, sem rede:

```bash
python3 "${CLAUDE_SKILL_DIR}/screen.py" --help
python3 "${CLAUDE_SKILL_DIR}/screen.py" trader/metrics.json --rules trader/rules.json \
  --prices trader/prices.json --out trader/shortlist.json
```

## O que lê e grava

- Métricas: `trader/metrics.json` do `/trader-analyst` (`demonstracoes.py
  --metrics` para a B3, `facts.py --metrics` para os EUA; mesmo formato), ou
  qualquer JSON ou CSV com uma coluna `ticker`. Números de CSV podem ter `R$`,
  `$`, `%`, separador de milhar e vírgula decimal brasileira.
- Preços (opcional): `trader/prices.json` (o `/trader-alerts` grava). Com eles
  o filtro acrescenta `price`, `pe` (P/L: preço sobre LPA dos 12 meses, só com
  LPA positivo) e `earnings_yield`.
- Regras: um JSON. `rules_br.example.json` (B3) e `rules.example.json` (EUA)
  nesta pasta para começar.
- Grava `trader/shortlist.json` com `--out`: quem passou, a nota e por quê,
  quem falhou e por quê.

## O arquivo de regras

```json
{"name": "B3: lucrativa, crescendo, sem preço de perfeição",
 "rules": [{"metric": "revenue_growth_yoy", "op": ">=", "value": 5},
           {"metric": "net_margin", "op": ">=", "value": 8},
           {"metric": "pe", "op": "<=", "value": 15}],
 "rank":  [{"metric": "eps_growth_yoy", "order": "desc", "weight": 2},
           {"metric": "pe", "order": "asc", "weight": 1}],
 "missing": "skip"}
```

Operadores: `>`, `>=`, `<`, `<=`, `==`, `!=`, `between` ([mín, máx]), `in` e
`not in` (uma lista, para tickers ou setores). `"missing": "fail"` reprova
quem não tem a métrica que a regra pede; `"skip"` ignora a regra para ela e
diz isso. Bancos não têm margem bruta: numa carteira da B3 com bancos, prefira
`"skip"` ou não use essa métrica. O ranking dá de 0 a 1 por métrica e tira a
média ponderada.

## Passos

1. Transforme as palavras do usuário em regras. Pergunte quando o limite for
   vago ("barata" é P/L de quanto?). Grave em `trader/rules.json`.
2. Gere as métricas dos candidatos com o `/trader-analyst` (`--metrics
   trader/metrics.json`), ou use o CSV do usuário. Atualize preços se o P/L importar.
3. Rode o filtro. Código 1 = ninguém passou: diga e mostre os que chegaram mais perto.
4. Mostre a lista com os motivos, os reprovados com os números que falharam e
   a data dos números (fim do trimestre de cada empresa, data do preço).
   Sugira `/trader-analyst` nos primeiros antes de qualquer outra coisa.

## Exemplos

B3 (dados fictícios dos testes): `EXMP4` com receita +15%, margem líquida
21,7%, LPA de 12 meses R$ 1,84 e preço R$ 22,10 (P/L 12) passa nas quatro
regras de `rules_br.example.json`.

EUA (2026-10-13): com `rules.example.json`, passam GOOGL (crescimento 24,2,
P/L 17,8) e KO (12,1, P/L 28,3); AAPL falha no P/L (39,2 > 35), BAC e AXP não
têm margem operacional nos fatos da SEC.

## O que ele nunca faz

- Nunca chama uma aprovada de compra. Um filtro é um filtro sobre números
  entregues, não recomendação.
- Nunca preenche um número faltando nem chuta uma métrica: faltando é faltando.
- Nunca manda nada sozinho para o `/trader-budget` ou para um caminho de ordem.

## Segurança

Educação e ferramenta, não recomendação de investimento (not financial
advice). Esta skill só filtra números. Nada envia ordem: na B3 você digita
cada boleta no home broker depois do `/trader-risk` e do seu "sim"; nos EUA
só o `/trader-broker` envia, depois do `/trader-risk` e do seu "yes" explícito.
