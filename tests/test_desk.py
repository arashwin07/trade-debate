"""Tests for every calculation the money depends on. Run: python -m unittest discover -s tests -v
No network: exchange rates and exchange rules are stubbed."""
import copy, json, os, random, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import desk, timemachine  # noqa: E402

CFG = json.load(open(os.path.join(ROOT, "config", "desk.json"), encoding="utf-8"))


def cfg_with(market, capital, currency=None):
    c = copy.deepcopy(CFG)
    c["accounts"][market]["capital"] = capital
    if currency:
        c["accounts"][market]["currency"] = currency
    return c


class Parse(unittest.TestCase):
    def test_num(self):
        self.assertEqual(desk.num("2,066-2,070"), 2068.0)
        self.assertEqual(desk.num("74,000 to 74,250"), 74125.0)
        self.assertEqual(desk.num("1.1230"), 1.123)
        self.assertEqual(desk.num("short 74,100-74,300"), 74200.0)
        self.assertEqual(desk.num(2047), 2047.0)
        self.assertIsNone(desk.num("n/a"))

    def test_plan_from_numbers_and_text(self):
        p = desk.plan_from({"plan_numbers": {"direction": "LONG", "entry": 2068, "stop": 2047, "targets": [2096, 2113]}})
        self.assertEqual(p, {"direction": "LONG", "entry": 2068.0, "stop": 2047.0, "targets": [2096.0, 2113.0]})
        p = desk.plan_from({"trade_plan": {"direction": "SHORT", "entry": "1.1225-1.1229", "stop_loss": "1.1257", "targets": ["1.1180"]}})
        self.assertEqual(p["direction"], "SHORT")
        self.assertAlmostEqual(p["entry"], 1.1227)
        self.assertIsNone(desk.plan_from({"plan": {"entry": "?", "stop": 1}}))


class PlanCheck(unittest.TestCase):
    def test_long_math(self):
        f, issues = desk.plan_check({"direction": "LONG", "entry": 100, "stop": 98, "targets": [104, 106]}, 100.5, 1.5, "1h", "us", CFG["risk"])
        self.assertEqual(f["risk_per_unit"], 2)
        self.assertEqual(f["r_multiple_gross"], [2.0, 3.0])
        self.assertEqual(f["stop_in_atr"], 1.33)
        self.assertEqual(issues, [])

    def test_wrong_side_and_tight_stop(self):
        _, issues = desk.plan_check({"direction": "LONG", "entry": 100, "stop": 101, "targets": [99]}, 100, 1.0, "1h", "us", CFG["risk"])
        ids = {i["id"] for i in issues}
        self.assertIn("stop_side", ids)
        self.assertIn("target_side", ids)
        _, issues = desk.plan_check({"direction": "SHORT", "entry": 100, "stop": 100.5, "targets": [98]}, 100, 1.0, "1h", "us", CFG["risk"])
        self.assertEqual([i["id"] for i in issues], ["stop_tight"])


