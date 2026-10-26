#!/usr/bin/env python3
"""Carteira de fundos brasileiros pela CDA da CVM (trader-copycat, mercado BR).

A CDA (Composição e Diversificação das Aplicações) é a carteira que todo fundo
entrega à CVM todo mês. Esta ferramenta lê a CDA mensal nos dados abertos da
CVM, acha o fundo, soma as ações (e units, FIIs, ETFs, BDRs) que ele tinha no
fim do mês e transforma isso em pesos para copiar.

    python3 fundos.py busca "dynamo cougar"          # nome -> CNPJ (no mês mais recente)
    python3 fundos.py meses                          # que meses a CDA já tem
    python3 fundos.py carteira <CNPJ> --top 15
    python3 fundos.py diff <CNPJ>        # o que mudou contra o mês anterior
    python3 fundos.py copiar <CNPJ> --top 5 --out trader/targets.json
    python3 fundos.py colunas --mes 202609           # cabeçalhos dos CSVs (para depurar)

O que a CDA NÃO mostra:
  - posições que o fundo pediu para manter em sigilo: a CVM permite adiar a
    divulgação por meses (na CDA de 07/2026, grandes fundos de ações estavam
    em sigilo até 01/2027). Elas aparecem agregadas no arquivo CONFID, sem o
    ativo, com a data de liberação; a ferramenta avisa o valor e a data. Sem
    --mes, ela volta mês a mês até achar a carteira mais recente já revelada
  - o que foi comprado e vendido dentro do mês, ou o preço pago
  - fundos que investem via fundo master: o FIC tem cotas do master. Com
    --seguir-master (o padrão) a ferramenta segue para a carteira do master

Arquivos: https://dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS/cda_fi_AAAAMM.zip
(meses desde 2021; antes disso em .../HIST/). CSVs em latin-1, separados por ";".
"""

import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import b3  # noqa: E402
import cvm  # noqa: E402

COL_CNPJ = ("CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO")
COL_NAME = ("DENOM_SOCIAL", "NOME_FUNDO", "DENOM_SOCIAL_FUNDO")
COL_DATE = ("DT_COMPTC",)
COL_APLIC = ("TP_APLIC",)
COL_ATIVO = ("TP_ATIVO",)
COL_CODE = ("CD_ATIVO", "CD_ATIVO_BV")
COL_DESC = ("DS_ATIVO",)
COL_QTY = ("QT_POS_FINAL",)
COL_VALUE = ("VL_MERC_POS_FINAL",)
COL_PL = ("VL_PATRIM_LIQ",)
COL_COTA_CNPJ = ("CNPJ_FUNDO_CLASSE_COTA", "CNPJ_FUNDO_COTA")
COL_COTA_NAME = ("NM_FUNDO_CLASSE_SUBCLASSE_COTA", "NM_FUNDO_CLASSE_COTA", "NM_FUNDO_COTA")

# aplicações que contam como posição comprada à vista (TP_APLIC, sem acento e em minúsculas).
# Lidas na CDA real de 07/2026. Fica fora: debêntures (que têm códigos como CSAN33, parecidos
# com BDR), opções, futuros, termo, aluguel tomado ("obrigações por ações ... recebidos em
# empréstimo"), bônus e recibos de subscrição.
EQUITY_APLIC = ("acoes", "acoes e outros tvm cedidos em emprestimo",
                "certificado ou recibo de deposito de valores mobiliarios",
                "brazilian depository receipt - bdr")

CAVEATS = [
    "A CDA é a carteira do último dia do mês, entregue à CVM semanas depois: não é a carteira de hoje.",
    "Posições em sigilo (muitas vezes por 3 a 6 meses) não aparecem ativo por ativo; a CVM publica a data de liberação.",
    "Só a ponta comprada à vista: sem opções, futuros, termo, aluguel tomado, caixa ou crédito.",
    "Copiar a carteira de um fundo não copia o resultado dele: você compra depois, ao preço de hoje.",
]


class FundError(Exception):
    pass


def month_list(start=None, n=12):
    d = (start or datetime.date.today()).replace(day=1)
    out = []
    for _ in range(n):
        d = (d - datetime.timedelta(days=1)).replace(day=1)
        out.append(d.strftime("%Y%m"))
    return out


