#!/usr/bin/env python3
"""Regras da B3 compartilhadas pelas skills trader-*. Só biblioteca padrão, sem rede.

Este arquivo é copiado, idêntico, para cada skill que opera na B3 (cada skill
precisa funcionar sozinha). O teste tests/test_repo.py confere que as cópias
são iguais: edite uma, rode `python3 tests/sync_b3.py` e todas são atualizadas.

O que ele sabe:

- reconhecer um ticker da B3 (PETR4, VALE3, TAEE11, BOVA11, AAPL34, PETR4F)
- classificar o ativo: ação, unit, FII, ETF ou BDR (com a lista de ETFs e
  units conhecidos em b3_ativos.json; um "11" fora das listas é tratado como
  FII e marcado como suposição)
- lote padrão (100 para ações e units, 1 para FIIs, ETFs e BDRs) e a divisão
  de uma quantidade em lote padrão + mercado fracionário (ticker + "F")
- calendário de pregões da B3 (2026 publicado pela B3; 2027 provisório) e o
  horário do mercado à vista, que muda com o horário de verão dos EUA
- formatar reais: R$ 1.234,56

Fontes (lidas em 2026-10-26): Calendário de negociação da B3 2026
(b3.com.br, notícia "Calendário de negociação da B3: confira o funcionamento
da bolsa em 2026"), mudança de horário de 09/03/2026 (10h00 às 16h55) e de
03/11/2025 (10h00 às 17h55, fim do horário de verão nos EUA).
"""

import datetime
import json
import os
import re

BRT = datetime.timezone(datetime.timedelta(hours=-3))  # Brasil sem horário de verão desde 2019

# ---------------------------------------------------------------- tickers

_TICKER = re.compile(r"^([A-Z0-9]{4})(\d{1,2})(F?)$")

# finais de BDR: 31-35 (não patrocinados e patrocinados), 39 (BDR de ETF)
_BDR_ENDINGS = {"31", "32", "33", "34", "35", "39"}
_SHARE_ENDINGS = {"3", "4", "5", "6", "7", "8"}  # ON, PN, PNA, PNB, PNC, PND

_HERE = os.path.dirname(os.path.abspath(__file__))


def clean(ticker):
    """' petr4.sa ' -> 'PETR4'. Tira espaços, o sufixo .SA do Yahoo e põe em maiúsculas."""
    t = str(ticker or "").strip().upper()
    if t.endswith(".SA"):
        t = t[:-3]
    return t


def is_b3(ticker):
    """True para tickers no formato da B3: 4 caracteres + 1 ou 2 dígitos (+ F)."""
    m = _TICKER.match(clean(ticker))
    if not m:
        return False
    end = m.group(2)
    return end in _SHARE_ENDINGS or end == "11" or end in _BDR_ENDINGS


def base(ticker):
    """PETR4F -> PETR4 (o ticker do lote padrão)."""
    t = clean(ticker)
    m = _TICKER.match(t)
    if m and m.group(3) == "F":
        return m.group(1) + m.group(2)
    return t


def fractional(ticker):
    """PETR4 -> PETR4F (o ticker do mercado fracionário)."""
    return base(ticker) + "F"


def market_of(ticker, default="us"):
    """'br' para tickers da B3, senão o padrão ('us')."""
    t = clean(ticker)
    if str(ticker or "").strip().upper().endswith(".SA") or is_b3(t):
        return "br"
    return default


def yahoo_symbol(ticker):
    """PETR4 -> PETR4.SA (o símbolo que o Yahoo Finance usa para a B3)."""
    return base(ticker) + ".SA"


# ---------------------------------------------------------------- tipo de ativo