class Costs(unittest.TestCase):
    def test_crypto_coindcx_c2c(self):
        # CoinDCX USDT pairs: 0.17% per side + 18% GST on the fee, + 0.02% slippage per side
        total, b = desk.round_trip_cost("crypto", "intraday", True, 2000, 2100, 1.0, CFG["costs"])
        self.assertAlmostEqual(b["exchange_fees"], 4100 * 0.0017, places=4)
        self.assertAlmostEqual(b["gst"], 4100 * 0.0017 * 0.18, places=4)
        self.assertAlmostEqual(total, 4100 * (0.0017 * 1.18 + 0.0002), places=4)

    def test_crypto_tax_on_profit_only(self):
        self.assertAlmostEqual(desk.after_tax(100.0, "crypto", CFG["costs"]), 68.8)  # 31.2% tax on profit
        self.assertEqual(desk.after_tax(-50.0, "crypto", CFG["costs"]), -50.0)       # losses are not reduced
        self.assertEqual(desk.after_tax(100.0, "nse", CFG["costs"]), 100.0)           # no flat tax modelled for stocks

    def test_us_indmoney_plan_a_cap(self):
        # 100 shares at 400: 0.25% = $100 per order, capped at $25 -> $50 brokerage + 18% GST
        _, b = desk.round_trip_cost("us", "intraday", True, 400, 404, 100, CFG["costs"])
        self.assertAlmostEqual(b["brokerage"], 50.0)
        self.assertAlmostEqual(b["gst"], 9.0)
        self.assertAlmostEqual(b["sec_fee"], 40400 * 0.0000206, places=4)
        # small order: 2 shares at 100 -> 0.25% = $0.50 per order, under the cap
        _, b2 = desk.round_trip_cost("us", "intraday", True, 100, 101, 2, CFG["costs"])
        self.assertAlmostEqual(b2["brokerage"], 0.5 + 0.505, places=6)

    def test_nse_intraday_enrich(self):
        # 100 shares at 1000 -> 1010 : buy value 100,000, sell value 101,000
        total, b = desk.round_trip_cost("nse", "intraday", True, 1000, 1010, 100, CFG["costs"])
        self.assertAlmostEqual(b["brokerage"], 201000 * 0.0002, places=4)    # 0.02% each side, no cap
        self.assertAlmostEqual(b["stt"], 101000 * 0.00025, places=4)         # 0.025% on the sell side
        self.assertAlmostEqual(b["clearing"], 201000 * 0.000025, places=4)
        self.assertAlmostEqual(b["stamp_duty"], 100000 * 0.00003, places=4)
        self.assertAlmostEqual(b["gst"], (40.2 + 201000 * 0.0000297 + 201000 * 0.000025 + 201000 * 0.000001) * 0.18, places=3)

    def test_nse_delivery_enrich(self):
        _, b = desk.round_trip_cost("nse", "swing", True, 1000, 1050, 10, CFG["costs"])
        self.assertAlmostEqual(b["brokerage"], (10000 + 10500) * 0.002, places=4)  # 0.2% delivery brokerage
        self.assertAlmostEqual(b["dp_charge"], 20.5)

    def test_nse_short_sells_first(self):
        _, b = desk.round_trip_cost("nse", "intraday", False, 1000, 990, 100, CFG["costs"])
        self.assertAlmostEqual(b["stt"], 100000 * 0.00025, places=6)  # the sell happens at the entry price

    def test_forex_enrich_currency_futures(self):
        _, b = desk.round_trip_cost("forex", "intraday", True, 83.2, 83.4, 1000, CFG["costs"], pip=0.0001)
        self.assertAlmostEqual(b["spread"], 1.0 * 0.0001 * 1000)
        self.assertAlmostEqual(b["brokerage"], (83200 + 83400) * 0.0002, places=4)  # 0.02% of contract value


class Sizing(unittest.TestCase):
    def setUp(self):
        self._fx, self._rules = desk.fx_rate, desk.crypto_rules
        desk.fx_rate = lambda a, b: 1.0 if a == b else 83.0
        desk.crypto_rules = lambda s: (0.0001, 5.0)

    def tearDown(self):
        desk.fx_rate, desk.crypto_rules = self._fx, self._rules

    def test_no_capital_never_invents_a_size(self):
        sz = desk.size({"direction": "LONG", "entry": 2068, "stop": 2047, "targets": [2096]}, "crypto", "intraday", "ETHUSDT", CFG)
        self.assertEqual(sz["status"], "NO_CAPITAL")
        self.assertIsNone(sz["qty"])

    def test_loss_never_exceeds_budget(self):
        rng = random.Random(7)
        for _ in range(300):
            mkt = rng.choice(["crypto", "us", "nse"])
            style = rng.choice(["intraday", "swing"])
            cap = rng.choice([1000, 5000, 25000, 200000, 1000000])
            e = rng.uniform(5, 5000)
            stop = e * (1 - rng.uniform(0.002, 0.08))
            tgt = e * (1 + rng.uniform(0.003, 0.2))
            c = cfg_with(mkt, cap)
            sym = {"crypto": "ETHUSDT", "us": "AAPL", "nse": "RELIANCE.NS"}[mkt]
            sz = desk.size({"direction": "LONG", "entry": e, "stop": stop, "targets": [tgt]}, mkt, style, sym, c)
            budget = cap * c["risk"]["risk_per_trade_pct"] / 100
            if sz["qty"]:
                self.assertLessEqual(sz["loss_at_stop_incl_costs"], budget + 0.01, (mkt, style, cap, e, stop))
                self.assertLessEqual(sz["position_value"], cap * c["risk"]["max_position_pct"] / 100 + 0.01)

    def test_whole_shares_for_stocks(self):
        sz = desk.size({"direction": "LONG", "entry": 351, "stop": 347, "targets": [357]}, "us", "intraday", "AAPL", cfg_with("us", 10000))
        self.assertEqual(sz["qty"], int(sz["qty"]))

    def test_currency_conversion(self):
        # INR account trading a USD stock: loss must be reported in INR
        sz = desk.size({"direction": "LONG", "entry": 100, "stop": 99, "targets": [103]}, "us", "intraday", "AAPL", cfg_with("us", 830000, "INR"))
        self.assertEqual(sz["account_currency"], "INR")
        self.assertLessEqual(sz["loss_at_stop_incl_costs"], 8300.01)


