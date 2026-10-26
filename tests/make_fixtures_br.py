#!/usr/bin/env python3
"""Gera as fixtures brasileiras dos testes (dados fictícios no formato REAL da CVM).

Os cabeçalhos, a ordem das colunas e os valores de domínio (TP_APLIC, Tipo_Movimentacao,
Tipo_Empresa, Tipo_Ativo, categorias do IPE) foram copiados dos arquivos reais de
dados.cvm.gov.br lidos em 26/10/2026 (CDA 01-07/2026, VLMO/IPE/FCA/ITR 2026, DFP 2025).
Empresas, fundos, CNPJs e valores são inventados.

    python3 tests/make_fixtures_br.py
"""

import io
import os
import zipfile

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

CIA = "11.222.333/0001-44"      # COMPANHIA EXEMPLO S.A., EXMP3 / EXMP4
BANK = "60.746.948/0001-12"     # BANCO EXEMPLO S.A., BEXE3
MASTER = "11.111.111/0001-11"   # EXEMPLO MASTER FIF EM AÇÕES
FIC = "22.222.222/0001-22"      # EXEMPLO AÇÕES FIC FIF


def write_zip(folder, name, members):
    os.makedirs(os.path.join(FIX, folder), exist_ok=True)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for member, header, rows in members:
            z.writestr(member, (header + "\n" + "\n".join(rows) + "\n").encode("latin-1"))
    with open(os.path.join(FIX, folder, name), "wb") as fh:
        fh.write(b.getvalue())


# ---------------------------------------------------------------- CDA (copycat)

H_PL = "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;VL_PATRIM_LIQ"
H_B2 = ("TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;TP_APLIC;TP_ATIVO;EMISSOR_LIGADO;TP_NEGOC;"
        "QT_VENDA_NEGOC;VL_VENDA_NEGOC;QT_AQUIS_NEGOC;VL_AQUIS_NEGOC;QT_POS_FINAL;VL_MERC_POS_FINAL;"
        "VL_CUSTO_POS_FINAL;DT_CONFID_APLIC;CNPJ_FUNDO_CLASSE_COTA;ID_SUBCLASSE;NM_FUNDO_CLASSE_SUBCLASSE_COTA")
H_B4 = ("TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;TP_APLIC;TP_ATIVO;EMISSOR_LIGADO;TP_NEGOC;"
        "QT_VENDA_NEGOC;VL_VENDA_NEGOC;QT_AQUIS_NEGOC;VL_AQUIS_NEGOC;QT_POS_FINAL;VL_MERC_POS_FINAL;"
        "VL_CUSTO_POS_FINAL;DT_CONFID_APLIC;CD_ATIVO;DS_ATIVO;CD_ISIN;DT_INI_VIGENCIA;DT_FIM_VIGENCIA")
H_B8 = ("TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;TP_APLIC;TP_ATIVO;EMISSOR_LIGADO;TP_NEGOC;"
        "QT_VENDA_NEGOC;VL_VENDA_NEGOC;QT_AQUIS_NEGOC;VL_AQUIS_NEGOC;QT_POS_FINAL;VL_MERC_POS_FINAL;"
        "VL_CUSTO_POS_FINAL;DT_CONFID_APLIC;DS_ATIVO;PF_PJ_EMISSOR;CPF_CNPJ_EMISSOR;EMISSOR")
H_CONF = "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;TP_APLIC;VL_VENDA_NEGOC;VL_AQUIS_NEGOC;VL_MERC_POS_FINAL;VL_CUSTO_POS_FINAL;DT_CONFID_APLIC"
MN = "EXEMPLO MASTER FIF EM AÇÕES RESPONSABILIDADE LIMITADA"
FN = "EXEMPLO AÇÕES FIC FIF RESPONSABILIDADE LIMITADA"


def b4(cnpj, name, dt, aplic, ativo, qty, val, cd, ds):
    return ";".join(["CLASSES - FIF", cnpj, name, dt, aplic, ativo, "N", "Para negociação", "", "", "", "",
                     "%.6f" % qty, "%.2f" % val, "", "", cd, ds, "BR" + cd + "XXX0", "2010-01-01", ""])