def cda_zip(month, offline=None):
    return cvm.download("FI/DOC/CDA/DADOS/cda_fi_%s.zip" % month, max_age=24 * 7, offline=offline)


def latest_month(offline=None, tries=6):
    errs = []
    for m in month_list(n=tries):
        try:
            cda_zip(m, offline)
            return m
        except cvm.CVMError as e:
            errs.append(str(e))
    raise FundError("não achei CDA nos últimos %d meses: %s" % (tries, errs[-1] if errs else ""))


def block(zpath, n, month):
    return cvm.rows(zpath, contains="cda_fi_blc_%d_%s" % (n, month))


def _cnpj_key(text):
    return cvm.digits(text).zfill(14)


def search(month, query, offline=None, limit=20):
    """Fundos cujo nome contém todas as palavras de `query` (sem acento), com PL."""
    z = cda_zip(month, offline)
    words = cvm.fold(query).split()
    found = {}
    for r in cvm.rows(z, contains="cda_fi_pl_%s" % month):
        name = cvm.pick(r, *COL_NAME) or ""
        if all(w in cvm.fold(name) for w in words):
            k = _cnpj_key(cvm.need(r, *COL_CNPJ))
            found[k] = {"cnpj": cvm.fmt_cnpj(k), "nome": name, "pl": cvm.num(cvm.pick(r, *COL_PL)),
                        "data": cvm.pick(r, *COL_DATE)}
    return sorted(found.values(), key=lambda f: -f["pl"])[:limit]


def _ticker_from(row):
    code = str(cvm.pick(row, *COL_CODE, default="") or "").strip().upper()
    if code and b3.is_b3(code):
        return b3.base(code)
    desc = str(cvm.pick(row, *COL_DESC, default="") or "").upper()
    for tok in re.findall(r"\b[A-Z0-9]{4}\d{1,2}\b", desc):
        if b3.is_b3(tok):
            return b3.base(tok)
    return None


def holdings(month, cnpj, offline=None, follow_master=True, _depth=0):
    """Carteira em ativos da B3 de um fundo num mês. Segue o master quando o fundo é FIC."""
    z = cda_zip(month, offline)
    key = _cnpj_key(cnpj)
    name, dt, pl = "", "", 0.0
    for r in cvm.rows(z, contains="cda_fi_pl_%s" % month):
        if _cnpj_key(cvm.pick(r, *COL_CNPJ)) == key:
            name, dt, pl = cvm.pick(r, *COL_NAME) or "", cvm.pick(r, *COL_DATE) or "", cvm.num(cvm.pick(r, *COL_PL))
            break
    pos, skipped = {}, []
    for n in (4, 8):
        try:
            it = block(z, n, month)
            for r in it:
                if _cnpj_key(cvm.pick(r, *COL_CNPJ)) != key:
                    continue
                name = name or cvm.pick(r, *COL_NAME) or ""
                dt = dt or cvm.pick(r, *COL_DATE) or ""
                aplic = cvm.fold(cvm.pick(r, *COL_APLIC) or "")
                value = cvm.num(cvm.pick(r, *COL_VALUE))
                tk = _ticker_from(r)
                if aplic not in EQUITY_APLIC or not tk:
                    # "fora da cópia" lista só ativos com código (debêntures, opções, termo, aluguel);
                    # caixa, valores a pagar e a receber não entram nessa conta
                    if value and (cvm.pick(r, *COL_CODE) or tk):
                        skipped.append({"ativo": cvm.pick(r, *COL_CODE) or cvm.pick(r, *COL_DESC) or "?",
                                        "aplicacao": cvm.pick(r, *COL_APLIC) or "", "valor": value})
                    continue
                p = pos.setdefault(tk, {"ticker": tk, "qty": 0.0, "value": 0.0,
                                        "desc": cvm.pick(r, *COL_DESC) or "", "aplic": set()})
                p["qty"] += cvm.num(cvm.pick(r, *COL_QTY))
                p["value"] += value
                p["aplic"].add(cvm.pick(r, *COL_APLIC) or "")
        except cvm.CVMError:
            if n == 4:
                raise
    # FIC: a maior parte do patrimônio em cotas de um único fundo (o master)?
    master = None
    if follow_master and _depth < 2:
        best = None
        for r in block(z, 2, month):
            if _cnpj_key(cvm.pick(r, *COL_CNPJ)) != key:
                continue
            v = cvm.num(cvm.pick(r, *COL_VALUE))
            if best is None or v > best[0]:
                best = (v, cvm.pick(r, *COL_COTA_CNPJ), cvm.pick(r, *COL_COTA_NAME) or "")
        equity = sum(p["value"] for p in pos.values())
        if best and best[1] and best[0] > max(equity, 0.5 * pl if pl else 0):
            master = {"cnpj": cvm.fmt_cnpj(best[1]), "nome": best[2], "valor": best[0]}
            inner = holdings(month, best[1], offline, follow_master, _depth + 1)
            inner["via"] = {"cnpj": cvm.fmt_cnpj(key), "nome": name, "pl": pl, "master": master}
            return inner
    confid, confid_until = confidential(z, month, key)
    rows = sorted(pos.values(), key=lambda p: -p["value"])
    total = sum(p["value"] for p in rows)
    for p in rows:
        p["aplic"] = sorted(a for a in p["aplic"] if a)
        p["pct_b3"] = 100.0 * p["value"] / total if total else 0.0
        p["pct_pl"] = 100.0 * p["value"] / pl if pl else None
        kind, guess = b3.asset_type(p["ticker"])
        p["tipo"], p["tipo_suposto"] = kind, guess
    return {"cnpj": cvm.fmt_cnpj(key), "nome": name, "data": dt, "mes": month, "pl": pl,
            "total_b3": total, "confidencial": confid, "sigilo_ate": confid_until, "posicoes": rows,
            "fora": skipped, "master": master}


