#!/usr/bin/env python3
"""Imposto de renda de renda variável para pessoa física residente no Brasil.
Só biblioteca padrão, sem rede. Faz a conta; não é assessoria tributária.

    python3 ir_br.py apurar --ano 2026                 # mês a mês: resultado, isenção, prejuízo, DARF
    python3 ir_br.py apurar --ano 2026 --mes 10 --json
    python3 ir_br.py posicao --em 2026-12-31           # preço médio e custo para Bens e Direitos
    python3 ir_br.py prejuizo --precos trader/prices.json   # posições no prejuízo (para realizar)
    python3 ir_br.py exterior --ano 2026 --trades exterior.csv  # ações nos EUA, Lei 14.754/2023

Entradas:
  trader/portfolio.json   "trades" (cada execução: date, ticker, side, qty, price, fees), gravados
                          pelo trader-broker (ticket.py fill), e "opening" (posições que você já
                          tinha antes: ticker, shares, cost); ou --trades arquivo.csv com as colunas
                          data;ticker;lado;quantidade;preco;taxas (lado: C/V ou compra/venda)
  trader/config.json      "prejuizo_acumulado": {"comum": 0, "daytrade": 0, "fii": 0} (o saldo a
                          compensar no início do ano), "irrf_saldo" (IRRF de meses anteriores ainda
                          não usado) e "asset_types" para corrigir o tipo de um ativo

As regras aplicadas (lidas em 2026-10-26; confira na Receita e com seu contador):
  preço médio     custo de aquisição = soma das compras + taxas, dividido pelas ações; vender não
                  muda o preço médio (não é FIFO, não existe "lote" para imposto)
  day trade       compra e venda do mesmo ativo no mesmo dia: a quantidade casada é day trade,
                  ao preço médio de compra e de venda do dia; o resto segue como operação comum
  comum (swing)   ações, units, ETFs e BDRs: 15% sobre o lucro do mês
  isenção         vendas de AÇÕES (e units) no mercado à vista até R$ 20.000 no mês: o lucro com
                  ações é isento. ETFs, BDRs e FIIs não têm isenção. O prejuízo de um mês isento
                  continua compensável; prejuízo acumulado não abate lucro isento
  day trade       20% sobre o lucro do mês, grupo próprio
  FII             20% sobre o lucro na venda de cotas, grupo próprio; rendimentos mensais são
                  isentos para pessoa física (regras de cotistas e de bolsa)
  prejuízos       cada grupo compensa só o seu (comum, day trade, FII), sem prazo de validade
  IRRF            0,005% sobre o valor das vendas comuns (o "dedo-duro", retido quando passa de
                  R$ 1) e 1% sobre o lucro de day trade; abate do imposto do mês, o que sobrar
                  passa para os meses seguintes. Os valores reais estão nas notas de corretagem:
                  esta ferramenta só estima
  DARF            código 6015, até o último dia útil do mês seguinte; abaixo de R$ 10 não se paga,
                  o valor acumula para o próximo DARF
  proventos       dividendos: isentos até R$ 50.000 por mês de cada empresa; acima disso a
                  empresa retém 10% sobre o total (Lei 15.270/2025, desde 2026). JCP: 17,5% retido
                  na fonte (LC 224/2025, desde 2026). Não entram nesta apuração
  exterior        ações e ETFs nos EUA: 15% sobre o ganho realizado em reais, apurado no ano e pago
                  na declaração anual (Lei 14.754/2023); sem isenção de R$ 20.000 ou R$ 35.000
"""

import argparse
import csv
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import b3  # noqa: E402

RATE = {"comum": 0.15, "daytrade": 0.20, "fii": 0.20}
EXEMPTION = 20000.0
IRRF_SWING = 0.00005   # 0,005%
IRRF_DT = 0.01         # 1%
DARF_MIN = 10.0
EPS = 1e-9


class IRError(Exception):
    pass


# ---------------------------------------------------------------- entradas

def read_json(path, required=False):
    if not path or not os.path.exists(path):
        if required:
            raise IRError("não encontrei %s" % path)
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise IRError("%s não é JSON válido: %s" % (path, e))


