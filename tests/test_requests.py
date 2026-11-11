import json, os, shutil, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import trade_requests as tr  # noqa: E402
import watch  # noqa: E402


def ts(hours_ago=0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Parse(unittest.TestCase):
    def test_minimal_request_gets_defaults(self):
        r, err = tr.parse({"symbol": "reliance", "market": "nse"})
        self.assertIsNone(err)
        self.assertEqual((r["direction"], r["style"], r["data_symbol"], r["user_plan"]), ("LONG", "intraday", "RELIANCE.NS", None))

    def test_buy_sell_words_and_auto_market(self):
        r, _ = tr.parse({"symbol": "BTC", "direction": "sell"})
        self.assertEqual((r["direction"], r["market"], r["display"]), ("SHORT", "crypto", "BTC/USDT"))

    def test_prices_all_or_none_and_right_side(self):
        self.assertIsNotNone(tr.parse({"symbol": "AAPL", "entry": 200})[1])
        self.assertIsNotNone(tr.parse({"symbol": "AAPL", "entry": 200, "stop": 205, "target": 210})[1])  # long stop above entry
        self.assertIsNotNone(tr.parse({"symbol": "AAPL", "direction": "SHORT", "entry": 200, "stop": 195, "target": 190})[1])
        r, err = tr.parse({"symbol": "AAPL", "entry": "200", "stop": "196.5", "target": "1,210"})
        self.assertIsNone(err)
        self.assertEqual(r["user_plan"], {"direction": "LONG", "entry": 200.0, "stop": 196.5, "targets": [1210.0]})

    def test_rejects_bad_values(self):
        for bad in ({}, {"symbol": "A B"}, {"symbol": "AAPL", "market": "mcx"}, {"symbol": "AAPL", "style": "weekly"},
                    {"symbol": "AAPL", "entry": -1, "stop": 1, "target": 2}, {"symbol": "AAPL", "direction": "up"}, []):
            self.assertIsNotNone(tr.parse(bad)[1], bad)

    def test_note_is_capped(self):
        r, _ = tr.parse({"symbol": "AAPL", "note": "x" * 900})
        self.assertEqual(len(r["user_note"]), 500)


class Queue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (tr.REQ, tr.DONE)
        tr.REQ, tr.DONE = os.path.join(self.tmp, "requests"), os.path.join(self.tmp, "requests", "done")
        os.makedirs(tr.REQ)

    def tearDown(self):
        tr.REQ, tr.DONE = self.saved
        shutil.rmtree(self.tmp)

    def put(self, name, obj):
        with open(os.path.join(tr.REQ, name), "w", encoding="utf-8") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def test_timing_rules(self):
        self.put("a.json", {"symbol": "NVDA", "market": "us", "style": "swing", "asked_utc": ts()})
        self.put("b.json", {"symbol": "TCS", "market": "nse", "style": "intraday", "asked_utc": ts(2)})
        self.put("c.json", {"symbol": "INFY", "market": "nse", "style": "intraday", "asked_utc": ts(60)})
        self.put("d.json", {"symbol": "BTC", "market": "crypto", "asked_utc": ts()})
        res = tr.list_requests(open_fn=lambda m: m == "crypto")
        self.assertEqual(sorted(r["symbol"] for r in res["ready"]), ["BTC", "NVDA"])  # swing any time, crypto open
        self.assertEqual([r["symbol"] for r in res["waiting"]], ["TCS"])               # intraday, market closed
        self.assertEqual([c["status"] for c in res["closed_now"]], ["expired"])        # waited over 48 h
        self.assertTrue(os.path.exists(os.path.join(tr.DONE, "c.json")))

    def test_invalid_files_are_moved_with_reason(self):
        self.put("bad.json", "{not json")
        self.put("bad2.json", {"symbol": "AAPL", "entry": 1})
        res = tr.list_requests(open_fn=lambda m: True)
        self.assertEqual(res["ready"], [])
        self.assertEqual(len(res["closed_now"]), 2)
        with open(os.path.join(tr.DONE, "bad2.json"), encoding="utf-8") as f:
            self.assertIn("all three", json.load(f)["reason"])

    def test_done_moves_and_records_id(self):
        self.put("x.json", {"symbol": "AAPL"})
        tr.move_done(os.path.join(tr.REQ, "x.json"), {"status": "debated", "debate_id": "ID1"})
        self.assertFalse(os.path.exists(os.path.join(tr.REQ, "x.json")))
        with open(os.path.join(tr.DONE, "x.json"), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual((d["symbol"], d["status"], d["debate_id"]), ("AAPL", "debated", "ID1"))


class WatchlistDedupe(unittest.TestCase):
    def test_recently_debated_matches_any_spelling(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "D1"))
            with open(os.path.join(tmp, "D1", "meta.json"), "w") as f:
                json.dump({"id": "D1", "symbol": "BTC/USDT", "market": "crypto", "direction": "LONG", "created_utc": ts(3)}, f)
            self.assertEqual(watch.recently_debated("BTC", "crypto", "LONG", debates_dir=tmp), "D1")
            self.assertIsNone(watch.recently_debated("BTC", "crypto", "SHORT", debates_dir=tmp))
            self.assertIsNone(watch.recently_debated("ETH", "crypto", "LONG", debates_dir=tmp))
            self.assertIsNone(watch.recently_debated("BTC", "crypto", "LONG", hours=2, debates_dir=tmp))
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
