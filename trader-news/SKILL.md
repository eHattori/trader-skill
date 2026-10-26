---
name: trader-news
description: >-
  O Monitor de Notícias. Acompanha, para cada ativo que você tem ou vai
  copiar, o que a empresa protocolou e o que a imprensa publicou, e mostra só
  o que é novo desde a última checagem. Na B3: fatos relevantes, comunicados
  ao mercado, avisos aos acionistas (dividendos, JCP, bonificação), releases
  de resultado e assembleias pelo IPE da CVM, mais manchetes em português do
  Google Notícias. Nos EUA: manchetes do Yahoo Finance e 8-Ks da SEC. Use
  quando o usuário disser "alguma notícia das minhas ações", "saiu fato
  relevante?", "o que aconteceu com a Petrobras", "monitorar notícias",
  "resumo da manhã", "any news on my stocks", "check the 8-Ks".
argument-hint: "[tickers]"
---

# trader-news

Uma posição pode mudar em um minuto: um fato relevante de aquisição, um
resultado abaixo do esperado, a saída do CEO, um processo. Esta skill lê as
fontes que trazem isso primeiro e conta só o que é novo.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

## Brasil: CVM (IPE) + Google Notícias

```bash
python3 "${CLAUDE_SKILL_DIR}/noticias.py"                              # tickers de portfolio.json ou targets.json
python3 "${CLAUDE_SKILL_DIR}/noticias.py" --tickers PETR4 VALE3 --dias 3
python3 "${CLAUDE_SKILL_DIR}/noticias.py" --sem-google                 # só documentos da CVM
python3 "${CLAUDE_SKILL_DIR}/noticias.py" --todos --json
```

- **IPE da CVM**: `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_AAAA.zip`,
  atualizado ao longo do dia útil; o ticker vira CNPJ pelo FCA. Mostra fato
  relevante, comunicado ao mercado, aviso aos acionistas, dados
  econômico-financeiros (release de resultados), assembleia, calendário de
  eventos e reunião da administração; o resto (estatuto, atas rotineiras) fica de fora.
- **Google Notícias**: `https://news.google.com/rss/search?q="PETR4"&hl=pt-BR&gl=BR&ceid=BR:pt-419`.
- FIIs, ETFs e BDRs não protocolam no IPE de companhias: para eles só as
  manchetes rodam. FIIs publicam fatos relevantes no Fundos.NET da B3; diga
  isso e sugira olhar lá.
- Grava `trader/state/noticias.json` (o que já foi mostrado, 30 dias).

Selos: `!` em fato relevante, release de resultados e aviso aos acionistas.
Etiquetas: resultado, proventos, jurídico, negócio, pessoas, risco.

## EUA: Yahoo + SEC

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers AAPL AXP GOOGL KO BAC --hours 24
python3 "${CLAUDE_SKILL_DIR}/news.py" --forms 8-K,10-Q --all --json
```

Yahoo Finance RSS por ticker e o feed Atom de 8-Ks de cada empresa na SEC
(precisa do `sec_user_agent` em `trader/config.json` ou `SEC_USER_AGENT`; sem
ele, só manchetes). 8-Ks marcados com `!` trazem um item importante:
resultado (2.02), troca de executivo (5.02), impairment (2.06), aviso de
deslistagem (3.01), balanço anterior não confiável (4.02), falência (1.03) ou
incidente cibernético (1.05). Estado em `trader/state/news.json`.

## As regras

- **Manchete é pista, não fato.** Antes de dizer que algo aconteceu, abra o
  documento ou a matéria e leia. Cite a fonte e o link. Nunca resuma matéria
  com paywall que você não leu: diga que tem paywall.
- **Documento vale mais que manchete.** Se um fato relevante (ou um 8-K) e uma
  manchete discordam, vale o que a empresa protocolou.
- **Diga o que toca.** Cada item mostra os tickers e o peso deles na carteira
  (de `trader/targets.json`).
- **Sem previsão.** Conte o que foi publicado; nunca diga o que a ação vai fazer.

## Passos

1. Rode a checagem do mercado do projeto (`noticias.py` para B3, `news.py`
   para EUA). Código de saída 1 = nada novo.
2. Leia os itens que importam: todo `!`, tudo marcado como resultado,
   proventos, jurídico ou risco, e as maiores posições primeiro.
3. Escreva um resumo curto: por ativo, o que aconteceu, a fonte e o link, e
   uma linha sobre por que importa para esta carteira. Quando um ativo não
   tem nada, diga isso em vez de encher o resumo.
4. Se algo pode mudar o plano (aquisição relevante, recuperação judicial,
   reapresentação de balanço), diga e sugira `/trader-analyst` para os números
   ou `/trader-risk` para reconferir boletas pendentes. Nunca aja só por manchete.

Para rodar sozinho: `/loop 30m /trader-news` no horário do pregão ou uma
tarefa agendada de manhã.

## Exemplo (dados fictícios dos testes)

```
! 2026-10-24 EXMP4   [aviso aos acionistas] Pagamento de juros sobre capital próprio
! 2026-10-23 EXMP4   [FATO RELEVANTE] Aprovação de aquisição de controle da Alfa Ltda.
  2026-10-24 EXMP4   [manchete] Companhia Exemplo anuncia lucro recorde no 3T26
```

Resumo: "A Companhia Exemplo (30% da carteira) protocolou fato relevante de
aquisição em 23/10 e aviso de JCP em 24/10; a imprensa repercute o lucro do
3T26. Leia o fato relevante antes de qualquer decisão."

## O que ele nunca faz

- Nunca inventa ou enfeita uma notícia, citação ou número.
- Nunca opera por notícia, nem diz para comprar ou vender por causa de uma manchete.
- Nunca sobrecarrega um servidor: uma requisição por feed por ticker, pausa
  entre chamadas, e o arquivo da CVM baixado uma vez a cada poucas horas.

## Segurança

Educação e ferramenta, não recomendação de investimento (not financial
advice). Esta skill só lê e conta. Nada envia ordem: na B3 você digita cada
boleta no home broker depois do `/trader-risk` e do seu "sim"; nos EUA só o
`/trader-broker` envia, depois do `/trader-risk` e do seu "yes" explícito.