def _side(v):
    v = str(v or "").strip().lower()
    if v in ("c", "compra", "buy", "b"):
        return "buy"
    if v in ("v", "venda", "sell", "s"):
        return "sell"
    raise IRError("lado desconhecido %r (use C/V, compra/venda)" % v)


def _date(v):
    v = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    raise IRError("data inválida %r (use AAAA-MM-DD ou DD/MM/AAAA)" % v)


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "0").strip()
    return b3.parse_brl(s) if s else 0.0


def read_trades_csv(path):
    """data;ticker;lado;quantidade;preco;taxas (separador ; ou ,). Cabeçalho obrigatório."""
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    delim = ";" if text.count(";") >= text.count(",") else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delim))
    out = []
    for i, r in enumerate(rows, 2):
        r = {str(k).strip().lower(): v for k, v in r.items() if k}
        try:
            out.append({
                "date": _date(r.get("data") or r.get("date")),
                "ticker": b3.base(r.get("ticker") or r.get("ativo") or r.get("symbol")),
                "side": _side(r.get("lado") or r.get("side") or r.get("c/v") or r.get("tipo")),
                "qty": _num(r.get("quantidade") or r.get("qty") or r.get("qtd")),
                "price": _num(r.get("preco") or r.get("preço") or r.get("price")),
                "fees": _num(r.get("taxas") or r.get("fees") or 0),
            })
        except IRError as e:
            raise IRError("%s, linha %d: %s" % (path, i, e))
    return out


def load_inputs(a):
    pf = read_json(a.portfolio) or {}
    cfg = read_json(a.config) or {}
    trades = list(pf.get("trades", []))
    if getattr(a, "trades", None):
        trades += read_trades_csv(a.trades)
    norm = []
    for t in trades:
        norm.append({"date": _date(t["date"]), "ticker": b3.base(t.get("ticker") or t.get("symbol")),
                     "side": _side(t["side"]), "qty": float(t["qty"]), "price": float(t["price"]),
                     "fees": float(t.get("fees") or 0)})
    opening = [{"ticker": b3.base(o["ticker"]), "shares": float(o["shares"]), "cost": float(o["cost"])}
               for o in pf.get("opening", [])]
    return norm, opening, cfg


# ---------------------------------------------------------------- o motor

def group_of(ticker, cfg):
    kind, guess = b3.asset_type(ticker, cfg.get("asset_types"))
    if kind == "fii":
        return "fii", kind, guess
    return "comum", kind, guess


def process(trades, opening, cfg):
    """Percorre as execuções em ordem e devolve (eventos realizados, posições finais, avisos).

    Evento: {date, ticker, kind, modo ('comum'|'daytrade'), qty, venda (valor bruto), resultado}."""
    pos = {}
    for o in opening:
        p = pos.setdefault(o["ticker"], {"shares": 0.0, "cost": 0.0})
        p["shares"] += o["shares"]
        p["cost"] += o["cost"]
    events, warnings = [], []
    by_day = {}
    for t in trades:
        by_day.setdefault((t["date"], t["ticker"]), []).append(t)
    for (day, tk) in sorted(by_day):
        rows = by_day[(day, tk)]
        _, kind, guess = group_of(tk, cfg)
        if guess:
            w = "%s tratado como %s pelo final do ticker; corrija em asset_types se não for" % (
                tk, b3.TYPE_NAMES.get(kind, kind))
            if w not in warnings:
                warnings.append(w)
        buys = [r for r in rows if r["side"] == "buy"]
        sells = [r for r in rows if r["side"] == "sell"]
        bq = sum(r["qty"] for r in buys)
        sq = sum(r["qty"] for r in sells)
        b_gross = sum(r["qty"] * r["price"] for r in buys)
        s_gross = sum(r["qty"] * r["price"] for r in sells)
        b_cost = b_gross + sum(r["fees"] for r in buys)          # custo com taxas
        s_net = s_gross - sum(r["fees"] for r in sells)          # venda líquida de taxas
        dt = min(bq, sq)
        if dt > EPS:
            res = dt * (s_net / sq) - dt * (b_cost / bq)
            events.append({"date": day, "ticker": tk, "kind": kind, "modo": "daytrade", "qty": dt,
                           "venda": dt * s_gross / sq, "resultado": res})
        rb, rs = bq - dt, sq - dt
        p = pos.setdefault(tk, {"shares": 0.0, "cost": 0.0})
        if rb > EPS:
            p["shares"] += rb
            p["cost"] += rb * (b_cost / bq)
        if rs > EPS:
            if p["shares"] + EPS < rs:
                raise IRError("%s em %s: venda de %s ações, mas a posição era %s. Falta uma compra ou a posição "
                              "inicial (\"opening\" no portfolio.json)" % (tk, day, _q(rs), _q(p["shares"])))
            avg = p["cost"] / p["shares"] if p["shares"] else 0.0
            res = rs * (s_net / sq) - rs * avg
            events.append({"date": day, "ticker": tk, "kind": kind, "modo": "comum", "qty": rs,
                           "venda": rs * s_gross / sq, "resultado": res, "preco_medio": avg})
            p["cost"] -= avg * rs
            p["shares"] -= rs
            if p["shares"] <= EPS:
                p["shares"], p["cost"] = 0.0, 0.0
    return events, pos, warnings


