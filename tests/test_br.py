"""Testes da edição Brasil: B3, CVM, brapi e IR. Offline, com fixtures fictícias."""

import contextlib
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest

from _load import FIX, ROOT, load

b3 = load("trader-budget", "b3")
size = load("trader-budget", "size")
check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")
alerts = load("trader-alerts", "alerts")
ir = load("trader-tax", "ir_br")
fundos = load("trader-copycat", "fundos")
vlmo = load("trader-insiders", "vlmo")
noticias = load("trader-news", "noticias")
demo = load("trader-analyst", "demonstracoes")
screen = load("trader-screener", "screen")
rebalance = load("trader-rebalance", "rebalance")

PRICES = {"PETR4": 37.42, "VALE3": 58.10, "ITUB4": 36.05, "BOVA11": 141.20, "MXRF11": 9.71}


def run(fn, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fn(argv)
    return code, out.getvalue()


class InTmp(unittest.TestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        os.chdir(self.tmp)
        os.makedirs("trader")

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.tmp)

    def write(self, path, doc):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)


class B3Rules(unittest.TestCase):
    def test_tickers(self):
        for t in ("PETR4", "VALE3", "TAEE11", "BOVA11", "AAPL34", "PETR4F", "B3SA3", "petr4.sa"):
            self.assertTrue(b3.is_b3(t), t)
        for t in ("AAPL", "GOOGL", "BRK.B", "PETRK380", "WINZ26", ""):
            self.assertFalse(b3.is_b3(t), t)
        self.assertEqual(b3.base("PETR4F"), "PETR4")
        self.assertEqual(b3.fractional("PETR4"), "PETR4F")
        self.assertEqual(b3.yahoo_symbol("PETR4F"), "PETR4.SA")
        self.assertEqual(b3.market_of("AAPL"), "us")
        self.assertEqual(b3.market_of("ITUB4"), "br")

    def test_asset_types_and_lots(self):
        self.assertEqual(b3.asset_type("PETR4"), ("acao", False))
        self.assertEqual(b3.asset_type("BOVA11"), ("etf", False))
        self.assertEqual(b3.asset_type("TAEE11"), ("unit", False))
        self.assertEqual(b3.asset_type("AAPL34"), ("bdr", False))
        self.assertEqual(b3.asset_type("MXRF11"), ("fii", True))
        self.assertEqual(b3.asset_type("MXRF11", {"MXRF11": "fii"}), ("fii", False))
        self.assertEqual(b3.round_lot("PETR4"), 100)
        self.assertEqual(b3.round_lot("TAEE11"), 100)
        self.assertEqual(b3.round_lot("BOVA11"), 1)
        self.assertEqual(b3.round_lot("XPTO3", lots={"XPTO3": 10}), 10)
        self.assertEqual(b3.split_lot(327, 100), (300, 27))
        self.assertEqual(b3.split_lot(99, 100), (0, 99))
        self.assertEqual(b3.split_lot(15, 1), (15, 0))

    def test_session_follows_us_daylight_time(self):
        s = b3.session(datetime.date(2026, 10, 26))
        self.assertEqual((s["open"].hour, s["close"].strftime("%H:%M")), (10, "16:55"))
        s = b3.session(datetime.date(2026, 11, 3))
        self.assertEqual(s["close"].strftime("%H:%M"), "17:55")
        self.assertIsNone(b3.session(datetime.date(2026, 11, 2)))   # Finados
        self.assertIsNone(b3.session(datetime.date(2026, 11, 20)))  # Consciência Negra
        self.assertIsNone(b3.session(datetime.date(2026, 12, 24)))
        self.assertIsNone(b3.session(datetime.date(2026, 2, 17)))   # Carnaval
        self.assertEqual(b3.session(datetime.date(2026, 2, 18))["open"].hour, 13)
        self.assertTrue(b3.session(datetime.date(2027, 3, 1))["provisional"])
        with self.assertRaises(KeyError):
            b3.session(datetime.date(2028, 1, 3))

    def test_clock(self):
        now = datetime.datetime(2026, 10, 30, 18, 0, tzinfo=b3.BRT)  # sexta, depois do fechamento
        c = b3.clock(now)
        self.assertFalse(c["open"])
        self.assertEqual(c["next"]["open"].date(), datetime.date(2026, 11, 3))  # pula 02/11

    def test_darf_due_date(self):
        self.assertEqual(b3.last_business_day(2026, 6), datetime.date(2026, 6, 30))
        self.assertEqual(b3.last_business_day(2026, 10), datetime.date(2026, 10, 30))
        self.assertEqual(b3.last_business_day(2026, 12), datetime.date(2026, 12, 30))

    def test_money(self):
        self.assertEqual(b3.brl(1234.5), "R$ 1.234,50")
        self.assertEqual(b3.money(20000, "br"), "R$ 20.000")
        self.assertEqual(b3.money(-35.1, "br"), "-R$ 35,10")
        self.assertEqual(b3.parse_brl("R$ 1.234,56"), 1234.56)
        self.assertEqual(b3.parse_brl("37.61"), 37.61)
        self.assertEqual(b3.parse_brl("1.234"), 1234.0)