def cda(month, dt, pl, b4rows, b8rows, b2rows, confid):
    write_zip("trader-copycat-br", "cda_fi_%s.zip" % month, [
        ("cda_fi_PL_%s.csv" % month, H_PL, ["CLASSES - FIF;%s;%s;%s;%s" % (c, n, dt, v) for c, n, v in pl]),
        ("cda_fi_BLC_2_%s.csv" % month, H_B2, b2rows),
        ("cda_fi_BLC_4_%s.csv" % month, H_B4, b4rows),
        ("cda_fi_BLC_8_%s.csv" % month, H_B8, b8rows),
        ("cda_fi_CONFID_%s.csv" % month, H_CONF, confid),
    ])


def make_cda():
    dt = "2026-09-30"
    fic_cota = ";".join(["CLASSES - FIF", FIC, FN, dt, "Cotas de Fundos", "Fundo de Investimento e de Cotas", "S", "",
                         "", "", "", "", "1000.000000", "980000.00", "", "", MASTER, "", MN])
    cda("202609", dt, [(MASTER, MN, "1000000.00"), (FIC, FN, "1000000.00")], [
        b4(MASTER, MN, dt, "Ações", "Ação preferencial", 10000, 400000, "PETR4", "PETROBRAS PN"),
        b4(MASTER, MN, dt, "Ações e outros TVM cedidos em empréstimo", "Ação preferencial", 2000, 80000, "PETR4",
           "PETROBRAS PN"),
        b4(MASTER, MN, dt, "Ações", "Ação ordinária", 5000, 300000, "VALE3", "VALE ON"),
        b4(MASTER, MN, dt, "Certificado ou recibo de depósito de valores mobiliários", "Certificado de depósito de ações",
           3000, 110000, "TAEE11", "TAESA UNT"),
        # tudo isto fica FORA da cópia (casos reais)
        b4(MASTER, MN, dt, "Debêntures", "Debênture simples", 100, 114749.69, "CSAN33", "DEB"),
        b4(MASTER, MN, dt, "Opções - Posições lançadas", "Opção de compra", -1000, -5000, "PETRK380", "PETR K380"),
        b4(MASTER, MN, dt, "Obrigações por ações e outros TVM recebidos em empréstimo", "Ação ordinária", -500,
           -30000, "MGLU3", "MAGAZINE LUIZA"),
        b4(MASTER, MN, dt, "Compras a termo a receber", "Ação ordinária", 100, 4000, "ITUB4", "ITAU PN"),
    ], [
        ";".join(["CLASSES - FIF", MASTER, MN, dt, "Ações", "Ação ordinária", "", "Para negociação", "", "", "", "",
                  "1000.000000", "50000.00", "", "", "Ação EGIE3 Engie Brasil", "PJ", "02.474.103/0001-19", "ENGIE"]),
        ";".join(["CLASSES - FIF", MASTER, MN, dt, "Disponibilidades", "Outros", "", "Para negociação", "", "", "",
                  "", "", "15000.00", "", "", "Disponibilidade", "", "", ""]),
    ], [fic_cota], [
        "CLASSES - FIF;%s;%s;%s;Ações;0;0;120000;;2027-03-31" % (MASTER, MN, dt),
        "CLASSES - FIF;%s;%s;%s;Cotas de Fundos;0;0;999999;;2027-03-31" % (MASTER, MN, dt),  # não é ação: não conta
    ])
    dt = "2026-08-31"
    cda("202608", dt, [(MASTER, MN, "950000.00"), (FIC, FN, "940000.00")], [
        b4(MASTER, MN, dt, "Ações", "Ação preferencial", 8000, 310000, "PETR4", "PETROBRAS PN"),
        b4(MASTER, MN, dt, "Ações", "Ação ordinária", 6000, 350000, "VALE3", "VALE ON"),
        b4(MASTER, MN, dt, "Ações", "Ação preferencial", 4000, 90000, "ITUB4", "ITAU PN"),
    ], [], [fic_cota.replace("2026-09-30", dt)], [])
    # outubro: tudo em sigilo (como os grandes fundos reais), para testar a volta ao mês revelado
    dt = "2026-10-31"
    cda("202610", dt, [(MASTER, MN, "1010000.00"), (FIC, FN, "1000000.00")], [], [], [], [
        "CLASSES - FIF;%s;%s;%s;Ações;0;0;950000;;2027-04-30" % (MASTER, MN, dt),
        "CLASSES - FIF;%s;%s;%s;Cotas de Fundos;0;0;990000;;2027-04-30" % (FIC, FN, dt),
    ])