def _q(x):
    return str(int(round(x))) if abs(x - round(x)) < EPS else "%.4f" % x


def apurar(events, cfg, year, months=None):
    """Apuração mensal do ano. Devolve a lista de meses e os saldos finais."""
    loss = dict({"comum": 0.0, "daytrade": 0.0, "fii": 0.0}, **{
        k: float(v) for k, v in (cfg.get("prejuizo_acumulado") or {}).items() if k in RATE})
    irrf_carry = float(cfg.get("irrf_saldo") or 0)
    darf_carry = 0.0
    out = []
    for m in range(1, 13):
        ym = "%04d-%02d" % (year, m)
        ev = [e for e in events if e["date"][:7] == ym]
        sales_acoes = sum(e["venda"] for e in ev if e["modo"] == "comum" and e["kind"] in ("acao", "unit"))
        exempt = sales_acoes <= EXEMPTION + EPS
        r_acoes = sum(e["resultado"] for e in ev if e["modo"] == "comum" and e["kind"] in ("acao", "unit"))
        r_outros = sum(e["resultado"] for e in ev if e["modo"] == "comum" and e["kind"] in ("etf", "bdr", "desconhecido"))
        r_fii = sum(e["resultado"] for e in ev if e["kind"] == "fii")
        r_dt = sum(e["resultado"] for e in ev if e["modo"] == "daytrade" and e["kind"] != "fii")
        isento = r_acoes if (exempt and r_acoes > 0) else 0.0
        bases = {"comum": (0.0 if isento else r_acoes) + r_outros, "daytrade": r_dt, "fii": r_fii}
        detail = {}
        tax = 0.0
        for g in ("comum", "daytrade", "fii"):
            b = bases[g]
            used = 0.0
            if b > 0:
                used = min(b, loss[g])
                b -= used
                loss[g] -= used
            elif b < 0:
                loss[g] += -b
                b = 0.0
            t = round(b * RATE[g], 2)
            tax += t
            detail[g] = {"resultado": round(bases[g], 2), "compensado": round(used, 2), "base": round(b, 2),
                         "imposto": t, "prejuizo_a_compensar": round(loss[g], 2)}
        # IRRF estimado: 0,005% das vendas comuns por dia (retido só se passar de R$ 1) e 1% do lucro de day trade do dia
        irrf = 0.0
        days = {}
        for e in ev:
            d = days.setdefault(e["date"], {"vendas": 0.0, "dt": 0.0})
            if e["modo"] == "comum":
                d["vendas"] += e["venda"]
            else:
                d["dt"] += e["resultado"]
        for d in days.values():
            v = d["vendas"] * IRRF_SWING
            irrf += v if v >= 1.0 else 0.0
            irrf += d["dt"] * IRRF_DT if d["dt"] > 0 else 0.0
        irrf = round(irrf, 2)
        avail = irrf + irrf_carry
        use = min(avail, tax)
        irrf_carry = round(avail - use, 2)
        due = round(tax - use + darf_carry, 2)
        pay = due if due >= DARF_MIN - EPS else 0.0
        darf_carry = 0.0 if pay else due
        vto = b3.last_business_day(year + (m == 12), 1 if m == 12 else m + 1)
        row = {"mes": ym, "vendas_acoes": round(sales_acoes, 2), "isento_20mil": exempt and sales_acoes > 0,
               "lucro_isento": round(isento, 2), "grupos": detail, "imposto": round(tax, 2),
               "irrf_estimado": irrf, "irrf_usado": round(use, 2), "darf": round(pay, 2),
               "acumula_proximo_darf": round(darf_carry, 2), "vencimento": vto.isoformat(),
               "codigo": "6015", "operacoes": len(ev)}
        if months is None or m in months:
            out.append(row)
    return out, {"prejuizo_a_compensar": {k: round(v, 2) for k, v in loss.items()},
                 "irrf_saldo": irrf_carry, "darf_acumulado": round(darf_carry, 2)}


