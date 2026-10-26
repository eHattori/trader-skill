#!/usr/bin/env python3
"""Price alerts and the NYSE clock for trader-alerts. Standard library only.

    python3 alerts.py clock                          # is the NYSE open? next open / close
    python3 alerts.py quote AAPL KO --write          # quotes -> trader/prices.json
    python3 alerts.py quote --holdings --write       # every ticker in your portfolio and targets
    python3 alerts.py add --symbol AAPL --above 350  # rules live in trader/alerts.json
    python3 alerts.py add --symbol BAC --stop 50
    python3 alerts.py add --symbol KO --pct 3
    python3 alerts.py add --opening-bell
    python3 alerts.py check                          # rings what hit, once; exit 1 if nothing rang
    python3 alerts.py list
    python3 alerts.py reset aapl-above-350

Rule types:
  above         the price is at or above "price" (a target)
  below / stop  the price is at or below "price" (a stop or a dip to buy)
  pct_move      the price moved "pct" percent or more from the previous close
                (or from "ref" if you give one); "direction": "up" or "down"
  opening_bell  the NYSE opened today (rings once per trading day)

An above / below alert rings ONCE and then stays quiet until you reset it,
unless the rule has "rearm": true (it re-arms when the price crosses back).
A pct_move alert rings at most once per day.

Quotes (free, delayed, for alerts only, never for placing orders):
  yahoo   https://query1.finance.yahoo.com/v8/finance/chart/AAPL (unofficial
          JSON, one request per ticker; the default)
  stooq   https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcv&h&e=csv (Stooq's free
          CSV; it answered 404 on 2026-10-13, kept for when it is back)
  --offline DIR reads DIR/<source>-<TICKER>.json|csv instead of the network.

B3 (Brazil): tickers like PETR4, BOVA11 or AAPL34 are quoted from brapi.dev
first (API v2, https://brapi.dev/api/v2/stocks/quote?symbols=PETR4, one
ticker per request) and from Yahoo as PETR4.SA when brapi fails; both are
saved as PETR4. brapi wants an API key in the BRAPI_TOKEN environment
variable, sent as "Authorization: Bearer" (never in the URL, never in the
chat). Without a key only its test tickers answer: PETR4, VALE3, ITUB4,
MGLU3, MXRF11 and HGLG11. The free plan is about 15,000 requests a month,
one at a time, quotes about 30 minutes delayed. `clock --market br` and opening-bell rules with
"market": "br" use the B3 calendar in b3.py (2026 published by B3, 2027
provisional) and the cash-market hours, 10:00 to 16:55 Brasília while the US
is on daylight time and 10:00 to 17:55 otherwise. `--now` without an offset
is Brasília time when --market br.

NYSE calendar: the 2026 and 2027 holidays and 1:00 p.m. early closes as
published at https://www.nyse.com/markets/hours-calendars (read 2026-10-13).
Outside those years the clock says the holiday list is unknown.
"""

import argparse
import csv
import datetime
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import b3  # noqa: E402  (calendário, horário e tickers da B3)

UA = "Mozilla/5.0 (compatible; trader-skill/1.0; +https://github.com/Jakeschincariol/trader-skill)"
PAUSE = 0.5  # seconds between requests: be polite to free endpoints

NYSE_HOLIDAYS = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King, Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King, Jr. Day",
    "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth National Independence Day (observed)",
    "2027-07-05": "Independence Day (observed)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day",
    "2027-12-24": "Christmas Day (observed)",
}
NYSE_EARLY_CLOSE = {  # 1:00 p.m. ET
    "2026-11-27": "day after Thanksgiving",
    "2026-12-24": "Christmas Eve",
    "2027-11-26": "day after Thanksgiving",
}
CALENDAR_YEARS = (2026, 2027)
OPEN = datetime.time(9, 30)
CLOSE = datetime.time(16, 0)
EARLY = datetime.time(13, 0)


class AlertError(Exception):
    pass


# ---------------------------------------------------------------- time

def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def eastern_offset(utc):
    """Hours from UTC for New York: -4 in daylight time, -5 otherwise.
    DST runs from 2:00 a.m. on the second Sunday of March to 2:00 a.m. on the
    first Sunday of November (US rule since 2007)."""
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))   # 2:00 EST
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))    # 2:00 EDT
    naive = utc.replace(tzinfo=None)
    return -4 if start <= naive < end else -5


