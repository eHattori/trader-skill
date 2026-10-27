#!/usr/bin/env python3
"""Resultados trimestrais de companhias da B3 pelos dados abertos da CVM (trader-analyst, BR).

Lê as demonstrações que a companhia entregou à CVM (ITR, trimestral, e DFP,
anual), monta a DRE consolidada trimestre a trimestre e compara cada
trimestre com o mesmo trimestre do ano anterior.

    python3 demonstracoes.py WEGE3                    # últimos 4 trimestres
    python3 demonstracoes.py WEGE3 ITUB4 --trimestres 8
    python3 demonstracoes.py WEGE3 VALE3 --metrics trader/metrics.json   # para o trader-screener
    python3 demonstracoes.py WEGE3 --json
    python3 demonstracoes.py colunas --ano 2026       # cabeçalhos (depuração)

Contas da DRE (plano padrão da CVM; bancos e seguradoras usam outro plano):
  3.01  receita de venda de bens e/ou serviços (bancos: receitas da intermediação financeira)
  3.03  resultado bruto
  3.05  resultado antes do resultado financeiro e dos tributos (EBIT)
  3.11  lucro/prejuízo consolidado do período (procurado também pelo nome)
  3.99  lucro por ação (3.99.01 básico, 3.99.02 diluído; por classe: ON, PN)

O 4º trimestre não é entregue em ITR: é o ano da DFP menos os 9 meses do ITR
do 3º trimestre, e é marcado "derivado". Valores em reais (a escala "MIL" da
CVM é convertida). Lucro por ação não é convertido.

Arquivos: https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_AAAA.zip
          https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_AAAA.zip
          FCA (ticker -> CNPJ): .../CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_AAAA.zip
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import b3  # noqa: E402
import cvm  # noqa: E402

NET_NAMES = ("lucro/prejuizo consolidado do periodo", "lucro ou prejuizo liquido consolidado do periodo",
             "lucro/prejuizo do periodo", "lucro liquido do periodo", "lucro ou prejuizo liquido do periodo")
FIN_HINTS = ("intermediacao financeira", "seguros", "previdencia", "segurador")
EBIT_NAMES = ("resultado antes do resultado financeiro e dos tributos",)
BRUTO_NAMES = ("resultado bruto",)


def _by_name(p, names):
    """Valor da conta de 1º nível (3.xx) cujo nome está em `names` (o código muda entre planos de contas)."""
    for code, d in sorted(p["_desc"].items()):
        if code.count(".") == 1 and cvm.fold(d) in names:
            return p[code]
    return None


class AnalystError(Exception):
    pass


def _zip(kind, year, offline=None):
    kind = kind.lower()
    return cvm.download("CIA_ABERTA/DOC/%s/DADOS/%s_cia_aberta_%d.zip" % (kind.upper(), kind, year),
                        max_age=24, offline=offline)


def dre_rows(kind, year, cnpjs, offline=None):
    """Linhas da DRE consolidada (ORDEM_EXERC ÚLTIMO, versão mais recente) das empresas pedidas."""
    try:
        z = _zip(kind, year, offline)
    except cvm.CVMError:
        return []
    name = None
    for n in cvm.members(z, "dre_con"):
        if n.lower().endswith(".csv"):
            name = n
    if not name:
        return []
    out = []
    for r in cvm.rows(z, member=name):
        c = cvm.digits(cvm.pick(r, "CNPJ_CIA")).zfill(14)
        if c not in cnpjs:
            continue
        if cvm.fold(cvm.pick(r, "ORDEM_EXERC", default="")) != "ultimo":
            continue
        out.append({"cnpj": c, "ref": cvm.pick(r, "DT_REFER"), "versao": int(float(cvm.pick(r, "VERSAO") or 0)),
                    "nome": cvm.pick(r, "DENOM_CIA"), "escala": cvm.fold(cvm.pick(r, "ESCALA_MOEDA", default="")),
                    "ini": cvm.pick(r, "DT_INI_EXERC"), "fim": cvm.pick(r, "DT_FIM_EXERC"),
                    "conta": cvm.pick(r, "CD_CONTA"), "desc": cvm.pick(r, "DS_CONTA") or "",
                    "valor": cvm.num(cvm.pick(r, "VL_CONTA")), "kind": kind})
    best = {}
    for r in out:
        k = (r["cnpj"], r["ref"])
        best[k] = max(best.get(k, -1), r["versao"])
    return [r for r in out if r["versao"] == best[(r["cnpj"], r["ref"])]]


def _months(ini, fim):
    a = datetime.date.fromisoformat(ini)
    b = datetime.date.fromisoformat(fim)
    return (b.year - a.year) * 12 + b.month - a.month + 1


def periods(rows):
    """{(ini, fim): {conta: valor, '_desc': {conta: desc}}} em reais."""
    out = {}
    for r in rows:
        mult = 1000.0 if r["escala"] == "mil" and not str(r["conta"]).startswith("3.99") else 1.0
        p = out.setdefault((r["ini"], r["fim"]), {"_desc": {}, "_nome": r["nome"]})
        p[r["conta"]] = r["valor"] * mult
        p["_desc"][r["conta"]] = r["desc"]
    return out


def pick_lines(p):
    """Receita, lucro bruto, EBIT, lucro líquido e LPA diluído de um período."""
    desc = p["_desc"]
    net = None
    for code, d in sorted(desc.items()):
        if cvm.fold(d) in NET_NAMES and code.count(".") == 1:
            net = p[code]
            break
    if net is None:
        for code in ("3.11", "3.09", "3.13"):
            if code in p and "lucro" in cvm.fold(desc.get(code, "")):
                net = p[code]
                break
    eps = None
    for prefix in ("3.99.02", "3.99.01"):
        vals = [(c, p[c]) for c in sorted(p) if isinstance(c, str) and c.startswith(prefix + ".") and p[c]]
        if vals:
            eps = vals
            break
    fin = any(h in cvm.fold(desc.get("3.01", "")) for h in FIN_HINTS)
    receita = p.get("3.01") or None  # zero = a companhia não preenche (holdings e seguradoras)
    return {"receita": receita, "lucro_bruto": None if fin else (_by_name(p, BRUTO_NAMES) or None),
            "ebit": _by_name(p, EBIT_NAMES), "lucro": net, "lpa": eps, "financeira": fin}


def quarterly(itr_rows, dfp_rows):
    """Série trimestral: 3 meses do ITR; 4º tri = DFP do ano - 9 meses do ITR do 3º tri."""
    q = {}
    itr = periods(itr_rows)
    for (ini, fim), p in itr.items():
        if _months(ini, fim) == 3:
            q[fim] = dict(pick_lines(p), fim=fim, derivado=False, nome=p["_nome"])
    nine = {fim[:4]: pick_lines(p) for (ini, fim), p in itr.items() if _months(ini, fim) == 9}
    for (ini, fim), p in periods(dfp_rows).items():
        if _months(ini, fim) != 12:
            continue
        year = fim[:4]
        if fim in q or year not in nine:
            continue
        y, n = pick_lines(p), nine[year]
        d = {}
        for k in ("receita", "lucro_bruto", "ebit", "lucro"):
            d[k] = (y[k] - n[k]) if (y[k] is not None and n[k] is not None) else None
        lpa = None
        if y["lpa"] and n["lpa"]:
            nn = dict(n["lpa"])
            lpa = [(c, v - nn[c]) for c, v in y["lpa"] if c in nn]
        q[fim] = dict(d, lpa=lpa, financeira=y["financeira"], fim=fim, derivado=True, nome=p["_nome"])
    return [q[k] for k in sorted(q)]


def _main_eps(lpa):
    """LPA da ação mais negociada: PN quando existe (3.99.xx.02), senão ON."""
    if not lpa:
        return None
    d = dict(lpa)
    for c in sorted(d):
        if c.endswith(".02"):
            return d[c]
    return lpa[0][1]


def shares_out(kind, year, cnpj, offline=None):
    """{DT_REFER: ações em circulação (total - tesouraria)} do arquivo composicao_capital."""
    try:
        z = _zip(kind, year, offline)
    except cvm.CVMError:
        return {}
    out, ver = {}, {}
    try:
        for r in cvm.rows(z, contains="composicao_capital"):
            if cvm.digits(cvm.pick(r, "CNPJ_CIA")).zfill(14) != cnpj:
                continue
            ref = cvm.pick(r, "DT_REFER")
            v = int(float(cvm.pick(r, "VERSAO") or 0))
            if v < ver.get(ref, -1):
                continue
            ver[ref] = v
            n = cvm.num(cvm.pick(r, "QT_ACAO_TOTAL_CAP_INTEGR")) - cvm.num(cvm.pick(r, "QT_ACAO_TOTAL_TESOURO"))
            if n > 0:
                out[ref] = n
    except cvm.CVMError:
        return {}
    return out


def fill_eps(series, shares):
    """Quando a companhia não preenche o lucro por ação (vem zero), calcula lucro / ações em circulação.

    Fica marcado lpa_calculado: é o LPA total (todas as classes juntas), aproximado."""
    for s in series:
        if s.get("lpa") or s.get("lucro") is None:
            continue
        n = shares.get(s["fim"])
        if not n:
            near = [k for k in shares if k <= s["fim"]]
            n = shares[max(near)] if near else None
        if n:
            s["lpa"] = [("calc", s["lucro"] / n)]
            s["lpa_calculado"] = True
    return series


def analyse(series):
    """Acrescenta margens, crescimento contra o mesmo trimestre do ano anterior e últimos 12 meses."""
    by = {s["fim"]: s for s in series}
    for s in series:
        r = s["receita"]
        # holding (Itaúsa, BB Seguridade...): o lucro vem da equivalência patrimonial e passa da
        # receita; margem sobre a receita não faz sentido
        s["holding"] = bool(r and s["lucro"] is not None and s["lucro"] > r) or (not r and s["lucro"])
        if s["holding"]:
            r = None
        s["margem_bruta"] = 100 * s["lucro_bruto"] / r if r and s["lucro_bruto"] is not None else None
        s["margem_ebit"] = 100 * s["ebit"] / r if r and s["ebit"] is not None else None
        s["margem_liquida"] = 100 * s["lucro"] / r if r and s["lucro"] is not None else None
        s["lpa_principal"] = _main_eps(s["lpa"])
        prev = by.get("%d%s" % (int(s["fim"][:4]) - 1, s["fim"][4:]))
        for k, out in (("receita", "cresc_receita"), ("lucro", "cresc_lucro"), ("lpa_principal", "cresc_lpa")):
            a, b = s.get(k), (prev or {}).get(k)
            s[out] = 100 * (a / b - 1) if (a is not None and b not in (None, 0) and b > 0) else None
        s["um_off"] = (s["lucro"] is not None and s["ebit"] is not None and s["ebit"] > 0 and s["lucro"] > s["ebit"])
    if len(series) >= 4:
        last4 = series[-4:]
        ttm = {}
        for k in ("receita", "lucro", "lpa_principal"):
            vals = [x[k] for x in last4]
            ttm[k] = sum(vals) if all(v is not None for v in vals) else None
        return series, ttm
    return series, None


def company(ticker, year=None, offline=None, tmap=None):
    year = year or datetime.date.today().year
    t = b3.base(ticker)
    tmap = tmap or cvm.ticker_map(year, offline)
    info = tmap.get(t)
    if not info:
        raise AnalystError("%s não está no FCA da CVM (FIIs, ETFs e BDRs não entregam ITR/DFP de companhia aberta)" % t)
    cnpj = info["cnpj"].zfill(14)
    itr, dfp = [], []
    for y in (year, year - 1, year - 2):
        itr += dre_rows("ITR", y, {cnpj}, offline)
        dfp += dre_rows("DFP", y, {cnpj}, offline)
    series = quarterly(itr, dfp)
    if not series:
        raise AnalystError("sem ITR/DFP de %s (CNPJ %s) nos arquivos da CVM" % (t, cvm.fmt_cnpj(cnpj)))
    if any(not s.get("lpa") for s in series):
        shares = {}
        for y in (year, year - 1, year - 2):
            shares.update(shares_out("ITR", y, cnpj, offline))
            shares.update(shares_out("DFP", y, cnpj, offline))
        series = fill_eps(series, shares)
    series, ttm = analyse(series)
    return {"ticker": t, "cnpj": cvm.fmt_cnpj(cnpj), "nome": series[-1]["nome"], "series": series, "ttm": ttm}


def to_metrics(c):
    last = c["series"][-1]
    ttm = c["ttm"] or {}
    return {"ticker": c["ticker"], "name": c["nome"], "cnpj": c["cnpj"], "market": "br", "currency": "BRL",
            "period_end": last["fim"], "revenue_ttm": ttm.get("receita"), "net_income_ttm": ttm.get("lucro"),
            "eps_ttm": round(ttm["lpa_principal"], 4) if ttm.get("lpa_principal") is not None else None,
            "revenue_growth_yoy": None if last.get("holding") else _r(last["cresc_receita"]), "eps_growth_yoy": _r(last["cresc_lpa"]),
            "net_income_growth_yoy": _r(last["cresc_lucro"]), "gross_margin": _r(last["margem_bruta"]),
            "operating_margin": _r(last["margem_ebit"]), "net_margin": _r(last["margem_liquida"]),
            "financial_company": last["financeira"], "holding": bool(last.get("holding")),
            "eps_calculated": any(s.get("lpa_calculado") for s in c["series"][-4:]), "source": "CVM ITR/DFP (DRE consolidada)"}


def _r(x):
    return round(x, 1) if x is not None else None


def _pct(x):
    return ("%+.1f%%" % x).replace(".", ",") if x is not None else "n/d"


def _m(x):
    if x is None:
        return "n/d"
    a = abs(x)
    if a >= 1e9:
        s = "R$ %.2f bi" % (x / 1e9)
    elif a >= 1e6:
        s = "R$ %.1f mi" % (x / 1e6)
    else:
        return b3.money(x, "br", False)
    return s.replace(".", ",")


def render(c, n):
    lines = ["%s (%s), CNPJ %s. DRE consolidada, fonte CVM:" % (c["nome"], c["ticker"], c["cnpj"])]
    lines.append("  %-10s %14s %9s %13s %9s %8s %8s %8s %8s" % (
        "trimestre", "receita", "a/a", "lucro", "a/a", "LPA", "m.bruta", "m.EBIT", "m.líq"))
    for s in c["series"][-n:]:
        lines.append("  %-10s %14s %9s %13s %9s %8s %8s %8s %8s%s" % (
            s["fim"], _m(s["receita"]), _pct(s["cresc_receita"]), _m(s["lucro"]), _pct(s["cresc_lucro"]),
            ("%.2f" % s["lpa_principal"]).replace(".", ",") if s["lpa_principal"] is not None else "n/d",
            ("%.1f" % s["margem_bruta"]).replace(".", ",") if s["margem_bruta"] is not None else "-",
            ("%.1f" % s["margem_ebit"]).replace(".", ",") if s["margem_ebit"] is not None else "-",
            ("%.1f" % s["margem_liquida"]).replace(".", ",") if s["margem_liquida"] is not None else "-",
            "  derivado (DFP - 9M)" if s["derivado"] else ""))
    notes = []
    last = c["series"][-1]
    if last["financeira"]:
        notes.append("instituição financeira: sem margem bruta; receita é da intermediação financeira")
    if last.get("holding"):
        notes.append("holding ou seguradora: o lucro vem de participações (equivalência patrimonial) e não da "
                     "receita; margens e crescimento de receita não se aplicam")
    if any(s.get("lpa_calculado") for s in c["series"]):
        notes.append("LPA calculado (lucro / ações em circulação): a companhia não preencheu o lucro por ação")
    if last["um_off"] and not last.get("holding"):
        notes.append("lucro acima do EBIT no último trimestre: há resultado financeiro ou não recorrente relevante")
    if c["ttm"]:
        notes.append("últimos 12 meses: receita %s, lucro %s, LPA %s" % (
            _m(c["ttm"]["receita"]), _m(c["ttm"]["lucro"]),
            ("R$ %.2f" % c["ttm"]["lpa_principal"]).replace(".", ",") if c["ttm"]["lpa_principal"] is not None else "n/d"))
    for x in notes:
        lines.append("  nota: " + x)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="DRE trimestral pela CVM (trader-analyst, B3).")
    ap.add_argument("tickers", nargs="+", help="tickers da B3, ou 'colunas'")
    ap.add_argument("--trimestres", type=int, default=4)
    ap.add_argument("--ano", type=int, help="ano mais recente a ler (padrão: o atual)")
    ap.add_argument("--metrics", help="grava as métricas para o trader-screener neste arquivo")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    year = a.ano or datetime.date.today().year
    try:
        if a.tickers == ["colunas"]:
            for kind in ("ITR", "DFP", "FCA"):
                try:
                    z = _zip(kind, year if kind != "DFP" else year - 1, a.offline)
                except cvm.CVMError as e:
                    print("%s: %s" % (kind, e))
                    continue
                for n in cvm.members(z, "dre_con" if kind != "FCA" else "valor_mobiliario"):
                    print("%s: %s" % (n, ";".join(cvm.header(z, member=n))))
            return 0
        tmap = cvm.ticker_map(year, a.offline)
        results, errors = [], []
        for t in a.tickers:
            try:
                results.append(company(t, year, a.offline, tmap))
            except AnalystError as e:
                errors.append(str(e))
    except cvm.CVMError as e:
        print("demonstracoes.py: %s" % e, file=sys.stderr)
        return 1
    if a.metrics and results:
        d = os.path.dirname(a.metrics)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.metrics, "w", encoding="utf-8") as fh:
            json.dump({"as_of": datetime.date.today().isoformat(), "market": "br",
                       "companies": [to_metrics(c) for c in results]}, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    if a.json:
        print(json.dumps({"empresas": results, "erros": errors}, indent=2, ensure_ascii=False, default=str))
    else:
        for c in results:
            print(render(c, a.trimestres))
            print("")
        for e in errors:
            print("erro: " + e)
        if a.metrics and results:
            print("Gravei %d empresas em %s." % (len(results), a.metrics))
        print("Números da DRE entregue à CVM. Para contexto (guidance, segmentos), leia o release no IPE.")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