# ---------------------------------------------------------------- exterior (Lei 14.754/2023)

def exterior(rows, year, prior_loss=0.0):
    """Ganho de capital em ações no exterior, em reais, pelo custo médio em reais.

    Cada linha: data, ticker, lado, quantidade, preco (em US$), cambio (R$ por US$ na data,
    a cotação do Banco Central que a regra pede: confira na IN da Receita) e taxas (US$)."""
    pos, events = {}, []
    for r in sorted(rows, key=lambda r: r["date"]):
        p = pos.setdefault(r["ticker"], {"shares": 0.0, "cost_brl": 0.0})
        brl_value = r["qty"] * r["price"] * r["fx"]
        fees = r["fees"] * r["fx"]
        if r["side"] == "buy":
            p["shares"] += r["qty"]
            p["cost_brl"] += brl_value + fees
        else:
            if p["shares"] + EPS < r["qty"]:
                raise IRError("%s em %s: venda maior que a posição" % (r["ticker"], r["date"]))
            avg = p["cost_brl"] / p["shares"]
            res = brl_value - fees - avg * r["qty"]
            p["cost_brl"] -= avg * r["qty"]
            p["shares"] -= r["qty"]
            if r["date"][:4] == str(year):
                events.append({"date": r["date"], "ticker": r["ticker"], "resultado_brl": round(res, 2)})
    total = sum(e["resultado_brl"] for e in events)
    if total >= 0:
        used = min(total, prior_loss)
        base, carry = total - used, prior_loss - used
    else:
        base, carry = 0.0, prior_loss - total
    return {"ano": year, "eventos": events, "resultado": round(total, 2), "base": round(base, 2),
            "imposto_15": round(base * 0.15, 2), "prejuizo_a_compensar": round(carry, 2),
            "posicoes": {t: {"quantidade": round(p["shares"], 6), "custo_brl": round(p["cost_brl"], 2)}
                         for t, p in pos.items() if p["shares"] > EPS}}


def read_exterior_csv(path):
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    delim = ";" if text.count(";") >= text.count(",") else ","
    out = []
    for i, r in enumerate(csv.DictReader(text.splitlines(), delimiter=delim), 2):
        r = {str(k).strip().lower(): v for k, v in r.items() if k}
        try:
            fx = r.get("cambio") or r.get("câmbio") or r.get("ptax") or r.get("fx")
            if not fx:
                raise IRError("falta a coluna cambio (R$ por US$ na data)")
            out.append({"date": _date(r.get("data") or r.get("date")), "ticker": str(r.get("ticker")).upper(),
                        "side": _side(r.get("lado") or r.get("side")),
                        "qty": _num(r.get("quantidade") or r.get("qty")),
                        "price": float(str(r.get("preco") or r.get("price")).replace(",", ".")),
                        "fx": float(str(fx).replace(",", ".")),
                        "fees": float(str(r.get("taxas") or r.get("fees") or 0).replace(",", "."))})
        except (IRError, ValueError, TypeError) as e:
            raise IRError("%s, linha %d: %s" % (path, i, e))
    return out


# ---------------------------------------------------------------- relatórios

R = lambda x: b3.money(x, "br", True)  # noqa: E731