class Budget(unittest.TestCase):
    def sized(self):
        rows = size.parse_weights({"PETR4": 30, "VALE3": 25, "ITUB4": 20, "BOVA11": 15, "MXRF11": 10})
        return size.size(rows, {"cash_buffer_pct": 10, "max_position_pct": 25}, 20000, PRICES)

    def test_b3_sizing_whole_shares_and_lots(self):
        r = self.sized()
        self.assertEqual(r["market"], "br")
        pos = {p["ticker"]: p for p in r["positions"]}
        self.assertEqual(pos["PETR4"]["shares"], 132)
        self.assertTrue(pos["PETR4"]["capped"])
        self.assertLessEqual(pos["PETR4"]["dollars"], 5000)
        self.assertEqual(pos["PETR4"]["limit_price"], 37.61)  # +0,5%
        self.assertLessEqual(r["invested"], r["investable"])
        orders = size.orders_from(r)
        legs = [(o["symbol"], o["qty"]) for o in orders]
        self.assertIn(("PETR4", "100"), legs)
        self.assertIn(("PETR4F", "32"), legs)
        self.assertIn(("BOVA11", "20"), legs)
        self.assertTrue(all("notional" not in o and o["type"] == "limit" for o in orders))

    def test_b3_needs_prices(self):
        rows = size.parse_weights({"PETR4": 50, "VALE3": 50})
        with self.assertRaises(size.SizeError):
            size.size(rows, {}, 10000, {})

    def test_mixed_markets_refused(self):
        rows = size.parse_weights({"PETR4": 50, "AAPL": 50})
        with self.assertRaises(size.SizeError):
            size.size(rows, {}, 10000, {"PETR4": 30, "AAPL": 300})

    def test_us_unchanged(self):
        rows = size.parse_weights({"AAPL": 50, "KO": 50})
        r = size.size(rows, {}, 5000)
        self.assertEqual(r["market"], "us")
        self.assertIn("notional", size.orders_from(r)[0])


class Risk(unittest.TestCase):
    CFG = {"market": "br", "budget": 20000, "cash_buffer_pct": 10, "max_position_pct": 25}

    def o(self, sym, qty, side="buy", price="37.61"):
        return {"symbol": sym, "side": side, "qty": str(qty), "type": "limit", "limit_price": price,
                "time_in_force": "day", "market": "br"}

    def test_lots(self):
        res = check.check([self.o("PETR4", 150), self.o("PETR4F", 150), self.o("BOVA11F", 3, price="141.9"),
                           self.o("ITUB4", 100, price="36.23")], self.CFG, None, PRICES, None, "2026-10-26")
        v = [r["verdict"] for r in res["results"]]
        self.assertEqual(v, ["BLOCK", "BLOCK", "BLOCK", "PASS"])
        self.assertIn("lote", res["results"][0]["reasons"][0])

    def test_notional_and_options_blocked(self):
        bad = {"symbol": "PETR4", "side": "buy", "notional": "1000", "type": "market", "time_in_force": "day",
               "market": "br"}
        opt = self.o("PETRK380", 100, price="1.10")
        res = check.check([bad, opt], self.CFG, None, PRICES, None, "2026-10-26")
        self.assertTrue(all(r["verdict"] == "BLOCK" for r in res["results"]))

    def test_day_trade_and_exemption_warnings(self):
        state = {"orders": [
            {"status": "placed", "date": "2026-10-26", "symbol": "PETR4", "side": "buy", "market": "br"},
            {"status": "placed", "date": "2026-10-05", "symbol": "VALE3", "side": "sell", "market": "br",
             "value": 19000, "order": {"symbol": "VALE3", "side": "sell", "market": "br"}}]}
        pf = {"cash": 1000, "positions": [{"ticker": "PETR4", "shares": 200}]}
        res = check.check([self.o("PETR4", 100, "sell", "37.00")], self.CFG, pf, PRICES, state, "2026-10-26")
        w = " ".join(res["results"][0]["warnings"])
        self.assertIn("day trade", w)
        self.assertIn("20.000", w)

    def test_fingerprint_matches_broker(self):
        o = self.o("PETR4", 100)
        self.assertEqual(check.fingerprint(o), ticket.fingerprint(o))


