#!/usr/bin/env python3
"""Pre-trade risk check for trader-risk. Standard library only, no network.

Reads the proposed orders (trader/orders.json) and checks every one against
your rules (trader/config.json), your account (trader/portfolio.json) and
prices (trader/prices.json). Each order gets PASS or BLOCK with the reasons.
Orders are checked in file order as if each PASS had filled, so five buys
that are fine one by one but break the cash buffer together are caught.

    python3 check.py                       # the trader/ files, writes trader/state/risk.json
    python3 check.py --orders trader/orders.json --json
    python3 check.py --no-write            # check without recording the verdicts

What blocks an order:

  format        missing symbol or side, both or neither of qty / notional,
                notional on anything but a market day order (Alpaca's rule),
                a limit order without a limit price, unknown type
  asset         options (OCC symbols) unless "allow_options": true; crypto
                and anything that is not a stock or ETF
  blocked       a ticker on your "blocked" list
  size          under min_order_usd, over max_order_usd
  position      the stock would be over max_position_pct of the account
  cash          the buy would dip into your cash buffer, or need margin
  short         selling more than you hold, unless "allow_short": true
  duplicate     the same symbol and side twice in this batch, or already
                placed today (trader/state/broker.json)
  daily limit   more than max_orders_per_day orders placed today

B3 orders ("market": "br", tickers like PETR4, PETR4F, BOVA11) are checked
in reais with the B3 rules on top:

  lote          quantity in whole shares; a standard-lot order a multiple of
                the round lot (100 for shares and units), a fractional order
                (ticker + F) between 1 and lot - 1; no notional on the B3
  tipo          market, limit or stop_limit; validity day, gtc, ioc or fok
  preço         a limit more than 5% away from the last price is flagged
  horário       outside the B3 session the order waits for the next open (warning)
  day trade     selling what was bought today (or buying back what was sold
                today) is a day trade: 20% income tax, no exemption (warning)
  isenção       stock sales this month over R$ 20.000 lose the swing-trade
                exemption (warning, from what trader-broker recorded)

Exit code 0 when every order passes, 1 when any order is blocked.
The verdicts go to trader/state/risk.json with a fingerprint of each order,
so trader-broker only shows an order as ready if THIS exact order passed today.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import b3  # noqa: E402  (regras da B3)

DEFAULTS = {
    "budget": None, "cash_buffer_pct": 10, "max_position_pct": 25, "max_order_usd": 2000,
    "min_order_usd": 5, "max_orders_per_day": 10, "paper": True, "blocked": [],
    "allow_options": False, "allow_margin": False, "allow_short": False,
}
ALPACA_FIELDS = ("symbol", "side", "qty", "notional", "type", "time_in_force", "limit_price",
                 "stop_price", "trail_price", "trail_percent", "extended_hours", "client_order_id",
                 "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                 "stop_loss_limit_price", "advanced_instructions", "market")
TYPES = {"market", "limit", "stop", "stop_limit", "trailing_stop"}
TIFS = {"day", "gtc", "opg", "cls", "ioc", "fok"}
OCC = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
TICKER = re.compile(r"^[A-Z]{1,5}([.\-][A-Z]{1,2})?$")
CENT = 0.005


class RiskError(Exception):
    pass


def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise RiskError("no %s at %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise RiskError("%s is not valid JSON: %s" % (path, e))


def fingerprint(order):
    """Same function in trader-broker/ticket.py: the exact order that was checked."""
    core = {k: order[k] for k in ALPACA_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


_MKT = ["us"]


def money(x, market=None):
    market = market or _MKT[0]
    if market == "br":
        return b3.money(x, "br")
    return "$" + "{:,.2f}".format(float(x)).replace(".00", "")


B3_TYPES = {"market", "limit", "stop_limit"}
B3_TIFS = {"day", "gtc", "ioc", "fok"}
EXEMPTION_BRL = 20000.0


def order_market(o, cfg):
    m = o.get("market") or cfg.get("market")
    if m:
        return str(m).lower()
    return b3.market_of(o.get("symbol", ""))


def month_sales_brl(state, month, cfg):
    """Stock sales (ações e units) recorded as placed this month, in reais."""
    total = 0.0
    for rec in (state or {}).get("orders", []):
        if rec.get("status") != "placed" or str(rec.get("date") or rec.get("at", ""))[:7] != month:
            continue
        o = rec.get("order") or rec
        if str(o.get("side")) != "sell" or str(o.get("market") or "") != "br":
            continue
        kind, _ = b3.asset_type(o.get("symbol", ""), cfg.get("asset_types"))
        if kind not in ("acao", "unit"):
            continue
        v = _f(rec.get("value")) or ((_f(o.get("qty")) or 0) * (_f(o.get("limit_price")) or 0))
        total += v or 0
    return total


def account(cfg, portfolio, prices):
    """Starting account: cash and position values. No portfolio = a fresh
    account funded with the budget."""
    warnings = []
    if portfolio is None:
        budget = _f(cfg.get("budget"))
        if not budget:
            raise RiskError("no trader/portfolio.json and no budget in the config: "
                            "nothing to check the orders against")
        return {"cash": budget, "shares": {}, "values": {}}, warnings
    cash = _f(portfolio.get("cash"))
    if cash is None:
        raise RiskError("portfolio.json needs a \"cash\" number")
    shares, values = {}, {}
    for p in portfolio.get("positions", []):
        t = str(p.get("ticker") or p.get("symbol") or "").upper()
        if not t:
            continue
        n = _f(p.get("shares", p.get("qty")))
        if n is None:
            n = sum(_f(l.get("shares")) or 0 for l in p.get("lots", []))
        shares[t] = shares.get(t, 0) + n
        if prices.get(t):
            values[t] = shares[t] * prices[t]
        else:
            basis = sum(_f(l.get("cost")) or 0 for l in p.get("lots", []))
            values[t] = basis
            warnings.append("no price for %s: valued at its cost basis %s" % (t, money(basis)))
    return {"cash": cash, "shares": shares, "values": values}, warnings


def placed_today(state, today):
    """Orders recorded as placed today by trader-broker."""
    out = []
    for rec in (state or {}).get("orders", []):
        if rec.get("status") == "placed" and str(rec.get("date") or str(rec.get("at", ""))[:10]) == today:
            out.append(rec)
    return out


def check(orders, cfg, portfolio=None, prices=None, state=None, today=None, now=None):
    """Pure function. Returns {"results": [...], "pass": n, "block": n, "warnings": [...]}."""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    markets = {order_market(o, c) for o in orders}
    if len(markets) > 1:
        raise RiskError("these orders mix B3 and US orders; keep one market per project folder")
    market = markets.pop() if markets else "us"
    _MKT[0] = market
    if market == "br":
        lo = c.get("min_order", c.get("min_order_brl", 50))
        hi = c.get("max_order", c.get("max_order_brl"))
        c["min_order_usd"], c["max_order_usd"] = lo, hi
    prices = {b3.base(k) if market == "br" else str(k).upper(): float(v)
              for k, v in (prices or {}).items() if _f(v)}
    today = today or datetime.date.today().isoformat()
    if market == "br" and portfolio:
        portfolio = dict(portfolio, positions=[dict(p, ticker=b3.base(p.get("ticker") or p.get("symbol") or ""))
                                               for p in portfolio.get("positions", [])])
    acct, top_warn = account(c, portfolio, prices)
    blocked = {str(b).upper() for b in c.get("blocked") or []}
    done_today = placed_today(state, today)
    count_today = len(done_today)
    placed_keys = {(str(r.get("symbol", "")).upper(), r.get("side")) for r in done_today}
    seen = set()
    results = []
    if market == "br":
        top_warn.append("B3: as boletas são executadas por você no home broker; confira lote, preço e validade lá")
        try:
            st = b3.session((now or b3.now_brt()).date())
            n = (now or b3.now_brt())
            if st is None:
                top_warn.append("sem pregão hoje na B3: uma ordem do dia só vale no próximo pregão")
            elif not (st["open"] <= n < st["close"]):
                top_warn.append("fora do horário do pregão (%s às %s): a ordem espera a próxima abertura"
                                % (st["open"].strftime("%H:%M"), st["close"].strftime("%H:%M")))
        except KeyError:
            top_warn.append("calendário da B3 deste ano desconhecido: confira se há pregão")
        bought_today = {b3.base(r.get("symbol", "")) for r in done_today if r.get("side") == "buy"}
        sold_today = {b3.base(r.get("symbol", "")) for r in done_today if r.get("side") == "sell"}
        month_sales = month_sales_brl(state, today[:7], c)
    elif not c.get("paper", True):
        top_warn.append("LIVE account (\"paper\": false): these orders use real money")

    for i, o in enumerate(orders, 1):
        reasons, warns = [], []
        sym = str(o.get("symbol", "")).strip().upper()
        side = str(o.get("side", "")).strip().lower()
        typ = str(o.get("type", "market")).strip().lower()
        tif = str(o.get("time_in_force", "day")).strip().lower()
        qty, notional = o.get("qty"), o.get("notional")
        value = None
        br = market == "br"
        if br:
            sym = b3.clean(sym)
        key_sym = b3.base(sym) if br else sym

        # format
        if not sym:
            reasons.append("format: no symbol")
        if side not in ("buy", "sell"):
            reasons.append("format: side must be buy or sell, got %r" % o.get("side"))
        if (qty is None) == (notional is None):
            reasons.append("format: give exactly one of qty or notional")
        for k in ("qty", "notional", "limit_price", "stop_price"):
            if o.get(k) is not None:
                v = _f(o.get(k))
                if v is None or v <= 0:
                    reasons.append("format: %s must be a positive number, got %r" % (k, o.get(k)))
                elif not isinstance(o.get(k), str):
                    warns.append("send %s as a string (\"%s\"), the way place_stock_order types it"
                                 % (k, o.get(k)))
        if br:
            if typ not in B3_TYPES:
                reasons.append("formato: na B3 use market, limit ou stop_limit, não %r" % typ)
            if tif not in B3_TIFS:
                reasons.append("formato: validade %r desconhecida (day, gtc, ioc, fok)" % tif)
            if notional is not None:
                reasons.append("formato: a B3 não aceita ordem por valor (notional); use qty em ações inteiras")
            q = _f(qty)
            if q is not None and q > 0:
                if abs(q - round(q)) > 1e-9:
                    reasons.append("lote: %s não é um número inteiro de ações" % qty)
                elif b3.is_b3(sym):
                    lot = b3.round_lot(key_sym, c.get("asset_types"), c.get("round_lots"))
                    frac = sym.endswith("F") and sym != key_sym
                    if frac and not (1 <= int(round(q)) < max(lot, 2)):
                        reasons.append("lote: no fracionário (%s) a quantidade vai de 1 a %d; %s não cabe"
                                       % (sym, lot - 1, qty))
                    if frac and lot <= 1:
                        reasons.append("lote: %s tem lote padrão de 1; não existe fracionário, use %s"
                                       % (key_sym, key_sym))
                    if not frac and lot > 1 and int(round(q)) % lot:
                        reasons.append("lote: %s negocia em lotes de %d; %s não é múltiplo (use %s para o resto)"
                                       % (sym, lot, qty, b3.fractional(sym)))
        else:
            if typ not in TYPES:
                reasons.append("format: unknown order type %r" % typ)
            if tif not in TIFS:
                reasons.append("format: unknown time_in_force %r" % tif)
        if not br and notional is not None and (typ != "market" or tif != "day"):
            reasons.append("format: a notional (dollar) order must be a market order with time_in_force day")
        if typ in ("limit", "stop_limit") and o.get("limit_price") is None:
            reasons.append("format: a %s order needs a limit_price" % typ)
        if typ in ("stop", "stop_limit") and o.get("stop_price") is None:
            reasons.append("format: a %s order needs a stop_price" % typ)
        if o.get("extended_hours") and not (typ == "limit" and tif == "day"):
            reasons.append("format: extended hours needs a limit order with time_in_force day")
        if o.get("order_class") or o.get("advanced_instructions"):
            warns.append("advanced order (%s): check every leg before you say yes"
                         % (o.get("order_class") or "advanced_instructions"))

        # asset
        if sym and OCC.match(sym.replace(" ", "")):
            if not c.get("allow_options"):
                reasons.append("asset: %s is an option contract; options are off "
                               "(\"allow_options\": false)" % sym)
            else:
                warns.append("option order: options can lose 100%% of what you pay")
        elif br and sym and not b3.is_b3(sym):
            reasons.append("ativo: %s não é um ticker de ação, unit, FII, ETF ou BDR da B3 "
                           "(opções e futuros estão fora deste pacote)" % sym)
        elif not br and sym and ("/" in sym or not TICKER.match(sym)):
            reasons.append("asset: %s does not look like a US stock or ETF ticker; "
                           "this pack trades stocks and ETFs only" % sym)

        # blocked list
        if sym in blocked or key_sym in blocked:
            reasons.append("blocked: %s is on your blocked list" % sym)

        # dollar value of the order
        ref = None
        if typ in ("limit", "stop_limit"):
            ref = _f(o.get("limit_price"))
        elif typ == "stop":
            ref = _f(o.get("stop_price"))
        if ref is None:
            ref = prices.get(key_sym)
        if br and typ in ("limit", "stop_limit") and ref and prices.get(key_sym):
            gap = 100.0 * (ref / prices[key_sym] - 1)
            if abs(gap) > 5:
                warns.append("preço: limite %s está %+.1f%% longe da última cotação %s"
                             % (money(ref), gap, money(prices[key_sym])))
        if notional is not None and _f(notional):
            value = _f(notional)
        elif qty is not None and _f(qty):
            if ref:
                value = _f(qty) * ref
            else:
                reasons.append("price: no price for %s to size a %s-share order; add it to "
                               "trader/prices.json (trader-alerts: alerts.py quote %s --write)"
                               % (sym, qty, sym))

        if value is not None:
            if value < float(c.get("min_order_usd") or 0) - CENT:
                reasons.append("size: %s is under your %s minimum order"
                               % (money(value), money(c["min_order_usd"])))
            if c.get("max_order_usd") and value > float(c["max_order_usd"]) + CENT:
                reasons.append("size: %s is over your %s max order"
                               % (money(value), money(c["max_order_usd"])))

        # account effects, simulated in order
        cash = acct["cash"]
        held = acct["shares"].get(key_sym, 0.0)
        held_value = acct["values"].get(key_sym, 0.0)
        total = cash + sum(acct["values"].values())
        buffer_usd = total * float(c.get("cash_buffer_pct") or 0) / 100.0
        if value is not None and side == "buy":
            after_cash = cash - value
            if after_cash < -CENT and not c.get("allow_margin"):
                reasons.append("cash: needs %s but only %s cash; that would be margin (borrowed money)"
                               % (money(value), money(cash)))
            elif after_cash < buffer_usd - CENT:
                reasons.append("cash: leaves %s cash, under your %s%% buffer of %s"
                               % (money(max(after_cash, 0)), _pct(c["cash_buffer_pct"]), money(buffer_usd)))
            pos_after = held_value + value
            limit = total * float(c.get("max_position_pct") or 100) / 100.0
            if total > 0 and pos_after > limit + CENT:
                reasons.append("position: %s would be %s, %.1f%% of the %s account, over your %s%% cap"
                               % (sym, money(pos_after), 100.0 * pos_after / total, money(total),
                                  _pct(c["max_position_pct"])))
        if br and sym:
            if side == "sell" and key_sym in bought_today:
                warns.append("day trade: %s foi comprado hoje; vender hoje é day trade (IR de 20%%, sem isenção)"
                             % key_sym)
            if side == "buy" and key_sym in sold_today:
                warns.append("day trade: %s foi vendido hoje; recomprar hoje vira day trade" % key_sym)
            if side == "sell" and value is not None:
                kind, _ = b3.asset_type(key_sym, c.get("asset_types"))
                if kind in ("acao", "unit"):
                    month_sales += value
                    if month_sales > EXEMPTION_BRL + CENT:
                        warns.append("isenção: vendas de ações no mês somam %s, acima de R$ 20.000; o lucro do "
                                     "mês (swing trade) paga 15%% de IR" % money(month_sales))
        if side == "sell" and sym:
            if qty is not None and _f(qty):
                over = _f(qty) > held + 1e-9
            elif value is not None:
                over = value > held_value + CENT
            else:
                over = held <= 0
            if over and not c.get("allow_short"):
                if br:
                    reasons.append("venda a descoberto: vendendo mais %s do que você tem (%s ações)"
                                   % (key_sym, _num(held)))
                else:
                    reasons.append("short: selling more %s than you hold (%s shares); short selling is off"
                                   % (sym, _num(held)))

        # duplicates and the daily limit
        key = (sym, side)
        if key in seen:
            reasons.append("duplicate: a second %s %s in this batch" % (side, sym))
        if key in placed_keys:
            reasons.append("duplicate: a %s %s was already placed today" % (side, sym))
        passed_so_far = sum(1 for r in results if r["verdict"] == "PASS")
        cap_n = int(c.get("max_orders_per_day") or 0)
        if cap_n and count_today + passed_so_far >= cap_n:
            reasons.append("daily limit: %d placed today plus %d passed earlier in this batch, "
                           "your limit is %d a day" % (count_today, passed_so_far, cap_n))
        seen.add(key)

        verdict = "BLOCK" if reasons else "PASS"
        if verdict == "PASS" and value is not None:
            if side == "buy":
                acct["cash"] -= value
                acct["values"][key_sym] = acct["values"].get(key_sym, 0.0) + value
                if ref:
                    acct["shares"][key_sym] = held + value / ref
            else:
                acct["cash"] += value
                acct["values"][key_sym] = max(acct["values"].get(key_sym, 0.0) - value, 0.0)
                if qty is not None:
                    acct["shares"][key_sym] = held - _f(qty)
                elif ref:
                    acct["shares"][key_sym] = held - value / ref
        results.append({
            "index": i, "symbol": sym, "side": side,
            "amount": money(_f(notional) or 0) if notional is not None else (
                ("%s ações" % qty) if br else ("%s shares" % qty)),
            "value_usd": round(value, 2) if value is not None else None,
            "value": round(value, 2) if value is not None else None,
            "market": market,
            "fingerprint": fingerprint(o), "verdict": verdict,
            "reasons": reasons, "warnings": warns,
        })

    return {
        "date": today,
        "market": market, "currency": "BRL" if market == "br" else "USD",
        "paper": bool(c.get("paper", True)),
        "results": results,
        "pass": sum(1 for r in results if r["verdict"] == "PASS"),
        "block": sum(1 for r in results if r["verdict"] == "BLOCK"),
        "warnings": top_warn,
        "cash_after": round(acct["cash"], 2),
    }


def _pct(x):
    x = float(x)
    return str(int(x)) if x == int(x) else ("%.2f" % x)


def _num(x):
    x = float(x)
    return str(int(x)) if x == int(x) else ("%.4f" % x).rstrip("0")


def report(res):
    _MKT[0] = res.get("market", "us")
    if _MKT[0] == "br":
        return report_b3(res)
    lines = []
    for w in res["warnings"]:
        lines.append("WARNING: " + w)
    if res["warnings"]:
        lines.append("")
    for r in res["results"]:
        lines.append("%-5s #%d %s %s %s" % (r["verdict"], r["index"], r["side"], r["symbol"], r["amount"]))
        for x in r["reasons"]:
            lines.append("        - " + x)
        for x in r["warnings"]:
            lines.append("        ~ " + x)
    lines.append("")
    lines.append("%d passed, %d blocked. Cash after the passed orders: %s (%s account)."
                 % (res["pass"], res["block"], money(res["cash_after"]), "paper" if res["paper"] else "LIVE"))
    if res["block"]:
        lines.append("Blocked orders do not go to the broker. Fix the order or your rules, then check again.")
    else:
        lines.append("Every order passed. trader-broker still asks you yes or no for each one.")
    lines.append("Education and tooling, not financial advice.")
    return "\n".join(lines)


def report_b3(res):
    lines = []
    for w in res["warnings"]:
        lines.append("AVISO: " + w)
    if res["warnings"]:
        lines.append("")
    for r in res["results"]:
        verdict = "OK" if r["verdict"] == "PASS" else "BLOQ"
        lines.append("%-5s #%d %s %s %s (%s)" % (verdict, r["index"], "COMPRA" if r["side"] == "buy" else "VENDA",
                                              r["symbol"], r["amount"], money(r["value"]) if r.get("value") else "?"))
        for x in r["reasons"]:
            lines.append("        - " + x)
        for x in r["warnings"]:
            lines.append("        ~ " + x)
    lines.append("")
    lines.append("%d aprovadas, %d bloqueadas. Caixa depois das aprovadas: %s."
                 % (res["pass"], res["block"], money(res["cash_after"])))
    if res["block"]:
        lines.append("Boletas bloqueadas não seguem. Corrija a boleta ou suas regras e confira de novo.")
    else:
        lines.append("Tudo aprovado. O trader-broker ainda pede o seu sim para cada boleta.")
    lines.append("Educação e ferramenta, não recomendação de investimento.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check proposed orders against your limits (trader-risk).")
    ap.add_argument("--orders", default="trader/orders.json")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--portfolio", default="trader/portfolio.json",
                    help="your account; if missing, a fresh account funded with the budget")
    ap.add_argument("--prices", default="trader/prices.json")
    ap.add_argument("--state", default="trader/state/broker.json", help="what trader-broker placed today")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--out", default="trader/state/risk.json", help="where the verdicts are recorded")
    ap.add_argument("--no-write", action="store_true", help="do not record the verdicts")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        doc = read_json(a.orders, "orders file (run trader-budget or trader-rebalance first)")
        orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
        if not isinstance(orders, list) or not orders:
            raise RiskError("no orders in %s" % a.orders)
        cfg = read_json(a.config, "config", required=False) or {}
        portfolio = read_json(a.portfolio, "portfolio", required=False)
        pdoc = read_json(a.prices, "prices", required=False) or {}
        prices = pdoc.get("prices", pdoc) if isinstance(pdoc, dict) else {}
        state = read_json(a.state, "broker state", required=False)
        res = check(orders, cfg, portfolio, prices, state, a.today)
        if pdoc.get("as_of"):
            res["prices_as_of"] = pdoc["as_of"]
        if not a.no_write:
            d = os.path.dirname(a.out)
            if d:
                os.makedirs(d, exist_ok=True)
            rec = dict(res)
            rec["checked_at"] = datetime.datetime.now().replace(microsecond=0).isoformat()
            rec["orders_file"] = a.orders
            with open(a.out, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
    except RiskError as e:
        print("check.py: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2) if a.json else report(res))
    return 1 if res["block"] else 0


if __name__ == "__main__":
    sys.exit(main())
