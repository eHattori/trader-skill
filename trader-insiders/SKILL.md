---
name: trader-insiders
description: >-
  O Rastreador de Insiders da B3. Lê os informes mensais em que controladores,
  conselheiros, diretores e membros de órgãos técnicos contam à CVM o que
  compraram e venderam de ações da própria empresa (Resolução CVM 44, art. 11;
  conjunto VLMO nos dados abertos da CVM). Avisa uma vez por documento novo,
  resume compras e vendas por grupo e por empresa, filtra pela sua carteira e
  faz o ranking do mês. Use quando o usuário disser "insiders da Petrobras",
  "o controlador está vendendo?", "diretores compraram ações?", "negociação
  de administradores", "CVM 44", "CVM 358", "quem comprou ações da própria
  empresa", "me avise quando os insiders negociarem". É o equivalente
  brasileiro do /trader-pelosi.
argument-hint: "[ticker] [--carteira]"
---

# trader-insiders

Quem administra ou controla uma companhia aberta precisa informar, todo mês,
o que negociou das ações dela: até 10 dias depois do fim do mês, por grupo
(controlador, conselho de administração, diretoria, conselho fiscal, órgãos
técnicos). A CVM publica esses informes no conjunto "Valores Mobiliários
Negociados e Detidos" (VLMO), atualizado toda semana. Esta skill lê o VLMO,
percebe quando chega um documento novo e conta o que ele diz.

É rápido, não é antecipado. Um negócio do dia 2 aparece por volta do dia 10
do mês seguinte, ou depois. Não há informação privilegiada aqui: são informes
públicos, lidos depressa. Diga isso sempre.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/vlmo.py" novos                          # documentos novos desde a última vez
python3 "${CLAUDE_SKILL_DIR}/vlmo.py" novos --tickers PETR4 VALE3    # só dessas empresas
python3 "${CLAUDE_SKILL_DIR}/vlmo.py" novos --carteira               # portfolio.json + targets.json
python3 "${CLAUDE_SKILL_DIR}/vlmo.py" empresa WEGE3 --ano 2026        # mês a mês de uma empresa
python3 "${CLAUDE_SKILL_DIR}/vlmo.py" ranking --mes 2026-09           # maiores saldos líquidos do mês
python3 "${CLAUDE_SKILL_DIR}/vlmo.py" colunas                         # cabeçalhos do CSV (depuração)
```

## O que lê e grava

- `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS/vlmo_cia_aberta_AAAA.zip`
  (o arquivo de movimentações consolidadas, `_con_`).
- `.../CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_AAAA.zip` para ligar ticker a CNPJ.
- Grava `trader/state/insiders.json` com os documentos já mostrados (empresa,
  mês e versão), para cada um avisar uma vez. Uma reapresentação (versão nova)
  avisa de novo e substitui a anterior.
- Lê `trader/portfolio.json` e `trader/targets.json` com `--carteira`.

## As regras

- **Cite o documento.** Toda linha vem do informe na CVM: empresa, mês de
  referência e versão. Rastreadores de terceiros servem para navegar, mas o
  informe vale mais.
- **Grupo, não pessoa.** O informe é agregado por cargo. Nunca diga "o CEO
  vendeu": diga "a diretoria vendeu".
- **Só compra e venda contam** (à vista, a termo ou sem qualificação).
  Exercício de opção de compra, ações de plano de remuneração, bonificação,
  empréstimo, doação, herança, posse e desligamento aparecem como "outras
  movimentações". Só ações e units entram; opções, debêntures e bônus de
  subscrição ficam fora.
- **Só as ações da própria companhia.** O informe também traz negociações com
  ações da controladora e das controladas; a ferramenta deixa essas fora.
- **Valor nem sempre vem.** Muitos informes trazem a quantidade sem preço:
  aparece "valor não informado". O ranking usa só os que têm valor.
- **Compra e venda iguais no mês**, no mesmo grupo, costumam ser transferência
  entre veículos (holding, fundo, pessoa física), não mudança de posição. A
  ferramenta avisa.
- **ON e PN.** O informe separa por espécie (ON, PN, units); diga qual.
- **FIIs, ETFs e BDRs** não entregam este informe. A ferramenta avisa.
- **Venda de insider tem muitos motivos** (imposto, diversificação, plano de
  remuneração, liquidez). Compras relevantes de vários membros ao mesmo tempo
  chamam mais atenção que uma venda isolada, mas nenhuma é sinal por si só.

## Passos

1. `vlmo.py novos --carteira` (ou com `--tickers`). Na primeira rodada mostra
   os últimos 2 meses; depois, só o que é novo. Código de saída 1 = nada novo.
2. Para cada documento: empresa e ticker, mês, quem comprou ou vendeu, quanto
   (ações e R$) e entre quais datas. Diga a defasagem.
3. Se o usuário quiser contexto: `vlmo.py empresa TICKER` para ver se é um
   padrão de meses, e `/trader-news` para fatos relevantes no mesmo período.
4. Para rodar sozinho: uma tarefa agendada semanal (a CVM atualiza o arquivo
   toda semana), por exemplo às segundas de manhã.

## Exemplo (VLMO real, setembro de 2026, lido em 26/10/2026)

```
NOVO WEG SA (WEGE3), mês 2026-09 (versão 1), CNPJ 84.429.695/0001-11
  - Controlador (ON): comprou 2.540 ações (R$ 128.499); vendeu 3.169.600 ações (R$ 163.457.288)
  - Diretor (ON): comprou 5.000 ações (R$ 249.750)
  negócios entre 2026-09-02 e 2026-09-29
```

E então: "É um informe público entregue até 10 dias depois do mês. Diz o que
o grupo controlador negociou em setembro, não o que alguém vai fazer, nem por quê."

Se o usuário quiser agir, o caminho é o longo: `/trader-budget`, `/trader-risk`
e o sim dele no `/trader-broker`, boleta por boleta.

## O que ele nunca faz

- Nunca diz ou insinua que alguém tem informação privilegiada, nem que copiar
  insiders bate o mercado.
- Nunca atribui a um nome o que o informe dá para um grupo.
- Nunca envia ordem.

## Segurança

- Educação e ferramenta, não recomendação de investimento (not financial advice).
- Nenhuma skill deste pacote envia ordem na B3. Uma boleta só chega ao seu home
  broker depois que o `/trader-risk` a aprovou hoje e você disse "sim" a ela no
  chat; quem digita e envia é você.
- Sem opções, margem, venda a descoberto ou alavancagem, a menos que o config
  permita e você confirme.
- Os informes são públicos e chegam com 10 a 40 dias de atraso. Diga isso.