def report_apuracao(months, saldo, warnings):
    lines = []
    for w in warnings:
        lines.append("AVISO: " + w)
    for m in months:
        if not m["operacoes"] and not m["acumula_proximo_darf"]:
            continue
        g = m["grupos"]
        lines.append("%s  vendas de ações %s%s" % (m["mes"], R(m["vendas_acoes"]),
                     "  (até R$ 20.000: lucro com ações isento)" if m["isento_20mil"] else ""))
        if m["lucro_isento"]:
            lines.append("    lucro isento (ações): %s" % R(m["lucro_isento"]))
        for k, label in (("comum", "comum 15%"), ("daytrade", "day trade 20%"), ("fii", "FII 20%")):
            d = g[k]
            if d["resultado"] or d["compensado"]:
                lines.append("    %-14s resultado %12s  compensado %10s  base %10s  imposto %9s  prejuízo a compensar %s"
                             % (label, R(d["resultado"]), R(d["compensado"]), R(d["base"]), R(d["imposto"]),
                                R(d["prejuizo_a_compensar"])))
        if m["imposto"] or m["darf"] or m["acumula_proximo_darf"]:
            lines.append("    imposto %s - IRRF estimado %s = DARF 6015 %s, vence %s%s" % (
                R(m["imposto"]), R(m["irrf_usado"]), R(m["darf"]), _br_date(m["vencimento"]),
                ("  (abaixo de R$ 10: acumula %s)" % R(m["acumula_proximo_darf"])) if m["acumula_proximo_darf"] else ""))
        else:
            lines.append("    sem imposto a pagar")
    if not lines:
        lines.append("Nenhuma operação no período.")
    lines.append("")
    p = saldo["prejuizo_a_compensar"]
    lines.append("Prejuízo a compensar no fim do período: comum %s, day trade %s, FII %s. IRRF não usado: %s."
                 % (R(p["comum"]), R(p["daytrade"]), R(p["fii"]), R(saldo["irrf_saldo"])))
    lines.append("IRRF é estimado; use os valores das notas de corretagem. Conta de apoio, não assessoria "
                 "tributária: confira com seu contador e no Sicalc/Receita.")
    return "\n".join(lines)


def _br_date(iso):
    y, m, d = iso.split("-")
    return "%s/%s/%s" % (d, m, y)


# ---------------------------------------------------------------- comandos

def cmd_apurar(a):
    trades, opening, cfg = load_inputs(a)
    events, _, warnings = process(trades, opening, cfg)
    year = a.ano or datetime.date.today().year
    months, saldo = apurar(events, cfg, year, [a.mes] if a.mes else None)
    if a.json:
        print(json.dumps({"ano": year, "meses": months, "saldo": saldo, "avisos": warnings}, indent=2,
                         ensure_ascii=False))
    else:
        print(report_apuracao(months, saldo, warnings))
    return 0


def cmd_posicao(a):
    trades, opening, cfg = load_inputs(a)
    cut = a.em or datetime.date.today().isoformat()
    events, pos, warnings = process([t for t in trades if t["date"] <= cut], opening, cfg)
    rows = []
    for tk in sorted(pos):
        p = pos[tk]
        if p["shares"] <= EPS:
            continue
        kind, guess = b3.asset_type(tk, cfg.get("asset_types"))
        rows.append({"ticker": tk, "tipo": kind, "quantidade": round(p["shares"], 6),
                     "custo_total": round(p["cost"], 2), "preco_medio": round(p["cost"] / p["shares"], 4)})
    if a.json:
        print(json.dumps({"em": cut, "posicoes": rows, "avisos": warnings}, indent=2, ensure_ascii=False))
        return 0
    for w in warnings:
        print("AVISO: " + w)
    print("Posição em %s (custo de aquisição, o valor de Bens e Direitos):" % _br_date(cut))
    for r in rows:
        print("  %-7s %-4s %8s ações  preço médio %12s  custo %14s" % (
            r["ticker"], b3.TYPE_NAMES.get(r["tipo"], r["tipo"])[:4], _q(r["quantidade"]),
            R(r["preco_medio"]), R(r["custo_total"])))
    if not rows:
        print("  (nenhuma posição)")
    print("Na declaração, cada ativo vai em Bens e Direitos pelo custo, não pelo valor de mercado.")
    return 0