def confidential(z, month, key):
    """(valor em ações/BDRs em sigilo, data de liberação mais distante) de um fundo num mês."""
    total, until = 0.0, ""
    try:
        for r in cvm.rows(z, contains="cda_fi_confid_%s" % month):
            if _cnpj_key(cvm.pick(r, *COL_CNPJ)) != key:
                continue
            if cvm.fold(cvm.pick(r, *COL_APLIC) or "") in EQUITY_APLIC:
                total += cvm.num(cvm.pick(r, *COL_VALUE))
                until = max(until, str(cvm.pick(r, "DT_CONFID_APLIC", default="") or ""))
    except cvm.CVMError:
        pass
    return total, until


def diff(new, old):
    a = {p["ticker"]: p for p in old["posicoes"]}
    b = {p["ticker"]: p for p in new["posicoes"]}
    out = {"novas": [], "zeradas": [], "aumentou": [], "reduziu": []}
    for t in b:
        if t not in a:
            out["novas"].append((t, b[t]["qty"]))
        elif b[t]["qty"] > a[t]["qty"] * 1.0001:
            out["aumentou"].append((t, a[t]["qty"], b[t]["qty"]))
        elif b[t]["qty"] < a[t]["qty"] * 0.9999:
            out["reduziu"].append((t, a[t]["qty"], b[t]["qty"]))
    for t in a:
        if t not in b:
            out["zeradas"].append((t, a[t]["qty"]))
    return out


def targets(h, top=None, exclude=(), min_pct=0.0):
    ex = {b3.base(e) for e in exclude}
    rows = [p for p in h["posicoes"] if p["ticker"] not in ex and p["pct_b3"] >= min_pct]
    if top:
        rows = rows[:top]
    tot = sum(p["value"] for p in rows)
    weights = []
    for p in rows:
        weights.append({"ticker": p["ticker"], "name": p["desc"], "weight": round(100.0 * p["value"] / tot, 2),
                        "pct_carteira_b3": round(p["pct_b3"], 2),
                        "pct_pl": round(p["pct_pl"], 2) if p["pct_pl"] is not None else None,
                        "value": round(p["value"], 2), "shares": p["qty"], "asset_type": p["tipo"]})
    if weights:
        drift = round(100.0 - sum(w["weight"] for w in weights), 2)
        weights[0]["weight"] = round(weights[0]["weight"] + drift, 2)
    via = h.get("via")
    src = "%s (CNPJ %s), CDA de %s" % (h["nome"], h["cnpj"], h["data"] or h["mes"])
    if via:
        src = "%s (CNPJ %s) via master %s (CNPJ %s), CDA de %s" % (via["nome"], via["cnpj"], h["nome"], h["cnpj"],
                                                                    h["data"] or h["mes"])
    return {"source": src, "market": "br", "as_of": h["data"] or h["mes"], "cnpj": h["cnpj"],
            "method": "%s posições em ativos da B3 por valor de mercado, escaladas para 100" % (
                "top %d" % top if top else "todas as"),
            "weights": weights, "excluded": sorted(ex), "caveats": CAVEATS,
            "confidencial": round(h["confidencial"], 2)}