def to_eastern(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=eastern_offset(utc))


def eastern_to_utc(local):
    for off in (-4, -5):
        utc = local - datetime.timedelta(hours=off)
        if eastern_offset(utc) == off:
            return utc
    return local + datetime.timedelta(hours=5)


def parse_now(text, market="us"):
    """ISO time -> naive UTC. A time without an offset is New York time (Brasília with market br)."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise AlertError("--now wants an ISO time like 2026-10-13T09:31 (New York) or ...Z (UTC)")
    if dt.tzinfo is None:
        if market == "br":
            return dt + datetime.timedelta(hours=3)
        return eastern_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def trading_day(d):
    """(is_trading_day, reason). Weekends and the NYSE holiday list."""
    if d.weekday() >= 5:
        return False, "weekend"
    name = NYSE_HOLIDAYS.get(d.isoformat())
    if name:
        return False, "NYSE holiday: " + name
    return True, ""


def session(d):
    """(open_time, close_time) in New York time, or None if closed all day."""
    ok, _ = trading_day(d)
    if not ok:
        return None
    return OPEN, (EARLY if d.isoformat() in NYSE_EARLY_CLOSE else CLOSE)


def b3_status(now_utc):
    """Same shape as market_status, for the B3 (times in Brasília)."""
    now = now_utc.replace(tzinfo=datetime.timezone.utc).astimezone(b3.BRT)
    d = now.date()
    st = {"market": "br", "now_local": now.strftime("%Y-%m-%d %H:%M"), "now_new_york": now.strftime("%Y-%m-%d %H:%M"),
          "tz": "Brasília", "date": d.isoformat(), "weekday": now.strftime("%A"),
          "calendar_known": d.year in b3.HOLIDAYS, "provisional": d.year in b3.PROVISIONAL_YEARS,
          "open": False, "reason": "", "early_close": None}
    try:
        s = b3.session(d)
    except KeyError:
        st["reason"] = "B3 calendar for %d unknown" % d.year
        return st
    if s is None:
        st["reason"] = "weekend" if d.weekday() >= 5 else "B3 holiday: " + (b3.holiday(d) or "")
    else:
        st["opens"], st["closes"] = s["open"].strftime("%H:%M"), s["close"].strftime("%H:%M")
        if s["note"]:
            st["note"] = s["note"]
        if s["open"] <= now < s["close"]:
            st["open"], st["reason"] = True, "regular session"
        elif now < s["open"]:
            st["reason"] = "before the open"
        else:
            st["reason"] = "after the close"
    c = b3.clock(now)
    if c.get("next"):
        st["next_open"] = c["next"]["open"].strftime("%Y-%m-%d %H:%M")
    return st


def market_status(now_utc):
    local = to_eastern(now_utc)
    d = local.date()
    ok, reason = trading_day(d)
    st = {"market": "us", "now_new_york": local.strftime("%Y-%m-%d %H:%M"), "now_local": local.strftime("%Y-%m-%d %H:%M"),
          "tz": "New York", "date": d.isoformat(),
          "weekday": local.strftime("%A"), "calendar_known": d.year in CALENDAR_YEARS,
          "open": False, "reason": reason, "early_close": NYSE_EARLY_CLOSE.get(d.isoformat())}
    s = session(d)
    if s:
        o, c = s
        st["opens"], st["closes"] = o.strftime("%H:%M"), c.strftime("%H:%M")
        if o <= local.time() < c:
            st["open"] = True
            st["reason"] = "regular session"
        elif local.time() < o:
            st["reason"] = "before the open"
        else:
            st["reason"] = "after the close"
    # next open
    nd = d if (s and local.time() < s[0]) else d + datetime.timedelta(days=1)
    for _ in range(15):
        if session(nd):
            st["next_open"] = "%s 09:30" % nd.isoformat()
            break
        nd += datetime.timedelta(days=1)
    return st


# ---------------------------------------------------------------- quotes

def stooq_url(sym):
    return "https://stooq.com/q/l/?s=%s.us&f=sd2t2ohlcv&h&e=csv" % sym.lower().replace(".", "-")


def yahoo_url(sym):
    if b3.is_b3(sym):
        return "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1d" % b3.yahoo_symbol(sym)
    return "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1d" % (
        sym.upper().replace(".", "-"))


def parse_stooq(text, sym):
    """Symbol,Date,Time,Open,High,Low,Close,Volume -> quote. N/D means no data."""
    rows = list(csv.DictReader(io.StringIO(text.strip())))
    if not rows:
        raise AlertError("Stooq returned no rows for %s" % sym)
    r = {k.strip().lower(): (v or "").strip() for k, v in rows[0].items() if k}
    close = r.get("close", "")
    if not close or close.upper() == "N/D":
        raise AlertError("Stooq has no data for %s (check the ticker)" % sym)

    def f(k):
        v = r.get(k, "")
        try:
            return float(v)
        except ValueError:
            return None
    return {"symbol": sym.upper(), "price": float(close), "open": f("open"), "high": f("high"),
            "low": f("low"), "prev_close": None, "time": ("%s %s" % (r.get("date", ""), r.get("time", ""))).strip(),
            "source": "stooq"}


def parse_yahoo(text, sym):
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise AlertError("Yahoo returned something unexpected for %s" % sym)
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise AlertError("Yahoo has no data for %s: %s" % (sym, err.get("description", "unknown ticker")))
    m = res[0].get("meta", {})
    price = m.get("regularMarketPrice")
    if price is None:
        raise AlertError("Yahoo has no price for %s" % sym)
    t = m.get("regularMarketTime")
    when = (datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if t else "")
    q = (res[0].get("indicators", {}).get("quote") or [{}])[0]
    opens = [x for x in (q.get("open") or []) if x is not None]
    return {"symbol": sym.upper(), "price": float(price), "open": opens[-1] if opens else None,
            "high": m.get("regularMarketDayHigh"), "low": m.get("regularMarketDayLow"),
            "prev_close": m.get("previousClose") or m.get("chartPreviousClose"), "time": when,
            "currency": m.get("currency"), "source": "yahoo"}


BRAPI_FREE = {"PETR4", "VALE3", "ITUB4", "MGLU3", "MXRF11", "HGLG11"}


def brapi_url(sym):
    return "https://brapi.dev/api/v2/stocks/quote?symbols=%s" % b3.base(sym)


def parse_brapi(text, sym):
    """brapi v2: {"results": [{"requestedSymbol", "symbol", "changed", "data": {...}}]}."""
    try:
        data = json.loads(text)
    except ValueError:
        raise AlertError("brapi returned something unexpected for %s" % sym)
    res = data.get("results") or []
    if not res or not isinstance(res[0], dict) or not res[0].get("data"):
        msg = data.get("message") or data.get("error") or "no data"
        raise AlertError("brapi has no data for %s: %s" % (sym, msg))
    r = res[0]
    d = r["data"]
    price = d.get("regularMarketPrice")
    if price is None:
        raise AlertError("brapi has no price for %s" % sym)
    prev = d.get("regularMarketPreviousClose")
    if prev is None and d.get("regularMarketChange") is not None:
        prev = round(float(price) - float(d["regularMarketChange"]), 4)
    q = {"symbol": b3.base(sym), "price": float(price), "open": d.get("regularMarketOpen"),
         "high": d.get("regularMarketDayHigh"), "low": d.get("regularMarketDayLow"),
         "prev_close": prev, "time": d.get("regularMarketTime") or "",
         "currency": d.get("currency") or "BRL", "name": d.get("shortName") or d.get("longName") or "",
         "source": "brapi"}
    if r.get("changed"):
        q["renamed_to"] = r.get("symbol")
    return q


def fetch(url, timeout=20, headers=None):
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        hint = {401: " (missing or invalid key: set BRAPI_TOKEN)", 403: " (your plan does not include this)",
                429: " (quota or concurrency limit reached)"}.get(e.code, "") if "brapi.dev" in url else ""
        raise AlertError("%s answered HTTP %d%s" % (url.split("?")[0], e.code, hint))
    except urllib.error.URLError as e:
        raise AlertError("could not reach %s: %s" % (url.split("/")[2], e.reason))


def _brapi_quote(sym, offline=None):
    if offline:
        path = os.path.join(offline, "brapi-%s.json" % b3.base(sym))
        if not os.path.exists(path):
            raise AlertError("no offline quote file %s" % path)
        with open(path, encoding="utf-8") as fh:
            return parse_brapi(fh.read(), sym)
    token = os.environ.get("BRAPI_TOKEN", "").strip()
    if not token and b3.base(sym) not in BRAPI_FREE:
        raise AlertError("brapi needs a key for %s: export BRAPI_TOKEN=... (free plan at brapi.dev); "
                         "without one only %s answer" % (sym, ", ".join(sorted(BRAPI_FREE))))
    headers = {"Authorization": "Bearer " + token} if token else {}
    return parse_brapi(fetch(brapi_url(sym), headers=headers), sym)


def get_quotes(symbols, source="yahoo", offline=None, pause=PAUSE):
    """{SYM: quote} and [errors]. One request per ticker, with a pause between.

    B3 tickers: brapi first, then Yahoo (PETR4.SA) if brapi fails, unless the
    source was chosen explicitly as yahoo or brapi."""
    quotes, errors = {}, []
    for i, sym in enumerate(symbols):
        sym = b3.clean(sym)
        src = source
        if b3.is_b3(sym) and src in ("auto", "stooq", "brapi"):
            if i and pause and not offline:
                time.sleep(pause)
            try:
                quotes[sym] = _brapi_quote(sym, offline)
                continue
            except AlertError as e:
                if src == "brapi":
                    errors.append(str(e))
                    continue
                errors.append(str(e) + "; trying Yahoo")
            src = "yahoo"
        elif src in ("auto", "brapi"):
            src = "yahoo"  # brapi covers the B3; US tickers go to Yahoo
        try:
            if offline:
                ext = "csv" if src == "stooq" else "json"
                path = os.path.join(offline, "%s-%s.%s" % (src, sym, ext))
                if not os.path.exists(path):
                    raise AlertError("no offline quote file %s" % path)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            else:
                if i and pause:
                    time.sleep(pause)
                text = fetch(stooq_url(sym) if src == "stooq" else yahoo_url(sym))
            q = parse_stooq(text, sym) if src == "stooq" else parse_yahoo(text, sym)
            q["symbol"] = sym  # PETR4, not PETR4.SA
            quotes[sym] = q
        except AlertError as e:
            errors.append(str(e))
    return quotes, errors


def write_prices(path, quotes, now_utc, source):
    old = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
        except (ValueError, OSError):
            old = {}
    prices = dict(old.get("prices", {}))
    detail = dict(old.get("detail", {}))
    for s, q in quotes.items():
        prices[s] = q["price"]
        detail[s] = {"prev_close": q.get("prev_close"), "time": q.get("time"), "source": q.get("source")}
    doc = {"as_of": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": source,
           "note": "Delayed quotes for alerts and sizing checks. Your broker's price is the one that fills.",
           "prices": prices, "detail": detail}
    _write(path, doc)
    return doc


def _write(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _read(path, default):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise AlertError("%s is not valid JSON: %s" % (path, e))


# ---------------------------------------------------------------- rules

PRICE_TYPES = {"above", "below", "stop", "target", "pct_move", "opening_bell"}


def validate(rule):
    t = rule.get("type")
    if t not in PRICE_TYPES:
        raise AlertError("rule %s: unknown type %r" % (rule.get("id"), t))
    if t != "opening_bell" and not rule.get("symbol"):
        raise AlertError("rule %s needs a symbol" % rule.get("id"))
    if t in ("above", "below", "stop", "target") and not isinstance(rule.get("price"), (int, float)):
        raise AlertError("rule %s needs a numeric price" % rule.get("id"))
    if t == "pct_move" and not isinstance(rule.get("pct"), (int, float)):
        raise AlertError("rule %s needs a numeric pct" % rule.get("id"))


def evaluate(rules, quotes, status, state, now_utc):
    """Pure function. Returns (rings, new_state). Each ring: {id, symbol, message}."""
    state = json.loads(json.dumps(state or {}))
    rung = state.setdefault("rung", {})
    today = status["date"]
    rings = []
    for r in rules:
        validate(r)
        rid = r.get("id") or "%s-%s" % (r.get("symbol", "market"), r["type"])
        typ = {"stop": "below", "target": "above"}.get(r["type"], r["type"])
        if typ == "opening_bell":
            mk = r.get("market", "us")
            st = (status.get("markets") or {}).get(mk, status)
            if mk == "br" and st.get("market") != "br":
                st = b3_status(now_utc)
            if st["open"] and rung.get(rid, "")[:10] != st["date"]:
                if mk == "br":
                    msg = "Abertura: a B3 está aberta (%s, Brasília), pregão até %s." % (
                        st["now_local"], st.get("closes", "?"))
                else:
                    msg = "Opening bell: the NYSE is open (%s New York)%s." % (
                        st["now_new_york"], (", early close at 1:00 p.m. today, " + st["early_close"])
                        if st.get("early_close") else "")
                rings.append({"id": rid, "symbol": "", "message": msg})
                rung[rid] = st["date"] + now_utc.strftime("T%H:%M:%SZ")
            continue
        sym = r["symbol"].upper()
        q = quotes.get(sym)
        if not q:
            continue
        p = q["price"]
        if typ in ("above", "below"):
            hit = p >= r["price"] if typ == "above" else p <= r["price"]
            if hit and rid not in rung:
                word = "at or above" if typ == "above" else "at or below"
                label = {"stop": "stop", "target": "target"}.get(r["type"], typ)
                mk = b3.market_of(sym)
                rings.append({"id": rid, "symbol": sym, "message": "%s %s %s is %s your %s %s%s."
                              % (sym, "is" if status["open"] else "last", b3.money(p, mk, True), word, label,
                                 b3.money(r["price"], mk), (" (" + r["note"] + ")") if r.get("note") else "")})
                rung[rid] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            elif not hit and rid in rung and r.get("rearm"):
                del rung[rid]
        elif typ == "pct_move":
            ref = r.get("ref") or q.get("prev_close") or q.get("open")
            if not ref:
                continue
            move = 100.0 * (p / float(ref) - 1)
            want = r.get("direction")
            hit = abs(move) >= r["pct"] and (not want or (want == "up") == (move > 0))
            if hit and rung.get(rid, "")[:10] != today:
                mk = b3.market_of(sym)
                rings.append({"id": rid, "symbol": sym, "message": "%s moved %+.2f%% to %s (from %s)."
                              % (sym, move, b3.money(p, mk, True), b3.money(float(ref), mk, True))})
                rung[rid] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    state["last_check"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return rings, state


def _n(x):
    x = float(x)
    return str(int(x)) if x == int(x) else "%.2f" % x


# ---------------------------------------------------------------- commands

def holdings(a):
    syms = []
    pf = _read(a.portfolio, {})
    for p in pf.get("positions", []):
        syms.append(str(p.get("ticker") or p.get("symbol") or "").upper())
    tg = _read(a.targets, {})
    for w in tg.get("weights", []) if isinstance(tg, dict) else []:
        syms.append(str(w.get("ticker") or w.get("symbol") or "").upper())
    return [s for s in syms if s]


def _dedupe(items):
    out = []
    for s in items:
        if s and s not in out:
            out.append(s)
    return out


def config_market(a):
    m = getattr(a, "market", None)
    if m:
        return m
    cfg = _read(getattr(a, "config", "trader/config.json"), {})
    return str(cfg.get("market") or "us").lower()


def cmd_clock(a):
    mk = config_market(a)
    if mk == "br":
        st = b3_status(parse_now(a.now, "br"))
        if a.json:
            print(json.dumps(st, indent=2))
            return 0 if st["open"] else 1
        print("Brasília %s: B3 %s, %s." % (st["now_local"], "ABERTA" if st["open"] else "fechada", {
            "regular session": "pregão regular", "before the open": "antes da abertura",
            "after the close": "depois do fechamento", "weekend": "fim de semana"}.get(st["reason"], st["reason"])))
        if st.get("opens"):
            print("Pregão de hoje (mercado à vista): %s às %s%s." % (st["opens"], st["closes"],
                  (" (%s)" % st["note"]) if st.get("note") else ""))
        if not st["open"] and st.get("next_open"):
            print("Próxima abertura: %s (Brasília)." % st["next_open"])
        if st.get("provisional"):
            print("Calendário de %s provisório: a B3 ainda não publicou. Confira em b3.com.br." % st["date"][:4])
        if not st["calendar_known"]:
            print("Calendário da B3 só cobre %s: confira em b3.com.br." % " e ".join(map(str, sorted(b3.HOLIDAYS))))
        print("Horário segue o horário de verão dos EUA (16h55 ou 17h55 de fechamento); a B3 anuncia por ofício circular.")
        return 0 if st["open"] else 1
    st = market_status(parse_now(a.now))
    if a.json:
        print(json.dumps(st, indent=2))
    else:
        print("New York %s (%s): NYSE %s, %s." % (st["now_new_york"], st["weekday"],
                                                  "OPEN" if st["open"] else "closed", st["reason"]))
        if st.get("opens"):
            print("Today's session: %s to %s%s." % (st["opens"], st["closes"],
                                                    (" (early close: %s)" % st["early_close"]) if st.get("early_close") else ""))
        if not st["open"] and st.get("next_open"):
            print("Next open: %s New York." % st["next_open"])
        if not st["calendar_known"]:
            print("Holiday list covers %s only: check nyse.com for this date." % " and ".join(map(str, CALENDAR_YEARS)))
    return 0 if st["open"] else 1


def cmd_quote(a):
    syms = _dedupe([b3.clean(s) for s in a.symbols] + (holdings(a) if a.holdings else []))
    if not syms:
        raise AlertError("which tickers? alerts.py quote AAPL KO, or --holdings")
    now = parse_now(a.now)
    quotes, errors = get_quotes(syms, a.source, a.offline)
    if a.write and quotes:
        write_prices(a.write, quotes, now, a.source)
    if a.json:
        print(json.dumps({"quotes": quotes, "errors": errors}, indent=2))
    else:
        for s in syms:
            q = quotes.get(s)
            if q:
                chg = ""
                if q.get("prev_close"):
                    chg = " (%+.2f%% vs prev close $%.2f)" % (100.0 * (q["price"] / q["prev_close"] - 1), q["prev_close"])
                mk = b3.market_of(s)
                if q.get("prev_close"):
                    chg = " (%+.2f%% vs prev close %s)" % (100.0 * (q["price"] / q["prev_close"] - 1),
                                                          b3.money(q["prev_close"], mk, True))
                print("%-6s %s%s  %s  [%s]" % (s, b3.money(q["price"], mk, True), chg, q.get("time", ""), q["source"]))
        for e in errors:
            print("error: " + e)
        if a.write and quotes:
            print("Wrote %d price(s) to %s." % (len(quotes), a.write))
        print("Quotes are delayed and for alerts only. Your broker's price is the one that fills.")
    return 0 if quotes else 1


def cmd_check(a):
    doc = _read(a.rules, None)
    if not doc or not doc.get("rules"):
        raise AlertError("no rules in %s: add one with alerts.py add --symbol AAPL --above 350" % a.rules)
    rules = doc["rules"]
    mk = config_market(a)
    now = parse_now(a.now, mk)
    status = b3_status(now) if mk == "br" else market_status(now)
    status["markets"] = {"us": market_status(now), "br": b3_status(now)}
    syms = _dedupe([b3.clean(r.get("symbol", "")) for r in rules if r.get("type") != "opening_bell"])
    quotes, errors = (get_quotes(syms, a.source, a.offline) if syms else ({}, []))
    state = _read(a.state, {})
    rings, state = evaluate(rules, quotes, status, state, now)
    if not a.no_write:
        _write(a.state, state)
        if quotes:
            write_prices(a.prices_out, quotes, now, a.source)
    if a.json:
        status.pop("markets", None)
        print(json.dumps({"market": status, "rings": rings, "errors": errors,
                          "quotes": {s: q["price"] for s, q in quotes.items()}}, indent=2))
    else:
        print("%s %s (%s %s, %s)." % ("B3" if mk == "br" else "NYSE", "OPEN" if status["open"] else "closed",
                                       status["now_local"], status["tz"], status["reason"]))
        for r in rings:
            print("ALERT " + r["message"])
        if not rings:
            print("Nothing hit. %d rule(s) watched." % len(rules))
        for e in errors:
            print("error: " + e)
        if rings:
            print("An alert is information, not an order. To act on one, size it (trader-budget or "
                  "trader-rebalance), check it (trader-risk) and say yes to it (trader-broker).")
    return 0 if rings else 1


def cmd_add(a):
    doc = _read(a.rules, {"rules": []})
    doc.setdefault("rules", [])
    if a.opening_bell:
        mk = config_market(a)
        rule = {"id": a.id or ("opening-bell" if mk == "us" else "abertura-b3"), "type": "opening_bell"}
        if mk == "br":
            rule["market"] = "br"
    else:
        if not a.symbol:
            raise AlertError("--symbol is required (or --opening-bell)")
        sym = b3.clean(a.symbol)
        if a.above is not None:
            rule = {"type": "above", "price": a.above}
        elif a.below is not None:
            rule = {"type": "below", "price": a.below}
        elif a.stop is not None:
            rule = {"type": "stop", "price": a.stop}
        elif a.pct is not None:
            rule = {"type": "pct_move", "pct": a.pct}
            if a.direction:
                rule["direction"] = a.direction
        else:
            raise AlertError("give one of --above, --below, --stop or --pct")
        val = rule.get("price", rule.get("pct"))
        rule = dict({"id": a.id or ("%s-%s-%s" % (sym.lower(), rule["type"], _n(val)))}, symbol=sym, **rule)
        if a.rearm:
            rule["rearm"] = True
        if a.note:
            rule["note"] = a.note
    validate(rule)
    if any(r.get("id") == rule["id"] for r in doc["rules"]):
        raise AlertError("a rule with id %s already exists" % rule["id"])
    doc["rules"].append(rule)
    _write(a.rules, doc)
    print("Added %s: %s" % (rule["id"], json.dumps(rule)))
    return 0


def cmd_list(a):
    doc = _read(a.rules, {"rules": []})
    state = _read(a.state, {})
    if not doc.get("rules"):
        print("No rules yet.")
        return 1
    for r in doc["rules"]:
        rid = r.get("id")
        rung = state.get("rung", {}).get(rid)
        print("%-24s %s%s" % (rid, json.dumps({k: v for k, v in r.items() if k != "id"}),
                              ("  (rang %s)" % rung) if rung else ""))
    return 0


def cmd_reset(a):
    state = _read(a.state, {})
    if a.id not in state.get("rung", {}):
        print("%s has not rung (nothing to reset)." % a.id)
        return 1
    del state["rung"][a.id]
    _write(a.state, state)
    print("Re-armed %s." % a.id)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Price alerts and the NYSE clock (trader-alerts).")
    sub = ap.add_subparsers(dest="cmd")

    def net(p):
        p.add_argument("--source", default="auto", choices=["auto", "brapi", "yahoo", "stooq"],
                       help="auto: brapi then Yahoo for B3 tickers, Yahoo for US tickers")
        p.add_argument("--offline", metavar="DIR", help="read <source>-<TICKER>.json|csv files, no network")
        p.add_argument("--now", help="pretend it is this time (ISO; no offset = New York time)")
        p.add_argument("--json", action="store_true")

    def mkt(p):
        p.add_argument("--market", choices=["us", "br"], help="NYSE (us) or B3 (br); default from trader/config.json")
        p.add_argument("--config", default="trader/config.json")

    p = sub.add_parser("clock", help="is the NYSE (or the B3) open?")
    p.add_argument("--now")
    p.add_argument("--json", action="store_true")
    mkt(p)
    p = sub.add_parser("quote", help="latest delayed quotes")
    net(p)
    p.add_argument("symbols", nargs="*")
    p.add_argument("--holdings", action="store_true", help="add tickers from your portfolio and targets")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--targets", default="trader/targets.json")
    p.add_argument("--write", nargs="?", const="trader/prices.json", metavar="PATH",
                   help="save to prices.json (default trader/prices.json)")
    p = sub.add_parser("check", help="check every rule, ring what hit")
    net(p)
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p.add_argument("--prices-out", default="trader/prices.json")
    p.add_argument("--no-write", action="store_true")
    mkt(p)
    p = sub.add_parser("add", help="add a rule")
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--symbol")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--above", type=float)
    g.add_argument("--below", type=float)
    g.add_argument("--stop", type=float)
    g.add_argument("--pct", type=float)
    g.add_argument("--opening-bell", action="store_true")
    p.add_argument("--direction", choices=["up", "down"])
    p.add_argument("--rearm", action="store_true")
    p.add_argument("--note")
    p.add_argument("--id")
    mkt(p)
    p = sub.add_parser("list", help="list the rules")
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p = sub.add_parser("reset", help="re-arm a rule that rang")
    p.add_argument("id")
    p.add_argument("--state", default="trader/state/alerts.json")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"clock": cmd_clock, "quote": cmd_quote, "check": cmd_check, "add": cmd_add,
                "list": cmd_list, "reset": cmd_reset}[a.cmd](a)
    except AlertError as e:
        print("alerts.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
