"""Phase 1 tests: guardrails (validate), claim checker, optimizer realism, volatility, calibration, levels helpers.
No network. Run: python -m unittest discover -s tests -v"""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import validate, claims, optimizer, regime, calibration, levels, desk  # noqa: E402


def stmt(side="bull", rnd=1, **kw):
    d = {"agent": side, "round": rnd, "stance": "TAKE" if side == "bull" else "SKIP", "headline": "A clear one-line headline",
         "messages": [{"text": "First message here", "evidence": [0]}, {"text": "Second message", "evidence": []}],
         "evidence": [{"claim": "1h RSI 27.6", "value": "27.6", "source": "snapshot", "time": "2026-11-10T12:00Z"}]}
    if side == "bull":
        d["plan_numbers"] = {"direction": "LONG", "entry": 100.0, "stop": 98.0, "targets": [103.0, 105.0]}
    d.update(kw)
    return d


class Guardrails(unittest.TestCase):
    def test_good_statement_passes(self):
        self.assertEqual(validate.validate_statement(stmt(), "bull", 1, 100.2, "intraday"), [])
        self.assertEqual(validate.validate_statement(stmt("bear"), "bear", 1, 100.2, "intraday"), [])

    def test_side_switch_is_caught(self):
        errs = validate.validate_statement(stmt(stance="SKIP"), "bull", 1, 100, "intraday")
        self.assertTrue(any("stance" in e for e in errs))

    def test_typo_entry_is_caught(self):
        s = stmt(plan_numbers={"direction": "LONG", "entry": 1000.0, "stop": 980.0, "targets": [1030.0]})
        self.assertTrue(any("from the live price" in e for e in validate.validate_statement(s, "bull", 1, 100, "intraday")))

    def test_wrong_side_and_bad_index(self):
        s = stmt(plan_numbers={"direction": "LONG", "entry": 100.0, "stop": 101.0, "targets": [99.0]},
                 messages=[{"text": "hello there", "evidence": [5]}, {"text": "second one", "evidence": []}])
        errs = validate.validate_statement(s, "bull", 1, 100, "intraday")
        self.assertTrue(any("wrong side" in e for e in errs))
        self.assertTrue(any("does not exist" in e for e in errs))

    def test_verdict_total_must_add_up(self):
        v = {"decision": "SKIP", "confidence": 80, "winner": "bear", "headline_plain": "x" * 20, "explain_plain": "x" * 20,
             "plan_plain": "x" * 20, "retake_plain": "x" * 20, "reasoning": "x" * 20,
             "scorecard": {"bull": {"evidence_quality": 5, "data_accuracy": 5, "rebuttal_strength": 5, "plan_reasoning": 5, "total": 21},
                           "bear": {"evidence_quality": 6, "data_accuracy": 6, "rebuttal_strength": 6, "plan_reasoning": 6, "total": 24}},
             "trade_plan_numbers": {"direction": "LONG", "entry": 100.0, "stop": 98.0, "targets": [103.0]}}
        errs = validate.validate_verdict(v, 100, "intraday")
        self.assertEqual(len(errs), 1)
        self.assertIn("not the sum", errs[0])


class ClaimChecker(unittest.TestCase):
    SNAP = {"timeframes": [{"timeframe": "5m", "atr14": 1.23, "rsi14": 25.1}, {"timeframe": "1h", "atr14": 3.86, "rsi14": 27.6}], "price": 170.64}

    def run_check(self, ev, fresh=True):
        return claims.check_statement({"evidence": ev}, claims.leaves([self.SNAP], []), claims.tf_values([self.SNAP]), fresh)

    def test_wrong_timeframe(self):
        r = self.run_check([{"claim": "1h ATR is 1.23", "value": "1.23", "source": "snapshot 1h"}])
        self.assertEqual(r["wrong"], 1)
        self.assertEqual(r["issues"][0]["problem"], "wrong_timeframe")

    def test_correct_values_pass(self):
        r = self.run_check([{"claim": "1h RSI 27.6", "value": "27.6", "source": "snapshot"},
                            {"claim": "price", "value": "$170.64", "source": "snapshot"}])
        self.assertEqual((r["wrong"], r["unconfirmed"]), (0, 0))

    def test_ratios_and_web_sources_are_not_flagged(self):
        r = self.run_check([{"claim": "stop is 0.36x ATR", "value": "0.36x", "source": "desk"},
                            {"claim": "chip index up", "value": "6.8%", "source": "CNBC article"}])
        self.assertEqual(r["issues"], [])

    def test_mismatch_without_fresh_pull_is_only_unconfirmed(self):
        r = self.run_check([{"claim": "5m RSI 27.3", "value": "27.3", "source": "snapshot"}], fresh=False)
        self.assertEqual((r["wrong"], r["unconfirmed"]), (0, 1))


class Optimizer(unittest.TestCase):
    LV = [{"price": p, "label": f"L{p}"} for p in (94, 96, 97.5, 102, 104, 106, 120, 150)]

    def test_candidates_are_realistic(self):
        cands = optimizer.candidates("LONG", 100.0, 2.0, self.LV, desk.config()["risk"])
        self.assertTrue(cands)
        for c in cands:
            self.assertLess(c["stop"], c["entry"])
            self.assertGreater(c["target"], c["entry"])
            self.assertGreaterEqual(c["entry"] - c["stop"], 2.0 * desk.config()["risk"]["min_stop_atr"] - 1e-9)
            self.assertLessEqual(c["target"] - c["entry"], optimizer.MAX_TARGET_ATR * 2.0 + 1e-9)  # never the 150 level

    def test_short_mirror(self):
        for c in optimizer.candidates("SHORT", 100.0, 2.0, self.LV, desk.config()["risk"]):
            self.assertGreater(c["stop"], c["entry"])
            self.assertLess(c["target"], c["entry"])


class Volatility(unittest.TestCase):
    def test_atr_series_constant_range(self):
        cs = [dict(o=100, h=101, l=99, c=100) for _ in range(40)]
        s = regime.atr_series(cs)
        self.assertAlmostEqual(s[-1], 0.02, places=6)  # range 2 on price 100


class Calibration(unittest.TestCase):
    def test_right_rules(self):
        self.assertTrue(calibration.right("SKIP", {"status": "stop", "r": -1}))
        self.assertFalse(calibration.right("SKIP", {"status": "target", "r": 1.3}))
        self.assertTrue(calibration.right("TAKE", {"status": "target", "r": 2}))
        self.assertIsNone(calibration.right("TAKE", {"status": "not_filled"}))
        self.assertIsNone(calibration.right("SKIP", {"status": "pending"}))


class Levels(unittest.TestCase):
    def test_swings_and_cluster(self):
        cs = [dict(h=h, l=h - 1) for h in (1, 2, 3, 9, 3, 2, 1, 2, 3, 9.2, 3, 2, 1)]
        hi, lo = levels.swings(cs, k=2)
        self.assertEqual(sorted(hi), [9, 9.2])
        cl = levels.cluster(hi, 0.5)
        self.assertEqual(len(cl), 1)
        self.assertEqual(cl[0]["touches"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