# ---------------------------------------------------------------- FCA (ticker -> CNPJ)

H_FCA = ("CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Empresarial;Valor_Mobiliario;"
         "Sigla_Classe_Acao_Preferencial;Classe_Acao_Preferencial;Codigo_Negociacao;Composicao_BDR_Unit;Mercado;"
         "Sigla_Entidade_Administradora;Entidade_Administradora;Data_Inicio_Negociacao;Data_Fim_Negociacao;"
         "Segmento;Data_Inicio_Listagem;Data_Fim_Listagem")
B3 = "Bolsa;B3;B3 S.A. - Brasil, Bolsa, Balcão."


def fca_zip(folder):
    rows = [
        "%s;2026-01-01;1;1;COMPANHIA EXEMPLO S.A.;Ações Ordinárias;;;EXMP3;;%s;2010-01-01;;Nível 2;2010-01-01;" % (CIA, B3),
        "%s;2026-01-01;1;1;COMPANHIA EXEMPLO S.A.;Ações Preferenciais;PN;Preferencial;EXMP4;;%s;2010-01-01;;Nível 2;2010-01-01;" % (CIA, B3),
        "%s;2026-01-01;1;2;BANCO EXEMPLO S.A.;Ações Ordinárias;;;BEXE3;;%s;2010-01-01;;Novo Mercado;2010-01-01;" % (BANK, B3),
        "%s;2026-01-01;1;2;BANCO EXEMPLO S.A.;Ações Ordinárias;;;BEXE3X;;%s;2010-01-01;2015-01-01;;;" % (BANK, B3),
        "%s;2026-01-01;1;2;BANCO EXEMPLO S.A.;Debêntures;;;NÃO HÁ;;Balcão Organizado;B3;B3;;;;;" % BANK,
    ]
    write_zip(folder, "fca_cia_aberta_2026.zip", [
        ("fca_cia_aberta_valor_mobiliario_2026.csv", H_FCA, rows),
        ("fca_cia_aberta_geral_2026.csv", "CNPJ_Companhia;Nome_Empresarial", []),
    ])


# ---------------------------------------------------------------- VLMO (insiders)

H_VLMO = ("CNPJ_Companhia;Nome_Companhia;Data_Referencia;Versao;Tipo_Empresa;Empresa;Tipo_Cargo;Tipo_Movimentacao;"
          "Descricao_Movimentacao;Tipo_Operacao;Tipo_Ativo;Caracteristica_Valor_Mobiliario;Intermediario;"
          "Data_Movimentacao;Quantidade;Preco_Unitario;Volume")
H_VLMO_DOC = ("CNPJ_Companhia;Nome_Companhia;Data_Referencia;Versao;Codigo_CVM;Categoria;Tipo;Data_Entrega;"
              "Tipo_Apresentacao;Motivo_Reapresentacao;Protocolo_Entrega;Link_Download")


def vl(cnpj, nome, ver, temp, cargo, mov, op, ativo, carac, data, qty, price, vol, ref="2026-09-01", emp=None):
    return ";".join([cnpj, nome, ref, str(ver), temp, emp or nome, cargo, mov, "", op, ativo, carac, "", data,
                     str(qty), price, vol])