class Broker(unittest.TestCase):
    O = {"symbol": "PETR4F", "side": "buy", "qty": "32", "type": "limit", "limit_price": "37.61",
         "time_in_force": "day", "market": "br"}

    def test_portuguese_yes(self):
        ok = lambda r: ticket.parse_yes(r, self.O, ["PETR4", "PETR4F", "VALE3F"])[0]  # noqa: E731
        self.assertTrue(ok("sim"))
        self.assertTrue(ok("Sim, PETR4F 32"))
        self.assertTrue(ok("sim, limitada a 37,61"))
        for r in ("pode mandar", "ok", "sim para todas", "sim, mas espera", "sim VALE3F", "sim 50", "sim?"):
            self.assertFalse(ok(r), r)

    def test_plain_ticket(self):
        self.assertEqual(ticket.plain(self.O),
                         "COMPRA 32 PETR4F (fracionário), limitada a R$ 37,61, validade: hoje (dia)")

    def test_fill_average_cost(self):
        pf = {"cash": 10000, "positions": []}
        ticket.apply_fill_br(pf, "PETR4F", "buy", 32, 37.50, "2026-10-26", 0.36)
        ticket.apply_fill_br(pf, "PETR4", "buy", 100, 37.40, "2026-10-26", 1.12)
        p = pf["positions"][0]
        self.assertEqual((p["ticker"], p["shares"], p["cost"]), ("PETR4", 132, 4941.48))
        ticket.apply_fill_br(pf, "PETR4", "sell", 32, 40.0, "2026-10-27", 0.4)
        p = pf["positions"][0]
        self.assertEqual(p["shares"], 100)
        self.assertAlmostEqual(p["avg_price"], 4941.48 / 132, places=3)  # vender não muda o preço médio
        self.assertEqual(len(pf["trades"]), 3)
        with self.assertRaises(ticket.TicketError):
            ticket.apply_fill_br(pf, "PETR4", "buy", 1.5, 37, "2026-10-27")


class Alerts(unittest.TestCase):
    def test_brapi_v2(self):
        text = json.dumps({"results": [{"requestedSymbol": "PETR4", "symbol": "PETR4", "changed": False,
                                        "data": {"shortName": "PETROBRAS PN", "currency": "BRL",
                                                 "regularMarketPrice": 41.18, "regularMarketChange": -0.58,
                                                 "regularMarketTime": "2026-06-14T17:08:02.000Z"}}]})
        q = alerts.parse_brapi(text, "PETR4")
        self.assertEqual((q["price"], q["prev_close"], q["source"]), (41.18, 41.76, "brapi"))
        with self.assertRaises(alerts.AlertError):
            alerts.parse_brapi(json.dumps({"results": []}), "XXXX3")

    def test_brapi_without_key_only_free_tickers(self):
        old = os.environ.pop("BRAPI_TOKEN", None)
        try:
            with self.assertRaises(alerts.AlertError) as e:
                alerts._brapi_quote("WEGE3")
            self.assertIn("BRAPI_TOKEN", str(e.exception))
        finally:
            if old is not None:
                os.environ["BRAPI_TOKEN"] = old

    def test_yahoo_symbol_for_b3(self):
        self.assertIn("/PETR4.SA?", alerts.yahoo_url("PETR4"))
        self.assertIn("/AAPL?", alerts.yahoo_url("AAPL"))

    def test_b3_opening_bell(self):
        now = alerts.parse_now("2026-10-26T10:05", "br")
        st = alerts.b3_status(now)
        self.assertTrue(st["open"])
        rings, state = alerts.evaluate([{"id": "abertura-b3", "type": "opening_bell", "market": "br"}],
                                       {}, st, {}, now)
        self.assertEqual(len(rings), 1)
        self.assertIn("B3", rings[0]["message"])
        rings, _ = alerts.evaluate([{"id": "abertura-b3", "type": "opening_bell", "market": "br"}],
                                   {}, st, state, now)
        self.assertEqual(rings, [])