def cmd_prejuizo(a):
    trades, opening, cfg = load_inputs(a)
    _, pos, _ = process(trades, opening, cfg)
    pdoc = read_json(a.precos) or {}
    prices = {b3.base(k): float(v) for k, v in (pdoc.get("prices", pdoc) or {}).items()
              if isinstance(v, (int, float))}
    rows = []
    for tk, p in pos.items():
        if p["shares"] <= EPS or tk not in prices:
            continue
        unreal = p["shares"] * prices[tk] - p["cost"]
        if unreal < -abs(a.minimo):
            kind, _ = b3.asset_type(tk, cfg.get("asset_types"))
            rows.append((unreal, tk, kind, p))
    rows.sort()
    if not rows:
        print("Nenhuma posição com prejuízo acima de %s (com os preços de %s)." % (R(a.minimo), a.precos))
        return 1
    print("Posições no prejuízo (preço de %s):" % (pdoc.get("as_of") or a.precos))
    for unreal, tk, kind, p in rows:
        grupo = "FII" if kind == "fii" else "comum"
        print("  %-7s %s  preço médio %s, agora %s, prejuízo %s (grupo %s)" % (
            tk, _q(p["shares"]), R(p["cost"] / p["shares"]), R(prices[tk]), R(unreal), grupo))
    print("")
    print("No Brasil não existe a regra americana de wash sale. Mas: recomprar no MESMO dia vira day trade")
    print("(grupo e alíquota diferentes) e o prejuízo só abate lucro do mesmo grupo. Venda e recompra para")
    print("gerar prejuízo artificial pode ser questionada pela Receita. Conta de apoio, não assessoria.")
    return 0


def cmd_exterior(a):
    if not a.trades:
        raise IRError("exterior precisa de --trades arquivo.csv (data;ticker;lado;quantidade;preco;cambio;taxas)")
    res = exterior(read_exterior_csv(a.trades), a.ano or datetime.date.today().year, a.prejuizo_anterior)
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    print("Exterior %d (Lei 14.754/2023): resultado %s, base %s, imposto de 15%% %s, prejuízo a compensar %s."
          % (res["ano"], R(res["resultado"]), R(res["base"]), R(res["imposto_15"]), R(res["prejuizo_a_compensar"])))
    for e in res["eventos"]:
        print("  %s %-6s %s" % (_br_date(e["date"]), e["ticker"], R(e["resultado_brl"])))
    print("Pago na declaração anual, não por DARF mensal. Dividendos no exterior também pagam 15% (o imposto retido")
    print("nos EUA pode ser abatido conforme a regra de reciprocidade). Confira a cotação de câmbio exigida pela")
    print("Receita e o resultado com seu contador.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="IR de renda variável no Brasil (trader-tax). Não é assessoria.")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--portfolio", default="trader/portfolio.json")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--trades", help="CSV extra: data;ticker;lado;quantidade;preco;taxas")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("apurar", help="apuração mensal e DARF")
    common(p)
    p.add_argument("--ano", type=int)
    p.add_argument("--mes", type=int)
    p = sub.add_parser("posicao", help="preço médio e custo por ativo numa data")
    common(p)
    p.add_argument("--em", help="AAAA-MM-DD (padrão: hoje)")
    p = sub.add_parser("prejuizo", help="posições abaixo do preço médio")
    common(p)
    p.add_argument("--precos", default="trader/prices.json")
    p.add_argument("--minimo", type=float, default=0.0, help="só prejuízos acima deste valor (R$)")
    p = sub.add_parser("exterior", help="ações nos EUA para residente no Brasil")
    p.add_argument("--trades", help="CSV: data;ticker;lado;quantidade;preco;cambio;taxas")
    p.add_argument("--ano", type=int)
    p.add_argument("--prejuizo-anterior", type=float, default=0.0)
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"apurar": cmd_apurar, "posicao": cmd_posicao, "prejuizo": cmd_prejuizo,
                "exterior": cmd_exterior}[a.cmd](a)
    except IRError as e:
        print("ir_br.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