def make_vlmo():
    C, N, B, BN = CIA, "COMPANHIA EXEMPLO S.A.", BANK, "BANCO EXEMPLO S.A."
    rows = [
        vl(C, N, 1, "Companhia", "Diretor ou Vinculado", "Saldo Inicial", "Crédito", "Ações", "PN", "", 100000, "", ""),
        vl(C, N, 1, "Companhia", "Diretor ou Vinculado", "Compra à vista", "Crédito", "Ações", "PN", "2026-09-15",
           20000, "37.5000000000", "750000.0000000000"),
        vl(C, N, 1, "Companhia", "Conselho de Administração ou Vinculado", "Venda à vista", "Débito", "Ações", "ON",
           "2026-09-22", 5000, "40.1000000000", "200500.0000000000"),
        # casos reais que NÃO são compra ou venda no mercado:
        vl(C, N, 1, "Companhia", "Diretor ou Vinculado", "Ações decorrentes de exercício de opção de compra",
           "Crédito", "Ações", "PN", "2026-09-16", 7000, "0.0000000000", "0.0000000000"),
        vl(C, N, 1, "Companhia", "Diretor ou Vinculado", "Compra à vista", "Crédito", "Opções de Plano de Remuneração",
           "PN", "2026-09-16", 9000, "1.0000000000", "9000.0000000000"),
        vl(C, N, 1, "Controladora", "Controlador ou Vinculado", "Venda à vista", "Débito", "Ações", "ON", "2026-09-18",
           888888, "10.0000000000", "8888880.0000000000", emp="HOLDING EXEMPLO S.A."),
        # compra sem preço informado (comum no arquivo real)
        vl(C, N, 1, "Companhia", "Conselho Fiscal ou Vinculado", "Compra à vista", "Crédito", "Ações", "ON",
           "2026-09-29", 100, "0.0000000000", "0.0000000000"),
        # banco: versão 1 substituída pela 2; transferência entre veículos na versão 2
        vl(B, BN, 1, "Companhia", "Controlador ou Vinculado", "Venda à vista", "Débito", "Ações", "ON", "2026-09-10",
           1000000, "12.0000000000", "12000000.0000000000"),
        vl(B, BN, 2, "Companhia", "Controlador ou Vinculado", "Venda à vista", "Débito", "Ações", "ON", "2026-09-10",
           900000, "12.0000000000", "10800000.0000000000"),
        vl(B, BN, 2, "Companhia", "Conselho de Administração ou Vinculado", "Compra", "Crédito", "Ações", "ON",
           "2026-09-11", 50000, "12.0000000000", "600000.0000000000"),
        vl(B, BN, 2, "Companhia", "Conselho de Administração ou Vinculado", "Venda", "Débito", "Ações", "ON",
           "2026-09-11", 50000, "12.0000000000", "600000.0000000000"),
    ]
    write_zip("trader-insiders", "vlmo_cia_aberta_2026.zip", [
        ("vlmo_cia_aberta_con_2026.csv", H_VLMO, rows),
        ("vlmo_cia_aberta_2026.csv", H_VLMO_DOC, []),
    ])
    fca_zip("trader-insiders")


# ---------------------------------------------------------------- IPE (notícias)

H_IPE = ("CNPJ_Companhia;Nome_Companhia;Codigo_CVM;Data_Referencia;Categoria;Tipo;Especie;Assunto;Data_Entrega;"
         "Tipo_Apresentacao;Protocolo_Entrega;Versao;Link_Download")
RAD = "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&descTipo=IPE&CodigoInstituicao=1&numProtocolo=%d&numSequencia=%d&numVersao=1"


def ipe(cnpj, nome, cat, tipo, esp, assunto, data, n):
    return ";".join([cnpj, nome, "9999", data, cat, tipo, esp, assunto, data, "AP - Apresentação",
                     "009999IPE%08d" % n, "1", RAD % (n, n)])


def make_ipe():
    N = "COMPANHIA EXEMPLO S.A."
    rows = [
        ipe(CIA, N, "Fato Relevante", "", "", "Aprovação de aquisição de controle da Alfa Ltda.", "2026-10-23", 1),
        ipe(CIA, N, "Aviso aos Acionistas", "Juros sobre Capital Próprio", "", "Pagamento de juros sobre capital próprio",
            "2026-10-24", 2),
        ipe(CIA, N, "Relatório Proventos", "", "", "Proventos em dinheiro", "2026-10-24", 3),
        ipe(CIA, N, "Valores Mobiliários negociados e detidos (art. 11 da Instr. CVM nº 358)", "Posição Consolidada",
            "", "", "2026-10-09", 4),
        ipe(CIA, N, "Comunicado ao Mercado", "Outros Comunicados Não Considerados Fatos Relevantes", "",
            "Esclarecimento sobre notícia", "2026-09-01", 5),
        ipe(CIA, N, "Estatuto Social", "", "", "Estatuto consolidado", "2026-10-24", 6),
        ipe(BANK, "BANCO EXEMPLO S.A.", "Fato Relevante", "", "", "Outra empresa", "2026-10-24", 7),
    ]
    write_zip("trader-news-br", "ipe_cia_aberta_2026.zip", [("ipe_cia_aberta_2026.csv", H_IPE, rows)])
    # Google Notícias: mesmo formato do RSS real (title "manchete - veículo", link, pubDate, source)
    rss = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>EXMP4</title>
