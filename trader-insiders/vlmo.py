#!/usr/bin/env python3
"""Negociações de insiders na B3 pelos dados abertos da CVM (trader-insiders).

Controladores, conselheiros, diretores e membros de órgãos técnicos de toda
companhia aberta precisam informar, todo mês, o que compraram e venderam de
ações da própria empresa (Resolução CVM 44, art. 11: até 10 dias depois do
fim do mês). A CVM publica isso no conjunto "Valores Mobiliários Negociados e
Detidos" (VLMO). Esta ferramenta lê o VLMO, acha os documentos novos desde a
última checagem e resume compras e vendas por grupo e por empresa.

    python3 vlmo.py novos                            # documentos novos desde a última vez
    python3 vlmo.py novos --tickers PETR4 VALE3      # só dessas empresas
    python3 vlmo.py novos --carteira                 # só de quem você tem ou vai copiar
    python3 vlmo.py empresa WEGE3 --ano 2026         # mês a mês de uma empresa
    python3 vlmo.py ranking --mes 2026-09            # maiores compras e vendas líquidas do mês
    python3 vlmo.py colunas                          # cabeçalhos dos CSVs (para depurar)

Rápido, não antecipado: o informe sai até 10 dias depois do mês fechado, e a
CVM publica o arquivo em seguida (atualização semanal). As negociações têm de
1 a 40 dias quando aparecem. Os dados são agregados por GRUPO (controlador,
conselho, diretoria...), não por pessoa. Nada aqui é informação privilegiada:
são informes públicos, lidos depressa.

Arquivo: https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS/vlmo_cia_aberta_AAAA.zip
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import b3  # noqa: E402
import cvm  # noqa: E402

COL = {
    "cnpj": ("CNPJ_Companhia", "CNPJ_CIA"),
    "nome": ("Nome_Companhia", "DENOM_CIA"),
    "ref": ("Data_Referencia", "DT_REFER"),
    "versao": ("Versao", "VERSAO"),
    "cargo": ("Tipo_Cargo", "Cargo", "Tipo_Empresa"),
    "empresa": ("Empresa", "Tipo_Empresa"),
    "mov": ("Tipo_Movimentacao", "Movimentacao", "Descricao_Movimentacao"),
    "oper": ("Tipo_Operacao", "Operacao"),
    "ativo": ("Tipo_Ativo", "Valor_Mobiliario"),
    "carac": ("Caracteristica_Valor_Mobiliario", "Caracteristica", "Especie"),
    "data": ("Data_Movimentacao", "Data_Operacao"),
    "qtd": ("Quantidade",),
    "preco": ("Preco_Unitario", "Preco"),
    "volume": ("Volume", "Valor"),
}


class VLMOError(Exception):
    pass


def zip_for(year, offline=None):
    return cvm.download("CIA_ABERTA/DOC/VLMO/DADOS/vlmo_cia_aberta_%d.zip" % year, max_age=24, offline=offline)


def g(row, key, default=""):
    v = cvm.pick(row, *COL[key])
    return default if v is None else v


def kind_of(row):
    """'compra', 'venda' ou 'outro' a partir do tipo de movimentação e da operação."""
    mov = cvm.fold(g(row, "mov"))
    op = cvm.fold(g(row, "oper"))
    if "saldo" in mov:
        return "saldo"
    if "compra" in mov or "aquisicao" in mov:
        return "compra"
    if "venda" in mov or "alienacao" in mov:
        return "venda"
    if op.startswith("credito") or op == "c":
        return "outro+"
    if op.startswith("debito") or op == "d":
        return "outro-"
    return "outro"


def is_share(row):
    a = cvm.fold(g(row, "ativo"))
    return (not a) or "acao" in a or "acoes" in a or "unit" in a or "certificado" in a


def load(year, offline=None):
    """Linhas do arquivo consolidado (movimentações), normalizadas."""
    z = zip_for(year, offline)
    names = cvm.members(z, "_con_") or cvm.members(z, "vlmo")
    names = [n for n in names if n.lower().endswith(".csv")]
    if not names:
        raise VLMOError("não achei o CSV de movimentações dentro de %s" % z)
    out = []
    for r in cvm.rows(z, member=sorted(names, key=lambda n: ("_con_" not in n, len(n)))[0]):
        k = kind_of(r)
        out.append({
            "cnpj": cvm.digits(g(r, "cnpj")).zfill(14), "nome": g(r, "nome"),
            "ref": str(g(r, "ref"))[:10], "versao": str(g(r, "versao")), "cargo": g(r, "cargo"),
            "empresa": g(r, "empresa"), "mov": g(r, "mov"), "tipo": k, "acao": is_share(r),
            "carac": g(r, "carac"), "data": str(g(r, "data"))[:10],
            "qtd": abs(cvm.num(g(r, "qtd"))), "preco": cvm.num(g(r, "preco")),
            "volume": abs(cvm.num(g(r, "volume"))),
        })
    return out


def latest_versions(rows):
    """Só a versão mais recente de cada (empresa, mês): reapresentações substituem a original."""
    best = {}
    for r in rows:
        k = (r["cnpj"], r["ref"])
        try:
            v = int(float(r["versao"] or 0))
        except ValueError:
            v = 0
        best[k] = max(best.get(k, -1), v)
    out = []
    for r in rows:
        try:
            v = int(float(r["versao"] or 0))
        except ValueError:
            v = 0
        if v == best[(r["cnpj"], r["ref"])]:
            out.append(r)
    return out


def summarize(rows):
    """{(cnpj, ref): {"nome", "grupos": {cargo: {compra_qtd, compra_vol, venda_qtd, venda_vol, outros}}}}"""
    docs = {}
    for r in rows:
        if not r["acao"] or r["tipo"] == "saldo":
            continue
        d = docs.setdefault((r["cnpj"], r["ref"]), {"cnpj": r["cnpj"], "nome": r["nome"], "ref": r["ref"],
                                                   "versao": r["versao"], "grupos": {}, "datas": set()})
        grp = d["grupos"].setdefault(r["cargo"] or "?", {"compra_qtd": 0.0, "compra_vol": 0.0, "venda_qtd": 0.0,
                                                         "venda_vol": 0.0, "outros": 0})
        if r["tipo"] == "compra":
            grp["compra_qtd"] += r["qtd"]
            grp["compra_vol"] += r["volume"] or r["qtd"] * r["preco"]
        elif r["tipo"] == "venda":
            grp["venda_qtd"] += r["qtd"]
            grp["venda_vol"] += r["volume"] or r["qtd"] * r["preco"]
        else:
            grp["outros"] += 1
        if r["data"]:
            d["datas"].add(r["data"])
    for d in docs.values():
        d["datas"] = sorted(d["datas"])
        d["compra_vol"] = sum(x["compra_vol"] for x in d["grupos"].values())
        d["venda_vol"] = sum(x["venda_vol"] for x in d["grupos"].values())
        d["liquido"] = d["compra_vol"] - d["venda_vol"]
    return docs


def load_state(path):
    if not os.path.exists(path):
        return {"vistos": {}}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_state(path, st):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def wanted_cnpjs(a):
    """CNPJs das empresas filtradas por --tickers ou --carteira (via FCA da CVM)."""
    tickers = [b3.base(t) for t in (a.tickers or [])]
    if a.carteira:
        for path, key in ((a.portfolio, "positions"), (a.targets, "weights")):
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    doc = json.load(fh)
                tickers += [b3.base(p.get("ticker") or p.get("symbol") or "") for p in doc.get(key, [])]
    tickers = [t for t in dict.fromkeys(tickers) if t]
    if not tickers:
        return None, {}
    tmap = cvm.ticker_map(a.ano or datetime.date.today().year, a.offline)
    out, names = set(), {}
    missing = []
    for t in tickers:
        info = tmap.get(t)
        if not info:
            missing.append(t)
            continue
        out.add(info["cnpj"].zfill(14))
        names.setdefault(info["cnpj"].zfill(14), []).append(t)
    if missing:
        print("Sem companhia aberta no FCA para: %s (FIIs, ETFs e BDRs não entregam este informe)"
              % ", ".join(missing))
    return out, names


R = lambda x: b3.money(x, "br", False)  # noqa: E731


def _q(x):
    return "{:,.0f}".format(x).replace(",", ".")


def render(d, tick_names=None):
    tk = "/".join((tick_names or {}).get(d["cnpj"], []))
    lines = ["%s%s, mês %s (versão %s), CNPJ %s" % (d["nome"], (" (%s)" % tk) if tk else "", d["ref"][:7],
                                                   d["versao"], cvm.fmt_cnpj(d["cnpj"]))]
    for cargo, x in sorted(d["grupos"].items(), key=lambda kv: -(kv[1]["compra_vol"] + kv[1]["venda_vol"])):
        parts = []
        if x["compra_qtd"]:
            parts.append("comprou %s ações (%s)" % (_q(x["compra_qtd"]), R(x["compra_vol"])))
        if x["venda_qtd"]:
            parts.append("vendeu %s ações (%s)" % (_q(x["venda_qtd"]), R(x["venda_vol"])))
        if x["outros"] and not parts:
            parts.append("%d movimentações que não são compra ou venda (bonificação, plano de ações...)" % x["outros"])
        if parts:
            lines.append("  - %s: %s" % (cargo, "; ".join(parts)))
    if d["datas"]:
        lines.append("  negócios entre %s e %s" % (d["datas"][0], d["datas"][-1]))
    return "\n".join(lines)


def cmd_novos(a):
    year = a.ano or datetime.date.today().year
    rows = latest_versions(load(year, a.offline))
    if datetime.date.today().month == 1 and not a.ano:
        try:
            rows += latest_versions(load(year - 1, a.offline))
        except cvm.CVMError:
            pass
    docs = summarize(rows)
    cnpjs, names = wanted_cnpjs(a)
    st = load_state(a.state)
    seen = st.setdefault("vistos", {})
    first_run = not seen
    cutoff = (datetime.date.today() - datetime.timedelta(days=62)).isoformat()
    new = []
    for k, d in sorted(docs.items(), key=lambda kv: kv[0][1], reverse=True):
        if cnpjs is not None and d["cnpj"] not in cnpjs:
            continue
        key = "%s|%s" % k
        if seen.get(key) == d["versao"]:
            continue
        if first_run and d["ref"] < cutoff and not a.tudo:
            seen[key] = d["versao"]
            continue
        if not (d["compra_vol"] or d["venda_vol"]) and not a.tudo:
            seen[key] = d["versao"]
            continue
        new.append(d)
        seen[key] = d["versao"]
    if not a.dry_run:
        st["ultima_checagem"] = datetime.datetime.now().replace(microsecond=0).isoformat()
        save_state(a.state, st)
    if a.json:
        print(json.dumps(new, indent=2, ensure_ascii=False))
        return 0 if new else 1
    if not new:
        print("Nada novo com compra ou venda de insiders%s." % (" nas suas empresas" if cnpjs is not None else ""))
        return 1
    for d in new[:a.limite]:
        print("NOVO " + render(d, names))
        print("")
    if len(new) > a.limite:
        print("... e mais %d documentos (use --limite ou filtre com --tickers)." % (len(new) - a.limite))
    print("Informes públicos da CVM, entregues até 10 dias depois do mês. Dizem o que o grupo negociou, "
          "não o que vai acontecer.")
    return 0


def cmd_empresa(a):
    year = a.ano or datetime.date.today().year
    tmap = cvm.ticker_map(year, a.offline)
    t = b3.base(a.ticker)
    info = tmap.get(t)
    if not info:
        raise VLMOError("%s não está no FCA da CVM como companhia aberta (FII, ETF ou BDR não entregam)" % t)
    docs = summarize(latest_versions(load(year, a.offline)))
    mine = [d for d in docs.values() if d["cnpj"] == info["cnpj"].zfill(14)]
    if not mine:
        print("Nenhum informe de %s em %d." % (t, year))
        return 1
    for d in sorted(mine, key=lambda d: d["ref"]):
        print(render(d, {d["cnpj"]: [t]}))
    return 0


def cmd_ranking(a):
    year = int(a.mes[:4]) if a.mes else (a.ano or datetime.date.today().year)
    docs = summarize(latest_versions(load(year, a.offline)))
    mes = a.mes or max(d["ref"][:7] for d in docs.values())
    rows = [d for d in docs.values() if d["ref"][:7] == mes and (d["compra_vol"] or d["venda_vol"])]
    rows.sort(key=lambda d: d["liquido"])
    print("Insiders em %s, saldo líquido (compras - vendas):" % mes)
    print("  Mais vendas:")
    for d in rows[:a.n]:
        if d["liquido"] < 0:
            print("    %-45s %s" % (d["nome"][:45], R(d["liquido"])))
    print("  Mais compras:")
    for d in reversed(rows[-a.n:]):
        if d["liquido"] > 0:
            print("    %-45s %s" % (d["nome"][:45], R(d["liquido"])))
    print("Venda de insider tem muitos motivos (impostos, diversificação, plano de ações): não é sinal por si só.")
    return 0


def cmd_colunas(a):
    z = zip_for(a.ano or datetime.date.today().year, a.offline)
    for n in cvm.members(z, ""):
        print("%s: %s" % (n, ";".join(cvm.header(z, member=n))))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Negociações de insiders (VLMO da CVM), trader-insiders.")
    ap.add_argument("--offline", metavar="DIR")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("novos")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--carteira", action="store_true", help="filtra por trader/portfolio.json e trader/targets.json")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--targets", default="trader/targets.json")
    p.add_argument("--state", default="trader/state/insiders.json")
    p.add_argument("--ano", type=int)
    p.add_argument("--tudo", action="store_true", help="mostra também documentos antigos e sem compra/venda")
    p.add_argument("--limite", type=int, default=30)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("empresa")
    p.add_argument("ticker")
    p.add_argument("--ano", type=int)
    p = sub.add_parser("ranking")
    p.add_argument("--mes", help="AAAA-MM")
    p.add_argument("--ano", type=int)
    p.add_argument("--n", type=int, default=10)
    p = sub.add_parser("colunas")
    p.add_argument("--ano", type=int)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"novos": cmd_novos, "empresa": cmd_empresa, "ranking": cmd_ranking, "colunas": cmd_colunas}[a.cmd](a)
    except (VLMOError, cvm.CVMError) as e:
        print("vlmo.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