class Tax(unittest.TestCase):
    TRADES = [
        ("2026-03-02", "PETR4", "buy", 300, 36.00, 3.0), ("2026-03-10", "PETR4", "sell", 300, 40.00, 3.0),
        ("2026-04-06", "VALE3", "sell", 200, 58.00, 3.0),
        ("2026-05-04", "PETR4", "buy", 600, 38.00, 5.0), ("2026-05-20", "PETR4", "sell", 600, 41.00, 5.0),
        ("2026-06-01", "BOVA11", "buy", 10, 130.00, 0), ("2026-06-01", "BOVA11", "sell", 10, 131.50, 0),
        ("2026-06-15", "MXRF11", "buy", 1000, 10.00, 0), ("2026-07-15", "MXRF11", "sell", 1000, 10.30, 0),
    ]

    def months(self):
        trades = [{"date": d, "ticker": t, "side": s, "qty": q, "price": p, "fees": f}
                  for d, t, s, q, p, f in self.TRADES]
        ev, pos, warn = ir.process(trades, [{"ticker": "VALE3", "shares": 200, "cost": 13000}], {})
        months, saldo = ir.apurar(ev, {}, 2026)
        return {m["mes"]: m for m in months}, saldo, warn

    def test_exemption_loss_carry_and_darf(self):
        m, saldo, warn = self.months()
        self.assertTrue(m["2026-03"]["isento_20mil"])
        self.assertEqual(m["2026-03"]["lucro_isento"], 1194.0)
        self.assertEqual(m["2026-03"]["darf"], 0)
        self.assertEqual(m["2026-04"]["grupos"]["comum"]["prejuizo_a_compensar"], 1403.0)  # mês isento, prejuízo vale
        may = m["2026-05"]
        self.assertFalse(may["isento_20mil"])
        self.assertEqual(may["grupos"]["comum"]["compensado"], 1403.0)
        self.assertEqual(may["imposto"], 58.05)
        self.assertEqual(may["irrf_estimado"], 1.23)
        self.assertEqual((may["darf"], may["vencimento"], may["codigo"]), (56.82, "2026-06-30", "6015"))

    def test_day_trade_fii_and_ten_reais_rule(self):
        m, saldo, warn = self.months()
        jun = m["2026-06"]
        self.assertEqual(jun["grupos"]["daytrade"]["imposto"], 3.0)
        self.assertEqual((jun["darf"], jun["acumula_proximo_darf"]), (0.0, 2.85))
        jul = m["2026-07"]
        self.assertEqual(jul["grupos"]["fii"]["imposto"], 60.0)
        self.assertEqual(jul["darf"], 62.85)
        self.assertTrue(any("MXRF11" in w for w in warn))

    def test_sale_without_position_is_an_error(self):
        with self.assertRaises(ir.IRError):
            ir.process([{"date": "2026-01-05", "ticker": "PETR4", "side": "sell", "qty": 10, "price": 30,
                         "fees": 0}], [], {})

    def test_exterior(self):
        rows = [{"date": "2026-01-10", "ticker": "AAPL", "side": "buy", "qty": 10, "price": 200, "fx": 5.0, "fees": 0},
                {"date": "2026-06-10", "ticker": "AAPL", "side": "sell", "qty": 10, "price": 220, "fx": 5.5, "fees": 0}]
        r = ir.exterior(rows, 2026)
        self.assertEqual((r["resultado"], r["imposto_15"]), (2100.0, 315.0))  # 12.100 - 10.000 em reais
        r = ir.exterior(rows, 2026, prior_loss=500)
        self.assertEqual((r["base"], r["prejuizo_a_compensar"]), (1600.0, 0.0))


