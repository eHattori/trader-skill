#!/usr/bin/env python3
"""Acesso aos dados abertos da CVM (dados.cvm.gov.br). Só biblioteca padrão.

Copiado, idêntico, para cada skill que lê a CVM (copycat, insiders, news,
analyst); tests/test_repo.py confere as cópias e `python3 tests/sync_b3.py`
as atualiza.

Os arquivos da CVM são zips com CSVs em latin-1, separados por ";". Os nomes
das colunas mudaram ao longo do tempo (por exemplo CNPJ_FUNDO virou
CNPJ_FUNDO_CLASSE com a Resolução CVM 175), por isso cada coluna é lida por
uma lista de nomes possíveis (`pick`). Quando nenhum nome bate, o erro diz
quais colunas o arquivo tem: rode o comando `colunas` da skill e corrija a
lista de aliases.

Downloads ficam em trader/cache/cvm/ e são reaproveitados por `max_age`
horas (a CVM atualiza os arquivos do ano corrente semanalmente ou diariamente).
"""

import csv
import io
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile

BASE = "https://dados.cvm.gov.br/dados"
UA = "trader-skill/1.1 (+https://github.com/eHattori/trader-skill)"
CACHE = os.path.join("trader", "cache", "cvm")

csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))


class CVMError(Exception):
    pass


def fold(text):
    """'Ações ON' -> 'acoes on': sem acento, minúsculas, espaços simples."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def digits(text):
    return "".join(c for c in str(text or "") if c.isdigit())


def fmt_cnpj(text):
    d = digits(text).zfill(14)
    return "%s.%s.%s/%s-%s" % (d[:2], d[2:5], d[5:8], d[8:12], d[12:])


def url(path):
    return BASE + "/" + path.lstrip("/")


def download(path, cache_dir=CACHE, max_age=24, offline=None):
    """Baixa BASE/path para o cache e devolve o caminho local.

    offline=DIR: lê DIR/<nome do arquivo> e nunca usa a rede (testes)."""
    name = path.rstrip("/").split("/")[-1]
    if offline:
        local = os.path.join(offline, name)
        if not os.path.exists(local):
            raise CVMError("arquivo offline %s não existe" % local)
        return local
    os.makedirs(cache_dir, exist_ok=True)
    local = os.path.join(cache_dir, name)
    if os.path.exists(local) and (time.time() - os.path.getmtime(local)) < max_age * 3600:
        return local
    req = urllib.request.Request(url(path), headers={"User-Agent": UA})
    tmp = local + ".part"
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
    except urllib.error.HTTPError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        if e.code == 404:
            raise CVMError("a CVM ainda não publicou %s (HTTP 404)" % url(path))
        raise CVMError("%s respondeu HTTP %d" % (url(path), e.code))
    except urllib.error.URLError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        if os.path.exists(local):
            return local  # usa o cache antigo se a rede caiu
        raise CVMError("não consegui acessar dados.cvm.gov.br: %s" % e.reason)
    os.replace(tmp, local)
    return local


def members(zpath, contains=""):
    with zipfile.ZipFile(zpath) as z:
        return [n for n in z.namelist() if fold(contains) in fold(n)]


def rows(zpath, member=None, contains=None, encoding="latin-1"):
    """Itera as linhas (dict) de um CSV dentro do zip (ou de um .csv solto)."""
    if zpath.lower().endswith(".csv"):
        fh = open(zpath, encoding=encoding, newline="")
        try:
            yield from csv.DictReader(fh, delimiter=";")
        finally:
            fh.close()
        return
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        if member is None:
            cands = [n for n in names if contains is None or fold(contains) in fold(n)]
            cands = [n for n in cands if n.lower().endswith(".csv")]
            if not cands:
                raise CVMError("nenhum CSV com %r dentro de %s (tem: %s)" % (contains, zpath, ", ".join(names[:12])))
            member = sorted(cands, key=len)[0]
        with z.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding=encoding, newline="")
            yield from csv.DictReader(text, delimiter=";")


def header(zpath, member=None, contains=None):
    for r in rows(zpath, member, contains):
        return list(r.keys())
    return []


def pick(row, *names, default=None):
    """Valor da primeira coluna existente entre `names` (ignora caixa e acento)."""
    for n in names:
        if n in row:
            return row[n]
    low = {fold(k): k for k in row}
    for n in names:
        k = low.get(fold(n))
        if k is not None:
            return row[k]
    return default


def need(row, *names):
    v = pick(row, *names)
    if v is None:
        raise CVMError("coluna %s não encontrada; o arquivo tem: %s" % (" / ".join(names), ", ".join(row.keys())))
    return v


def num(text):
    """'1234.56' ou '1.234,56' -> float; vazio -> 0.0."""
    s = str(text or "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- tickers <-> CNPJ (FCA)

def fca_path(year, offline=None, max_age=72):
    """Formulário Cadastral: tem o código de negociação de cada valor mobiliário."""
    return download("CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_%d.zip" % year, max_age=max_age, offline=offline)


def ticker_map(year, offline=None):
    """{TICKER: {"cnpj", "nome", "tipo", "classe"}} a partir do FCA (arquivo valor_mobiliario)."""
    path = fca_path(year, offline)
    out = {}
    for r in rows(path, contains="valor_mobiliario"):
        tk = str(pick(r, "Codigo_Negociacao", default="") or "").strip().upper()
        if not tk:
            continue
        fim = pick(r, "Data_Fim_Negociacao", default="")
        if fim and str(fim).strip():
            continue
        out[tk] = {"cnpj": digits(pick(r, "CNPJ_Companhia")), "nome": pick(r, "Nome_Empresarial", default=""),
                   "tipo": pick(r, "Valor_Mobiliario", default=""),
                   "classe": pick(r, "Sigla_Classe_Acao_Preferencial", default="") or ""}
    return out


def cnpj_tickers(tmap):
    """{cnpj: [tickers]} invertendo o ticker_map."""
    out = {}
    for tk, v in tmap.items():
        out.setdefault(v["cnpj"], []).append(tk)
    for v in out.values():
        v.sort()
    return out