<item><title>Companhia Exemplo anuncia lucro recorde no 3T26 - Jornal Exemplo</title><link>https://news.google.com/rss/articles/EXEMPLO1?oc=5</link><pubDate>Sat, 24 Oct 2026 13:00:00 GMT</pubDate><source url="https://exemplo.com.br">Jornal Exemplo</source></item>
<item><title>Notícia antiga da Exemplo - Jornal Exemplo</title><link>https://news.google.com/rss/articles/EXEMPLO2?oc=5</link><pubDate>Mon, 01 Jun 2026 13:00:00 GMT</pubDate><source url="https://exemplo.com.br">Jornal Exemplo</source></item>
</channel></rss>
"""
    with open(os.path.join(FIX, "trader-news-br", "google-EXMP4.xml"), "w", encoding="utf-8") as fh:
        fh.write(rss)
    fca_zip("trader-news-br")


# ---------------------------------------------------------------- ITR / DFP (analyst)

H_DRE = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;DT_INI_EXERC;"
         "DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA")


def dre(ref, ini, fim, rec, bruto, ebit, lucro, lpa_on, lpa_pn, ver=1, ordem="ÚLTIMO"):
    out = []
    for cd, ds, v in (("3.01", "Receita de Venda de Bens e/ou Serviços", rec), ("3.03", "Resultado Bruto", bruto),
                      ("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", ebit),
                      ("3.11", "Lucro/Prejuízo Consolidado do Período", lucro),
                      ("3.99.02.01", "ON", lpa_on), ("3.99.02.02", "PN", lpa_pn)):
        out.append(";".join([CIA, ref, str(ver), "COMPANHIA EXEMPLO S.A.", "009999",
                             "DF Consolidado - Demonstração do Resultado", "REAL", "MIL", ordem, ini, fim, cd, ds,
                             "%.10f" % v, "S"]))
    return out


def make_itr():
    def itr(year, qs, stale_version=False):
        rows, ytd = [], [0] * 6
        ends = {1: ("%d-01-01" % year, "%d-03-31" % year), 2: ("%d-04-01" % year, "%d-06-30" % year),
                3: ("%d-07-01" % year, "%d-09-30" % year)}
        for q, vals in qs.items():
            ini, fim = ends[q]
            ytd = [a + b for a, b in zip(ytd, vals)]
            ver = 2 if (stale_version and q == 1) else 1
            rows += dre(fim, ini, fim, *vals, ver=ver)
            if stale_version and q == 1:
                rows += dre(fim, ini, fim, *[x * 9 for x in vals], ver=1)  # versão antiga, deve ser ignorada
            if q > 1:
                rows += dre(fim, "%d-01-01" % year, fim, *ytd)
            rows += dre(fim, "%d-%s" % (year - 1, ini[5:]), "%d-%s" % (year - 1, fim[5:]), *[x * 0.5 for x in vals],
                        ordem="PENÚLTIMO")
        write_zip("trader-analyst-br", "itr_cia_aberta_%d.zip" % year,
                  [("itr_cia_aberta_DRE_con_%d.csv" % year, H_DRE, rows),
                   ("itr_cia_aberta_%d.csv" % year, "CNPJ_CIA;DT_REFER;VERSAO", [])])
    itr(2025, {1: (1000000, 400000, 200000, 150000, 0.30, 0.33), 2: (1100000, 440000, 220000, 160000, 0.32, 0.35),
               3: (1200000, 480000, 240000, 170000, 0.34, 0.37)})
    itr(2026, {1: (1150000, 470000, 240000, 180000, 0.36, 0.40), 2: (1250000, 520000, 260000, 190000, 0.38, 0.42),
               3: (1380000, 560000, 280000, 300000, 0.60, 0.66)}, stale_version=True)
    write_zip("trader-analyst-br", "dfp_cia_aberta_2025.zip",
              [("dfp_cia_aberta_DRE_con_2025.csv", H_DRE,
                dre("2025-12-31", "2025-01-01", "2025-12-31", 4600000, 1860000, 920000, 640000, 1.28, 1.41))])
    fca_zip("trader-analyst-br")


if __name__ == "__main__":
    make_cda()
    make_vlmo()
    make_ipe()
    make_itr()
    print("fixtures BR gravadas em", FIX)