class Gate(unittest.TestCase):
    def base(self, **kw):
        plan = kw.get("plan", {"direction": "LONG", "entry": 100, "stop": 98, "targets": [104]})
        facts, issues = desk.plan_check(plan, 100, 1.5, "1h", kw.get("market", "us"), CFG["risk"])
        sz = kw.get("sz", {"status": "OK", "r_after_costs_target1": 1.9, "notes": []})
        snap = kw.get("snap", {"market_status": "OPEN", "timeframes": []})
        ev = kw.get("ev", {"status": "CLEAR", "plain": "clear"})
        tm = kw.get("tm", {"lean": "LEANS_TARGET", "verdict": "ok"})
        return desk.risk_gate(plan, facts, issues, sz, snap, ev, tm, kw.get("market", "us"), kw.get("style", "intraday"),
                              kw.get("sym", "AAPL"), kw.get("cfg", CFG), kw.get("trades", 0))

    def test_clean_plan_passes(self):
        self.assertEqual(self.base()[0], "PASS")

    def test_each_hard_rule_blocks(self):
        self.assertEqual(self.base(ev={"status": "BLOCK", "plain": "CPI"})[0], "BLOCK")
        self.assertEqual(self.base(tm={"lean": "STRONG_STOP", "verdict": "x"})[0], "BLOCK")
        self.assertEqual(self.base(sz={"status": "OK", "r_after_costs_target1": 1.2, "notes": []})[0], "BLOCK")
        self.assertEqual(self.base(snap={"market_status": "CLOSED", "timeframes": []})[0], "BLOCK")
        self.assertEqual(self.base(trades=3)[0], "BLOCK")
        self.assertEqual(self.base(plan={"direction": "LONG", "entry": 100, "stop": 101, "targets": [104]})[0], "BLOCK")

    def test_shorting_rules(self):
        short = {"direction": "SHORT", "entry": 100, "stop": 102, "targets": [96]}
        self.assertEqual(self.base(plan=short, market="crypto", sym="ETHUSDT")[0], "BLOCK")
        self.assertEqual(self.base(plan=short, market="nse", sym="RELIANCE.NS", style="intraday")[0], "PASS")
        self.assertEqual(self.base(plan=short, market="nse", sym="RELIANCE.NS", style="swing")[0], "BLOCK")

    def test_data_delay_and_price_mismatch(self):
        snap = lambda pc: {"market_status": "OPEN", "timeframes": [], "price_check": pc}
        g = lambda pc: self.base(market="nse", sym="RELIANCE.NS", snap=snap(pc))
        self.assertEqual(g({"data_delay_minutes": 1})[0], "PASS")
        res = g({"data_delay_minutes": 15})
        self.assertEqual(res[0], "PASS")  # a warning, not a block
        self.assertIn("data_delay", str(res))
        self.assertEqual(g({"data_delay_minutes": 45})[0], "BLOCK")
        tv0 = {"feed_delay_minutes": 0}; tv15 = {"feed_delay_minutes": 15}
        self.assertEqual(g({"data_delay_minutes": 0, "second_source": tv0, "second_source_diff_pct": 2.0})[0], "BLOCK")
        self.assertEqual(g({"data_delay_minutes": 0, "second_source": tv15, "second_source_diff_pct": 2.0})[0], "PASS")  # delayed source: warn only
        self.assertEqual(g({"data_delay_minutes": 0, "second_source": tv0, "second_source_diff_pct": 0.1})[0], "PASS")

    def test_india_forex_rules(self):
        self.assertEqual(self.base(market="forex", sym="AUDUSD=X")[0], "BLOCK")
        self.assertEqual(self.base(market="forex", sym="USDINR=X")[0], "PASS")