# ---------------------------------------------------------------- saída

R = lambda x: b3.money(x, "br", False)  # noqa: E731


def show(h, top):
    lines = []
    via = h.get("via")
    if via:
        lines.append("%s (CNPJ %s) é um FIC: %s do patrimônio está no master %s (CNPJ %s)."
                     % (via["nome"], via["cnpj"], R(via["master"]["valor"]), h["nome"], h["cnpj"]))
    lines.append("%s, CNPJ %s, carteira de %s. PL %s; ativos da B3 %s (%s do PL)." % (
        h["nome"], h["cnpj"], h["data"] or h["mes"], R(h["pl"]), R(h["total_b3"]),
        ("%.1f%%" % (100.0 * h["total_b3"] / h["pl"])) if h["pl"] else "?"))
    lines.append("")
    lines.append("%-3s %-7s %-5s %12s %16s %8s %8s" % ("#", "ticker", "tipo", "qtd", "valor", "% B3", "% PL"))
    for i, p in enumerate(h["posicoes"][:top] if top else h["posicoes"], 1):
        lines.append("%-3d %-7s %-5s %12s %16s %7.2f%% %7s" % (
            i, p["ticker"], b3.TYPE_NAMES.get(p["tipo"], "?")[:5], "{:,.0f}".format(p["qty"]).replace(",", "."),
            R(p["value"]), p["pct_b3"], ("%.2f%%" % p["pct_pl"]) if p["pct_pl"] is not None else "?"))
    if h["confidencial"]:
        lines.append("")
        lines.append("Em sigilo: %s em ações e BDRs que o fundo ainda não revelou%s." % (
            R(h["confidencial"]), (" (liberação prevista em %s)" % h["sigilo_ate"]) if h.get("sigilo_ate") else ""))
    for sk in h.get("meses_em_sigilo", []):
        lines.append("Mês %s pulado: carteira em sigilo%s." % (
            sk["mes"], (" até %s" % sk["ate"]) if sk.get("ate") else ""))
    if h["fora"]:
        tot = sum(s["valor"] for s in h["fora"])
        lines.append("Fora da cópia: %d linhas (%s) de debêntures, opções, futuros, termo, aluguel tomado ou ativos sem ticker." % (
            len(h["fora"]), R(tot)))
    lines.append("")
    lines.extend(CAVEATS[:2])
    return "\n".join(lines)


def cmd_busca(a):
    month = a.mes or latest_month(a.offline)
    res = search(month, a.nome, a.offline)
    if a.json:
        print(json.dumps({"mes": month, "fundos": res}, indent=2, ensure_ascii=False))
        return 0 if res else 1
    if not res:
        print("Nenhum fundo com %r na CDA de %s." % (a.nome, month))
        return 1
    print("CDA de %s:" % month)
    for f in res:
        print("  %s  %-60s PL %s" % (f["cnpj"], f["nome"][:60], R(f["pl"])))
    print("Escolha o CNPJ da classe que você quer copiar (FICs são seguidos até o master).")
    return 0


def cmd_meses(a):
    ok = []
    for m in month_list(n=a.n):
        try:
            cda_zip(m, a.offline)
            ok.append(m)
        except cvm.CVMError:
            pass
    print("CDA disponível: %s" % (", ".join(ok) or "nenhum mês encontrado"))
    return 0 if ok else 1