class Copycat(InTmp):
    F = os.path.join(FIX, "trader-copycat-br")

    def test_follows_master_and_skips_derivatives(self):
        h = fundos.holdings("202609", "22.222.222/0001-22", self.F)
        self.assertEqual(h["via"]["cnpj"], "22.222.222/0001-22")
        self.assertEqual(h["cnpj"], "11.111.111/0001-11")
        pos = {p["ticker"]: p for p in h["posicoes"]}
        self.assertEqual(sorted(pos), ["EGIE3", "PETR4", "TAEE11", "VALE3"])
        self.assertEqual(pos["PETR4"]["value"], 480000)  # inclui ações cedidas em aluguel
        self.assertEqual(h["confidencial"], 120000)  # só ações; cotas de fundos em sigilo não contam
        self.assertEqual(h["sigilo_ate"], "2027-03-31")
        fora = sorted(x["aplicacao"] for x in h["fora"])
        self.assertIn("Debêntures", fora)  # CSAN33 parece BDR, mas é debênture
        self.assertEqual(len(fora), 4)     # debênture, opção lançada, aluguel tomado, termo (caixa não conta)

    def test_copy_and_diff(self):
        code, out = run(fundos.main, ["--offline", self.F, "copiar", "22222222000122", "--mes", "202609", "--top", "3"])
        self.assertEqual(code, 0)
        with open("trader/targets.json", encoding="utf-8") as fh:
            t = json.load(fh)
        self.assertEqual(t["market"], "br")
        self.assertEqual([w["ticker"] for w in t["weights"]], ["PETR4", "VALE3", "TAEE11"])
        self.assertAlmostEqual(sum(w["weight"] for w in t["weights"]), 100.0, places=2)
        d = fundos.diff(fundos.holdings("202609", "11111111000111", self.F),
                        fundos.holdings("202608", "11111111000111", self.F))
        self.assertEqual([x[0] for x in d["zeradas"]], ["ITUB4"])
        self.assertIn("TAEE11", [x[0] for x in d["novas"]])

    def test_skips_months_in_secrecy(self):
        class A:
            cnpj, mes, offline, sem_master = "22.222.222/0001-22", None, None, False
        A.offline = self.F
        old = fundos.latest_month
        fundos.latest_month = lambda offline=None, tries=6: "202610"
        try:
            h = fundos._hold(A)
        finally:
            fundos.latest_month = old
        self.assertEqual(h["mes"], "202609")  # 202610 está todo em sigilo
        self.assertEqual(h["meses_em_sigilo"][0]["mes"], "202610")
        A.mes = "202610"
        with self.assertRaises(fundos.FundError):
            fundos._hold(A)

    def test_search(self):
        res = fundos.search("202609", "exemplo fic", self.F)
        self.assertEqual(res[0]["cnpj"], "22.222.222/0001-22")


class Insiders(InTmp):
    F = os.path.join(FIX, "trader-insiders")

    def test_novos_once_and_latest_version(self):
        args = ["--offline", self.F, "novos", "--ano", "2026", "--json"]
        code, out = run(vlmo.main, args)
        docs = {d["nome"]: d for d in json.loads(out)}
        ex = docs["COMPANHIA EXEMPLO S.A."]
        # só compra à vista conta: exercício de opção e opções de plano de remuneração ficam fora
        self.assertEqual(ex["grupos"]["Diretor (PN)"]["compra_qtd"], 20000)
        self.assertEqual(ex["grupos"]["Diretor (PN)"]["outros"], 1)
        self.assertEqual(ex["grupos"]["Conselho de Administração (ON)"]["venda_vol"], 200500)
        self.assertEqual(ex["grupos"]["Conselho Fiscal (ON)"]["compra_qtd"], 100)  # sem preço, mas conta
        self.assertNotIn("Controlador (ON)", ex["grupos"])  # venda de ações da controladora, não da companhia
        bank = docs["BANCO EXEMPLO S.A."]
        self.assertEqual(bank["versao"], "2")  # a reapresentação substitui a original
        self.assertEqual(bank["venda_vol"], 10800000 + 600000)
        code, out = run(vlmo.main, args)
        self.assertEqual((code, json.loads(out)), (1, []))  # cada documento avisa uma vez

    def test_filter_by_ticker(self):
        code, out = run(vlmo.main, ["--offline", self.F, "novos", "--ano", "2026", "--tickers", "EXMP4",
                                    "--dry-run"])
        self.assertIn("COMPANHIA EXEMPLO", out)
        self.assertNotIn("BANCO EXEMPLO", out)
        self.assertIn("valor não informado", out)

    def test_transfer_note(self):
        code, out = run(vlmo.main, ["--offline", self.F, "novos", "--ano", "2026", "--tickers", "BEXE3",
                                    "--dry-run"])
        self.assertIn("transferência entre veículos", out)