class TimeMachine(unittest.TestCase):
    def test_symmetric_random_walk_is_a_coin_flip(self):
        rng = random.Random(1)
        pool = {s: [(1, 1 + abs(x) + 0.0005, 1 - abs(x) - 0.0005, 1 + x) for x in (rng.gauss(0, 0.002) for _ in range(400))] for s in range(288)}
        pool = {s: [(1, max(1, c) + 0.0005, min(1, c) - 0.0005, c) for (_, _, _, c) in v] for s, v in pool.items()}
        mc = timemachine.simulate(pool, list(range(288)), True, 0, 96, 100.0, 99.0, [101.0], True, replays=4000, seed=3)
        self.assertLess(abs(mc["p_target"] - mc["p_stop"]), 0.05)
        self.assertEqual(timemachine.verdict(mc)[0], "COIN_FLIP")

    def test_deterministic_with_seed(self):
        pool = {0: [(1, 1.01, 0.99, 1.002), (1, 1.012, 0.995, 0.998), (1, 1.005, 0.98, 0.99)]}
        a = timemachine.simulate(pool, [0], True, 0, 10, 100, 97, [104], True, replays=500, seed=19)
        b = timemachine.simulate(pool, [0], True, 0, 10, 100, 97, [104], True, replays=500, seed=19)
        self.assertEqual(a, b)

    def test_short_side_mirrors(self):
        up = {0: [(1, 1.003, 0.9995, 1.002)] * 5}  # always drifts up
        mc = timemachine.simulate(up, [0], True, 0, 20, 100, 101, [98], False, replays=200, seed=1)
        self.assertEqual(mc["p_stop"], 1.0)  # a short in a rising market always stops out

    def test_rejects_wrong_side(self):
        with self.assertRaises(ValueError):
            timemachine.simulate({0: [(1, 1, 1, 1)]}, [0], True, 0, 5, 100, 101, [103], True)


class Outcomes(unittest.TestCase):
    P = {"direction": "LONG", "entry": 100, "stop": 98, "targets": [104]}

    def bars(self, *hl):
        return [dict(t=1000 + 300 * i, o=(h + l) / 2, h=h, l=l, c=(h + l) / 2) for i, (h, l) in enumerate(hl)]

    def test_target_first(self):
        import outcomes
        o = outcomes.evaluate(self.P, self.bars((101, 99.5), (103, 100), (104.5, 102)), 1000, 99999, 99999)
        self.assertEqual((o["status"], o["r"]), ("target", 2.0))

    def test_both_in_one_bar_counts_as_stop(self):
        import outcomes
        o = outcomes.evaluate(self.P, self.bars((100.5, 99.8), (105, 97)), 1000, 99999, 99999)
        self.assertEqual(o["status"], "stop")

    def test_never_filled_and_pending(self):
        import outcomes
        b = self.bars((106, 101), (107, 102))
        self.assertEqual(outcomes.evaluate(self.P, b, 1000, 5000, 9999)["status"], "not_filled")
        self.assertEqual(outcomes.evaluate(self.P, b, 1000, 5000, 2000)["status"], "pending")

    def test_short_expired_marked_to_market(self):
        import outcomes
        p = {"direction": "SHORT", "entry": 100, "stop": 102, "targets": [95]}
        o = outcomes.evaluate(p, self.bars((100.5, 99.5), (100, 99)), 1000, 1600, 9999)
        self.assertEqual(o["status"], "expired")
        self.assertAlmostEqual(o["r"], 0.25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