def _hold(a, month=None, back=9):
    """Carteira do mês pedido; sem mês, a mais recente já revelada (volta até `back` meses)."""
    fixed = month or a.mes
    month = fixed or latest_month(a.offline)
    skipped = []
    for _ in range(1 if fixed else back):
        try:
            h = holdings(month, a.cnpj, a.offline, not a.sem_master)
        except cvm.CVMError:
            h = None
        if h and h["posicoes"]:
            h["meses_em_sigilo"] = skipped
            return h
        val, until = (0.0, "")
        try:
            val, until = confidential(cda_zip(month, a.offline), month, _cnpj_key(a.cnpj))
        except cvm.CVMError:
            pass
        skipped.append({"mes": month, "ate": until, "valor": val})
        month = _prev(month)
    raise FundError("o fundo %s não tem ativos da B3 revelados na CDA %s (sigilo, CNPJ errado ou não é fundo "
                    "de ações; use busca)" % (cvm.fmt_cnpj(a.cnpj),
                                              ("de " + fixed) if fixed else "dos últimos %d meses" % back))


def cmd_carteira(a):
    h = _hold(a)
    if a.json:
        print(json.dumps(h, indent=2, ensure_ascii=False, default=list))
    else:
        print(show(h, a.top))
    return 0


def _prev(month):
    d = datetime.date(int(month[:4]), int(month[4:]), 1) - datetime.timedelta(days=1)
    return d.strftime("%Y%m")


def cmd_diff(a):
    month = a.mes or latest_month(a.offline)
    new = _hold(a, month)
    old = _hold(a, a.contra or _prev(month))
    d = diff(new, old)
    if a.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
        return 0
    print("%s: %s contra %s (quantidade no fim de cada mês, não negócios com data)." % (
        new["nome"], new["data"] or month, old["data"] or old["mes"]))
    f = lambda q: "{:,.0f}".format(q).replace(",", ".")  # noqa: E731
    for t, q in d["novas"]:
        print("  NOVA     %-7s %s" % (t, f(q)))
    for t, q in d["zeradas"]:
        print("  ZERADA   %-7s era %s" % (t, f(q)))
    for t, x, y in d["aumentou"]:
        print("  AUMENTOU %-7s %s -> %s" % (t, f(x), f(y)))
    for t, x, y in d["reduziu"]:
        print("  REDUZIU  %-7s %s -> %s" % (t, f(x), f(y)))
    print("Uma posição pode 'sumir' por ter entrado em sigilo, não só por ter sido vendida.")
    return 0


def cmd_copiar(a):
    h = _hold(a)
    t = targets(h, a.top, a.excluir or [], a.min_pct)
    d = os.path.dirname(a.out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(t, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(show(h, a.top))
    print("")
    print("Pesos para copiar (%s):" % t["method"])
    for w in t["weights"]:
        print("  %-7s %6.2f%%" % (w["ticker"], w["weight"]))
    print("Gravei %s. Próximo: trader-budget dimensiona para o seu orçamento." % a.out)
    return 0


def cmd_colunas(a):
    month = a.mes or latest_month(a.offline)
    z = cda_zip(month, a.offline)
    for name in cvm.members(z, ""):
        print("%s: %s" % (name, ";".join(cvm.header(z, member=name))))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Carteira de fundos pela CDA da CVM (trader-copycat, B3).")
    ap.add_argument("--offline", metavar="DIR", help="lê os zips de DIR, sem rede (testes)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("busca")
    p.add_argument("nome")
    p.add_argument("--mes")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("meses")
    p.add_argument("--n", type=int, default=6)
    for name in ("carteira", "diff", "copiar"):
        p = sub.add_parser(name)
        p.add_argument("cnpj")
        p.add_argument("--mes", help="AAAAMM (padrão: o mais recente publicado)")
        p.add_argument("--top", type=int)
        p.add_argument("--sem-master", action="store_true", help="não seguir o fundo master de um FIC")
        p.add_argument("--json", action="store_true")
        if name == "diff":
            p.add_argument("--contra", help="AAAAMM a comparar (padrão: o mês anterior)")
        if name == "copiar":
            p.add_argument("--out", default="trader/targets.json")
            p.add_argument("--excluir", nargs="*")
            p.add_argument("--min-pct", type=float, default=0.0)
    p = sub.add_parser("colunas")
    p.add_argument("--mes")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"busca": cmd_busca, "meses": cmd_meses, "carteira": cmd_carteira, "diff": cmd_diff,
                "copiar": cmd_copiar, "colunas": cmd_colunas}[a.cmd](a)
    except (FundError, cvm.CVMError) as e:
        print("fundos.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