def _load_assets():
    path = os.path.join(_HERE, "b3_ativos.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    return {k: {clean(t) for t in data.get(k, [])} for k in ("etf", "unit", "fii", "bdr")}


_ASSETS = None


def known_assets():
    global _ASSETS
    if _ASSETS is None:
        _ASSETS = _load_assets()
    return _ASSETS


def asset_type(ticker, overrides=None):
    """Classe do ativo para lote e imposto.

    Retorna (tipo, suposicao): tipo em 'acao', 'unit', 'fii', 'etf', 'bdr' ou
    'desconhecido'; suposicao=True quando o tipo foi deduzido só pelo final do
    ticker (um "11" fora das listas é tratado como FII). `overrides` é um dict
    {ticker: tipo} do trader/config.json ("asset_types"), que sempre vence."""
    t = base(ticker)
    over = {clean(k): v for k, v in (overrides or {}).items()}
    if t in over:
        return over[t], False
    m = _TICKER.match(t)
    if not m:
        return "desconhecido", True
    end = m.group(2)
    known = known_assets()
    for kind in ("etf", "unit", "fii", "bdr"):
        if t in known[kind]:
            return kind, False
    if end in _SHARE_ENDINGS:
        return "acao", False
    if end in _BDR_ENDINGS:
        return "bdr", False
    if end == "11":
        return "fii", True
    return "desconhecido", True


TYPE_NAMES = {"acao": "ação", "unit": "unit", "fii": "FII", "etf": "ETF", "bdr": "BDR",
              "desconhecido": "tipo desconhecido"}


def round_lot(ticker, overrides=None, lots=None):
    """Lote padrão: 100 para ações e units; 1 para FIIs, ETFs e BDRs.

    `lots` ({ticker: n}, "round_lots" no config) vence o padrão. Confira o lote
    no home broker antes de operar: a B3 pode mudar o lote de um ativo."""
    t = base(ticker)
    lots = {clean(k): int(v) for k, v in (lots or {}).items()}
    if t in lots:
        return lots[t]
    kind, _ = asset_type(t, overrides)
    return 100 if kind in ("acao", "unit") else 1


def split_lot(qty, lot):
    """327 ações com lote 100 -> (300, 27): 300 no lote padrão, 27 no fracionário.

    No fracionário só se negociam de 1 até (lote - 1) ações por ordem."""
    qty = int(qty)
    if lot <= 1:
        return qty, 0
    return (qty // lot) * lot, qty % lot


def tick(price):
    """Arredonda para o tick de R$ 0,01 do mercado à vista."""
    return round(round(float(price) * 100) / 100.0, 2)


# ---------------------------------------------------------------- calendário

# Dias sem pregão, publicados pela B3 para 2026 (inclui 24 e 31/12).
HOLIDAYS = {
    2026: {
        "2026-01-01": "Confraternização Universal",
        "2026-02-16": "Carnaval", "2026-02-17": "Carnaval",
        "2026-04-03": "Sexta-feira Santa",
        "2026-04-21": "Tiradentes",
        "2026-05-01": "Dia do Trabalho",
        "2026-06-04": "Corpus Christi",
        "2026-09-07": "Independência",
        "2026-10-12": "Nossa Senhora Aparecida",
        "2026-11-02": "Finados",
        "2026-11-20": "Consciência Negra",
        "2026-12-24": "Véspera de Natal (sem pregão)",
        "2026-12-25": "Natal",
        "2026-12-31": "Último dia do ano (sem pregão)",
    },
    # 2027: feriados nacionais pelo calendário (Páscoa em 28/03/2027) e o mesmo
    # padrão de 2026. A B3 ainda não publicou o calendário de 2027: provisório.
    2027: {
        "2027-01-01": "Confraternização Universal",
        "2027-02-08": "Carnaval", "2027-02-09": "Carnaval",
        "2027-03-26": "Sexta-feira Santa",
        "2027-04-21": "Tiradentes",
        "2027-05-27": "Corpus Christi",
        "2027-09-07": "Independência",
        "2027-10-12": "Nossa Senhora Aparecida",
        "2027-11-02": "Finados",
        "2027-11-15": "Proclamação da República",
        "2027-12-24": "Véspera de Natal (sem pregão)",
        "2027-12-31": "Último dia do ano (sem pregão)",
    },
}
PROVISIONAL_YEARS = {2027}

# Quarta-feira de Cinzas: pregão só à tarde.
LATE_OPEN = {"2026-02-18": (13, 0), "2027-02-10": (13, 0)}


def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def us_dst(day):
    """Horário de verão dos EUA: do 2º domingo de março ao 1º domingo de novembro."""
    return _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1)


def holiday(day):
    """Nome do feriado da B3 nesse dia, ou None. Levanta KeyError se o ano é desconhecido."""
    if day.year not in HOLIDAYS:
        raise KeyError(day.year)
    return HOLIDAYS[day.year].get(day.isoformat())


def is_trading_day(day):
    if day.weekday() >= 5:
        return False
    return holiday(day) is None


def session(day):
    """Horário do mercado à vista em `day` (horário de Brasília), ou None se não há pregão.

    Negociação contínua das 10h00 até 16h55 quando os EUA estão no horário de
    verão, e até 17h55 fora dele; o call de fechamento vem logo depois (cerca
    de 5 minutos). A B3 anuncia cada mudança por ofício circular: confira."""
    if not is_trading_day(day):
        return None
    oh, om = LATE_OPEN.get(day.isoformat(), (10, 0))
    close = (16, 55) if us_dst(day) else (17, 55)
    return {
        "open": datetime.datetime(day.year, day.month, day.day, oh, om, tzinfo=BRT),
        "close": datetime.datetime(day.year, day.month, day.day, close[0], close[1], tzinfo=BRT),
        "provisional": day.year in PROVISIONAL_YEARS,
        "note": "abertura tardia (Quarta-feira de Cinzas)" if day.isoformat() in LATE_OPEN else "",
    }


def now_brt():
    return datetime.datetime.now(BRT)


def clock(now=None):
    """Situação da B3 agora: aberta ou fechada, e o próximo pregão."""
    now = (now or now_brt()).astimezone(BRT)
    today = now.date()
    try:
        s = session(today)
    except KeyError:
        return {"known": False, "now": now, "open": False,
                "note": "calendário da B3 para %d desconhecido" % today.year}
    if s and s["open"] <= now < s["close"]:
        return {"known": True, "now": now, "open": True, "session": s, "closes": s["close"]}
    day = today if (s and now < s["open"]) else today + datetime.timedelta(days=1)
    for _ in range(30):
        try:
            nxt = session(day)
        except KeyError:
            return {"known": False, "now": now, "open": False,
                    "note": "calendário da B3 para %d desconhecido" % day.year}
        if nxt:
            return {"known": True, "now": now, "open": False, "next": nxt,
                    "holiday": holiday(today) if today.weekday() < 5 else None}
        day += datetime.timedelta(days=1)
    return {"known": False, "now": now, "open": False, "note": "sem pregão nos próximos 30 dias?"}


def last_business_day(year, month):
    """Último dia útil do mês (vencimento do DARF de renda variável).

    Usa o calendário de pregões como aproximação de dia útil bancário. A
    véspera de Natal (24/12) tem expediente bancário e conta como dia útil;
    31/12 não tem atendimento ao público e não conta."""
    if month == 12:
        day = datetime.date(year, 12, 31)
    else:
        day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    for _ in range(10):
        if day.weekday() < 5:
            try:
                h = holiday(day)
            except KeyError:
                h = None
            if h is None or h.startswith("Véspera de Natal"):
                return day
        day -= datetime.timedelta(days=1)
    return day


# ---------------------------------------------------------------- dinheiro

def brl(x, cents=True):
    """1234.5 -> 'R$ 1.234,50' (com cents=False: 'R$ 1.235')."""
    x = float(x)
    neg = x < 0
    s = "{:,.2f}".format(abs(x)) if cents else "{:,.0f}".format(abs(x))
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if neg else "R$ ") + s


def money(x, market="br", cents=None):
    """Formata no padrão do mercado: R$ 1.234,56 (br) ou $1,234.56 (us)."""
    x = float(x)
    whole = abs(x - round(x)) < 0.005
    if cents is None:
        cents = not whole
    if market == "br":
        return brl(x, cents)
    return ("-$" if x < 0 else "$") + ("{:,.2f}".format(abs(x)) if cents else "{:,.0f}".format(abs(round(x))))


def parse_brl(text):
    """'R$ 1.234,56' -> 1234.56; '1234.56' -> 1234.56; '1.234' -> 1234.0."""
    s = str(text).strip().replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.match(r"^-?\d{1,3}(\.\d{3})+$", s):
        s = s.replace(".", "")
    return float(s)
