#!/usr/bin/env python3
"""Monitor de notícias da B3 (trader-news, mercado BR). Só biblioteca padrão.

Lê duas fontes para cada ativo que você tem (ou vai copiar) e mostra só o
que é novo desde a última checagem, do mais recente para o mais antigo:

  1. IPE da CVM: todo fato relevante, comunicado ao mercado, aviso aos
     acionistas (dividendos, JCP, bonificação), release de resultados e
     assembleia que a companhia protocola. É o que a empresa disse
     oficialmente. https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_AAAA.zip
  2. Google Notícias em português, uma busca por ticker:
     https://news.google.com/rss/search?q=PETR4&hl=pt-BR&gl=BR&ceid=BR:pt-419

    python3 noticias.py                               # tickers de trader/portfolio.json ou targets.json
    python3 noticias.py --tickers PETR4 VALE3 --dias 3
    python3 noticias.py --sem-google                  # só documentos da CVM
    python3 noticias.py --todos                       # inclui o que já foi visto

FIIs, ETFs e BDRs não protocolam no IPE das companhias abertas: para eles só
as manchetes rodam (FIIs publicam fatos relevantes no Fundos.NET da B3).

Estado: trader/state/noticias.json (o que já foi mostrado, 30 dias).
Offline (testes): --offline DIR lê ipe_cia_aberta_AAAA.zip, fca_cia_aberta_AAAA.zip
e google-<TICKER>.xml de DIR.
"""

import argparse
import datetime as dt
import email.utils
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import b3  # noqa: E402
import cvm  # noqa: E402

GOOGLE = "https://news.google.com/rss/search?q=%s&hl=pt-BR&gl=BR&ceid=BR:pt-419"
UA = "Mozilla/5.0 (compatible; trader-skill/1.1)"
KEEP_DAYS = 30

COL = {
    "cnpj": ("CNPJ_Companhia",), "nome": ("Nome_Companhia",), "ref": ("Data_Referencia",),
    "categoria": ("Categoria",), "tipo": ("Tipo",), "especie": ("Especie",), "assunto": ("Assunto",),
    "entrega": ("Data_Entrega",), "protocolo": ("Protocolo_Entrega",), "versao": ("Versao",),
    "link": ("Link_Download",), "apresentacao": ("Tipo_Apresentacao",),
}

# categorias do IPE que importam, com o selo mostrado
IMPORTANT = {
    "fato relevante": "FATO RELEVANTE",
    "comunicado ao mercado": "comunicado",
    "aviso aos acionistas": "aviso aos acionistas",
    "dados economico-financeiros": "resultados",
    "assembleia": "assembleia",
    "calendario de eventos corporativos": "calendário",
    "reuniao da administracao": "reunião da administração",
    "valores mobiliarios negociados e detidos": "insiders",
}
TAGS = [
    ("resultado", r"resultado|lucro|receita|ebitda|balan[cç]o|trimestr|\b\dT\d{2}\b|guidance|proje[cç]"),
    ("proventos", r"dividend|juros sobre (o )?capital|\bjcp\b|provento|bonifica|desdobr|grupamento|recompra"),
    ("jurídico", r"processo|a[cç][aã]o judicial|cvm|investiga|multa|acordo|tribunal|justi[cç]a|cade"),
    ("negócio", r"aquisi|fus[aã]o|incorpora|venda de ativo|desinvest|oferta|follow.?on|ipo|privatiza"),
    ("pessoas", r"\bceo\b|presidente|diretor|conselh|ren[uú]ncia|elei[cç][aã]o|nomea"),
    ("risco", r"recupera[cç][aã]o judicial|fal[eê]ncia|default|inadimpl|rebaixa|downgrade|rating|vazamento|ataque"),
]


class NewsError(Exception):
    pass