class News(InTmp):
    F = os.path.join(FIX, "trader-news-br")

    def test_ipe_and_google(self):
        code, out = run(noticias.main, ["--offline", self.F, "--tickers", "EXMP4", "--hoje", "2026-10-26",
                                        "--dias", "20", "--json"])
        items = json.loads(out)["itens"]
        labels = [i["label"] for i in items]
        self.assertIn("FATO RELEVANTE", labels)
        self.assertIn("aviso aos acionistas", labels)
        self.assertIn("manchete", labels)
        self.assertIn("proventos", labels)   # categoria "Relatório Proventos"
        self.assertIn("insiders", labels)    # nome real tem sufixo "(art. 11 da Instr. CVM nº 358)"
        self.assertNotIn("Estatuto consolidado", [i["title"] for i in items])  # categoria irrelevante
        self.assertTrue(all("BANCO" not in i.get("company", "") for i in items))
        jcp = [i for i in items if i["label"] == "aviso aos acionistas"][0]
        self.assertIn("proventos", jcp["tags"])
        code, out = run(noticias.main, ["--offline", self.F, "--tickers", "EXMP4", "--hoje", "2026-10-26",
                                        "--dias", "20", "--json"])
        self.assertEqual(json.loads(out)["itens"], [])


class Analyst(unittest.TestCase):
    F = os.path.join(FIX, "trader-analyst-br")

    def test_quarters_q4_derived_and_metrics(self):
        c = demo.company("EXMP4", 2026, self.F)
        s = {x["fim"]: x for x in c["series"]}
        self.assertEqual(s["2026-09-30"]["receita"], 1380000000.0)  # escala MIL
        self.assertTrue(s["2025-12-31"]["derivado"])
        self.assertEqual(s["2025-12-31"]["receita"], 1300000000.0)  # 4,6 bi - 3,3 bi
        self.assertAlmostEqual(s["2025-12-31"]["lpa_principal"], 0.36, places=4)
        self.assertAlmostEqual(s["2026-09-30"]["cresc_receita"], 15.0, places=4)
        self.assertTrue(s["2026-09-30"]["um_off"])
        m = demo.to_metrics(c)
        self.assertEqual((m["eps_ttm"], m["market"]), (1.84, "br"))

    def test_unknown_ticker(self):
        with self.assertRaises(demo.AnalystError):
            demo.company("BOVA11", 2026, self.F)


class Screener(unittest.TestCase):
    def test_brazilian_numbers(self):
        self.assertEqual(screen.to_number("1.234,56"), 1234.56)
        self.assertEqual(screen.to_number("R$ 12,5"), 12.5)
        self.assertEqual(screen.to_number("21,7%"), 21.7)
        self.assertEqual(screen.to_number("$1,250"), 1250.0)
        self.assertEqual(screen.to_number("1,250"), 1250.0)   # sem R$ e com 3 casas: milhar americano


class Rebalance(InTmp):
    def test_b3_orders(self):
        self.write("trader/targets.json", {"market": "br", "weights": [
            {"ticker": "PETR4", "weight": 40}, {"ticker": "VALE3", "weight": 40}, {"ticker": "BOVA11", "weight": 20}]})
        self.write("trader/portfolio.json", {"cash": 500, "positions": [
            {"ticker": "PETR4", "shares": 500}, {"ticker": "VALE3", "shares": 80}, {"ticker": "BOVA11", "shares": 20}]})
        self.write("trader/prices.json", {"prices": PRICES})
        self.write("trader/config.json", {"market": "br", "max_order_brl": 6000})
        code, out = run(rebalance.main, ["--band", "3", "--write"])
        self.assertEqual(code, 0)
        with open("trader/orders.json", encoding="utf-8") as fh:
            orders = json.load(fh)["orders"]
        self.assertEqual(orders[0]["side"], "sell")
        for o in orders:
            self.assertEqual((o["market"], o["type"]), ("br", "limit"))
            q = int(o["qty"])
            if o["lot_market"] == "padrao" and o["asset_type"] == "acao":
                self.assertEqual(q % 100, 0)
            if o["lot_market"] == "fracionario":
                self.assertTrue(o["symbol"].endswith("F") and 1 <= q <= 99)
        res = check.check(orders, {"market": "br", "max_order_brl": 6000},
                          {"cash": 500, "positions": [{"ticker": "PETR4", "shares": 500},
                                                      {"ticker": "VALE3", "shares": 80},
                                                      {"ticker": "BOVA11", "shares": 20}]},
                          PRICES, None, "2026-10-26")
        self.assertEqual(res["block"], 0)


if __name__ == "__main__":
    unittest.main()