def load_json(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def watch_from_files(portfolio="trader/portfolio.json", targets="trader/targets.json"):
    for path, key in ((portfolio, "positions"), (targets, "weights")):
        doc = load_json(path)
        if doc and doc.get(key):
            out = []
            for p in doc[key]:
                t = b3.base(p.get("ticker") or p.get("symbol") or "")
                if t and b3.is_b3(t) and t not in out:
                    out.append(t)
            if out:
                return out, path
    return [], None


def ipe_docs(year, offline=None):
    z = cvm.download("CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_%d.zip" % year, max_age=6, offline=offline)
    out = []
    for r in cvm.rows(z, contains="ipe_cia_aberta"):
        g = lambda k: cvm.pick(r, *COL[k], default="") or ""  # noqa: E731
        cat = g("categoria")
        label = IMPORTANT.get(cvm.fold(cat))
        if not label:
            continue
        out.append({"source": "CVM", "cnpj": cvm.digits(g("cnpj")).zfill(14), "company": g("nome"),
                    "category": cat, "label": label, "type": g("tipo"), "species": g("especie"),
                    "title": (g("assunto") or g("tipo") or cat).strip(), "date": g("entrega")[:10] or g("ref")[:10],
                    "ref": g("ref")[:10], "link": g("link"), "id": g("protocolo") or g("link"),
                    "version": g("versao")})
    return out


def parse_rss(data, ticker):
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise NewsError("o feed de %s não é XML válido" % ticker)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        when = it.findtext("pubDate") or ""
        try:
            d = email.utils.parsedate_to_datetime(when).astimezone(dt.timezone.utc)
        except (TypeError, ValueError):
            d = None
        src = it.find("source")
        out.append({"source": (src.text if src is not None and src.text else "Google Notícias"),
                    "tickers": [ticker], "title": title, "link": link,
                    "date": d.strftime("%Y-%m-%d") if d else "", "time": d.isoformat() if d else "",
                    "id": link or title, "label": "manchete"})
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise NewsError("%s respondeu HTTP %d" % (url.split("?")[0], e.code))
    except urllib.error.URLError as e:
        raise NewsError("não consegui acessar %s: %s" % (url.split("/")[2], e.reason))


def google(ticker, offline=None):
    if offline:
        p = os.path.join(offline, "google-%s.xml" % ticker)
        if not os.path.exists(p):
            return []
        with open(p, "rb") as fh:
            return parse_rss(fh.read(), ticker)
    q = urllib.parse.quote('"%s"' % ticker)
    return parse_rss(fetch(GOOGLE % q), ticker)


def tag(item):
    text = cvm.fold(item.get("title", "") + " " + item.get("type", "") + " " + item.get("species", ""))
    tags = [name for name, rx in TAGS if re.search(rx, text, re.I)]
    item["tags"] = tags
    return item


def fp(item):
    return hashlib.sha1(("%s|%s" % (item["source"], item["id"])).encode("utf-8")).hexdigest()[:16]


def collect(tickers, year, offline=None, use_google=True, errors=None):
    errors = errors if errors is not None else []
    items = []
    try:
        tmap = cvm.ticker_map(year, offline)
    except cvm.CVMError as e:
        tmap = {}
        errors.append("FCA da CVM indisponível (%s): sem documentos do IPE" % e)
    by_cnpj = {}
    for t in tickers:
        info = tmap.get(t)
        if info:
            by_cnpj.setdefault(info["cnpj"].zfill(14), []).append(t)
    if by_cnpj:
        try:
            for d in ipe_docs(year, offline):
                if d["cnpj"] in by_cnpj:
                    d["tickers"] = by_cnpj[d["cnpj"]]
                    items.append(d)
        except cvm.CVMError as e:
            errors.append("IPE da CVM indisponível: %s" % e)
    if use_google:
        for t in tickers:
            try:
                items.extend(google(t, offline))
            except NewsError as e:
                errors.append(str(e))
    return [tag(i) for i in items]


def select(items, state, since, show_all=False):
    seen = state.setdefault("vistos", {})
    out, keys = [], set()
    for it in items:
        k = fp(it)
        if k in keys:
            continue
        keys.add(k)
        if it.get("date") and it["date"] < since:
            continue
        if not show_all and k in seen:
            continue
        out.append(it)
    out.sort(key=lambda i: (i.get("label") != "FATO RELEVANTE", i.get("time") or i.get("date") or ""), reverse=False)
    out.sort(key=lambda i: i.get("date") or "", reverse=True)
    return out


def remember(items, state, today):
    seen = state.setdefault("vistos", {})
    for it in items:
        seen[fp(it)] = today
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["vistos"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["ultima_checagem"] = today


def render(items, errors, weights=None):
    lines = []
    for it in items:
        mark = "!" if it.get("label") in ("FATO RELEVANTE", "resultados", "aviso aos acionistas") else " "
        tk = "/".join(it.get("tickers", []))
        w = ""
        if weights:
            ws = [weights[t] for t in it.get("tickers", []) if t in weights]
            if ws:
                w = " (%.1f%% da carteira)" % max(ws)
        lines.append("%s %s %-7s [%s] %s%s" % (mark, it.get("date", "")[:10], tk, it["label"], it["title"][:110], w))
        extra = []
        if it.get("company"):
            extra.append(it["company"])
        if it.get("tags"):
            extra.append(", ".join(it["tags"]))
        extra.append(it.get("link") or it.get("source"))
        lines.append("    " + " | ".join(e for e in extra if e))
    if not items:
        lines.append("Nada novo.")
    for e in errors:
        lines.append("erro: " + e)
    lines.append("")
    lines.append("Manchete é pista, não fato: abra o documento da CVM antes de agir. O documento protocolado "
                 "vale mais que a manchete.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Notícias e documentos da CVM para ativos da B3 (trader-news).")
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--dias", type=int, default=2, help="janela em dias (padrão 2)")
    ap.add_argument("--todos", action="store_true", help="mostra também o que já foi visto")
    ap.add_argument("--sem-google", action="store_true")
    ap.add_argument("--state", default="trader/state/noticias.json")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--targets", default="trader/targets.json")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--hoje", help="AAAA-MM-DD (testes)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    today = a.hoje or dt.date.today().isoformat()
    tickers = [b3.base(t) for t in (a.tickers or [])]
    src = "--tickers"
    if not tickers:
        tickers, src = watch_from_files(a.portfolio, a.targets)
    if not tickers:
        print("noticias.py: quais ativos? Use --tickers PETR4 VALE3 ou crie trader/portfolio.json", file=sys.stderr)
        return 2
    weights = {}
    tg = load_json(a.targets) or {}
    for w in tg.get("weights", []):
        weights[b3.base(w.get("ticker", ""))] = float(w.get("weight") or 0)
    state = load_json(a.state) or {}
    errors = []
    year = int(today[:4])
    items = collect(tickers, year, a.offline, not a.sem_google, errors)
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=a.dias)).isoformat()
    shown = select(items, state, since, a.todos)
    if not a.dry_run:
        remember(shown, state, today)
        d = os.path.dirname(a.state)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
    if a.json:
        print(json.dumps({"tickers": tickers, "itens": shown, "erros": errors}, indent=2, ensure_ascii=False))
    else:
        print("Ativos (%s): %s" % (src, " ".join(tickers)))
        print(render(shown, errors, weights))
    return 0 if shown else 1


if __name__ == "__main__":
    sys.exit(main())
