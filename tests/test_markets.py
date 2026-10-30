"""Stocks and coins (sources/markets.py, render/markets.py): every market, asked carefully.

* Yahoo Finance's and CoinGecko's answers are read from saved samples (no network in tests).
* Every symbol a page shows goes in one request; a coin's prices in every currency in one more.
* Nobody is asked while every market a page shows is closed and its close is in.
* After a failure, longer and longer waits, Retry-After honoured; the last prices stay.
* A closed market says so: its change is the last session's, never shown as live.
* Prices are written as the screen's language writes them, in each holding's own currency.
* Every word fits its row at every size offered, in every language.
"""
import asyncio
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import support  # noqa: F401
from fake_http import FakeSession, sample

import health
import pacing
import widgets
from render import arrange, markets as draw, theme as T, words
from sources import markets as M


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def run(coro):
    return asyncio.run(coro)


ABOUT = {s: M.read_chart(b) for s, b in sample("yahoo_chart.json").items()}


class TestReading(unittest.TestCase):
    def test_prices_from_yahoo(self):
        got = M.read_spark(sample("yahoo_spark.json"))
        self.assertEqual(set(got), {"TLV.RO", "^GDAXI", "EURRON=X", "7203.T"})
        bt = got["TLV.RO"]
        self.assertEqual((bt["price"], bt["previous"], round(bt["change_pct"], 3)), (36.02, 35.88, 0.391))
        self.assertEqual(len(bt["trend"]), 16)
        self.assertEqual(datetime.fromtimestamp(bt["traded_at"], timezone.utc), at("2026-10-30T12:05:08+00:00"))

    def test_what_a_symbol_is(self):
        bt = ABOUT["TLV.RO"]
        self.assertEqual((bt["currency"], bt["tz"], bt["opens"], bt["closes"], bt["kind"]),
                         ("RON", "Europe/Bucharest", "10:00", "18:00", "EQUITY"))
        self.assertEqual(ABOUT["7203.T"]["currency"], "JPY")
        self.assertEqual(ABOUT["^GDAXI"]["kind"], "INDEX")

    def test_a_currency_pair_is_priced_in_its_second_currency(self):
        # Yahoo gives a pair no currency; a euro in lei shows in lei.
        self.assertEqual(ABOUT["EURRON=X"]["currency"], "RON")
        self.assertEqual(ABOUT["EURRON=X"]["decimals"], 4)

    def test_coins(self):
        prices = M.read_coin_prices(sample("coingecko_price.json"))
        self.assertEqual(prices["bitcoin"]["prices"]["RON"]["price"], 369354)
        self.assertLess(prices["bitcoin"]["prices"]["EUR"]["change_pct"], 0)
        lines = M.read_coin_markets(sample("coingecko_markets.json"))
        self.assertEqual(lines["bitcoin"]["name"], "Bitcoin")
        self.assertGreater(len(lines["bitcoin"]["trend"]), 10)

    def test_another_form_is_said_not_guessed(self):
        for bad in ([], "x", None):
            with self.assertRaises(ValueError):
                M.read_spark(bad)
        with self.assertRaises(ValueError):
            M.read_chart({"chart": {"result": None}})
        with self.assertRaises(ValueError):
            M.read_coin_markets({"error": "x"})

    def test_search_finds_both_kinds_and_no_options(self):
        found = M.read_search(sample("yahoo_search.json"), sample("coingecko_search.json"))
        self.assertIn({"kind": "quote", "symbol": "^GDAXI", "name": "DAX P", "where": "XETRA · Index"}, found)
        self.assertEqual(next(f for f in found if f["kind"] == "coin")["symbol"], "bitcoin")
        self.assertEqual(M.read_search({"quotes": [{"symbol": "AAPL250117C00100000", "quoteType": "OPTION"}]}, None), [])


class TestHoldings(unittest.TestCase):
    def test_cleaned_kept_in_order_each_once_at_most_eight(self):
        el = {"holdings": [{"symbol": " tlv.ro "}, {"symbol": "TLV.RO"}, {"symbol": "<script>"}, {"coin": "Bitcoin"},
                           {"coin": "bitcoin", "currency": "eur"}, *({"symbol": f"S{k}.DE"} for k in range(10))]}
        got = M.holdings_of(el)
        self.assertEqual([(h.kind, h.symbol, h.currency) for h in got[:3]],
                         [("quote", "TLV.RO", ""), ("coin", "bitcoin", ""), ("coin", "bitcoin", "EUR")])
        self.assertEqual(len(got), M.MOST)


class TestOpenOrClosed(unittest.TestCase):
    bt = ABOUT["TLV.RO"]

    def test_open_while_trading_today(self):
        st = M.state(self.bt, at("2026-10-30T12:05:00+00:00").timestamp(), at("2026-10-30T12:10:00+00:00"))
        self.assertTrue(st["open"])

    def test_after_the_close_its_the_close(self):
        st = M.state(self.bt, at("2026-10-30T15:59:00+00:00").timestamp(), at("2026-10-30T17:00:00+00:00"))
        self.assertEqual(st, {"open": False, "since": "2026-10-30"})

    def test_the_weekend_says_fridays_close(self):
        st = M.state(self.bt, at("2026-10-30T15:59:00+00:00").timestamp(), at("2026-11-01T10:00:00+00:00"))
        self.assertEqual(st, {"open": False, "since": "2026-10-30"})

    def test_a_holiday_is_closed_not_live(self):
        # Within its hours on a weekday, but nothing traded today: yesterday's change isn't today's.
        st = M.state(self.bt, at("2026-11-02T15:59:00+00:00").timestamp(), at("2026-11-03T11:00:00+00:00"))
        self.assertFalse(st["open"])

    def test_next_open(self):
        self.assertEqual(M.next_open(self.bt, at("2026-10-31T09:00:00+00:00")).astimezone(ZoneInfo("Europe/Bucharest")).isoformat(),
                         "2026-11-02T10:00:00+02:00")

    def test_the_row_says_its_the_close(self):
        now = at("2026-11-01T10:00:00+00:00").astimezone(ZoneInfo("Europe/Bucharest"))
        row = {"kind": "quote", "symbol": "TLV.RO", "open": False, "since": "2026-10-30"}
        with words.speaking("en"):
            self.assertEqual(draw._sub(row, now), "TLV.RO · At close Fri")
        with words.speaking("ro"):
            self.assertEqual(draw._sub(row, now), "TLV.RO · Închidere Vin.")


class Base(unittest.TestCase):
    def setUp(self):
        health.reset()
        M._about.clear()
        M._last_quotes.clear()
        M.PACE_YAHOO.ok()
        M.PACE_GECKO.ok()
        self.clock = 1_000_000.0
        pacing.clock = lambda: self.clock

    def tearDown(self):
        import time
        pacing.clock = time.time


class TestAskingCarefully(Base):
    def yahoo(self, method, url, data):
        if "/spark" in url:
            return 200, sample("yahoo_spark.json"), {}
        return 200, sample("yahoo_chart.json")["TLV.RO"], {}

    def test_every_symbol_in_one_request(self):
        s = FakeSession(self.yahoo)
        run(M.fetch_quotes.direct(s, ("TLV.RO", "^GDAXI", "EURRON=X", "7203.T")))
        self.assertEqual(len(s.asked), 1)
        self.assertIn("symbols=TLV.RO,%5EGDAXI,EURRON%3DX,7203.T", s.urls()[0])

    def test_twenty_at_a_time(self):
        s = FakeSession(self.yahoo)
        run(M.fetch_quotes.direct(s, tuple(f"S{k}.DE" for k in range(25))))
        self.assertEqual(len(s.asked), 2)

    def test_it_names_itself(self):
        s = FakeSession(self.yahoo)
        run(M.fetch_quotes.direct(s, ("TLV.RO",)))
        self.assertTrue(s.asked[0][3]["User-Agent"].startswith("epaper-panel/"))

    def test_nobody_is_asked_while_every_market_is_closed(self):
        s = FakeSession(self.yahoo)
        symbols = ("7203.T",)                       # Tokyo closed at 06:30 UTC
        M._about["7203.T"] = {"at": 1e12, "about": ABOUT["7203.T"]}
        first = run(M.fetch_quotes.direct(s, symbols))
        again = run(M.fetch_quotes.direct(s, symbols))
        self.assertEqual(len(s.asked), 1, "its close is in: nothing to ask until Tokyo opens")
        self.assertIs(again, first)

    def test_an_open_market_is_asked(self):
        s = FakeSession(self.yahoo)
        M._last_quotes[("TLV.RO",)] = {"at": datetime.now(timezone.utc).timestamp(),
                                       "quotes": {"TLV.RO": {"traded_at": datetime.now(timezone.utc).timestamp()}}}
        M._about["TLV.RO"] = {"at": 1e12, "about": {**ABOUT["TLV.RO"], "opens": "00:00", "closes": "23:59", "tz": "UTC"}}
        resting = M._resting(("TLV.RO",), datetime.now(timezone.utc))
        self.assertEqual(resting, datetime.now(timezone.utc).weekday() >= 5, "on a weekday it's open all day here")

    def test_what_a_symbol_is_once_a_day(self):
        s = FakeSession(self.yahoo)
        run(M.fetch_about.direct(s, "TLV.RO"))
        run(M.fetch_about.direct(s, "TLV.RO"))
        self.assertEqual(len(s.asked), 1)

    def test_a_symbol_yahoo_doesnt_know(self):
        s = FakeSession(lambda m, u, d: (404, sample("yahoo_chart_missing.json"), {}))
        self.assertEqual(run(M.fetch_about.direct(s, "NOPE.XX")), {"missing": True})
        self.assertEqual(M.PACE_YAHOO.failures, 0, "not knowing a symbol is an answer, not a failure")

    def test_coins_in_two_requests_whatever_the_currencies(self):
        s = FakeSession(lambda m, u, d: (200, sample("coingecko_markets.json") if "/coins/markets" in u else sample("coingecko_price.json"), {}))
        got = run(M.fetch_coins.direct(s, ("bitcoin", "ethereum"), ("EUR", "RON")))
        self.assertEqual(len(s.asked), 2)
        self.assertIn("vs_currencies=eur,ron", s.urls()[1])
        self.assertEqual(got["coins"]["bitcoin"]["prices"]["RON"]["price"], 369354)

    def test_the_live_readers_ask_every_five_minutes_at_most(self):
        self.assertEqual((M.fetch_quotes.interval, M.fetch_coins.interval), (300, 300))


class TestBackingOff(Base):
    def test_slow_down_waits_as_long_as_asked(self):
        s = FakeSession(lambda m, u, d: (429, "Too Many Requests", {"Retry-After": "1200"}))
        with self.assertRaises(LookupError):
            run(M.fetch_quotes.direct(s, ("TLV.RO",)))
        self.assertEqual(M.PACE_YAHOO.waiting(), 1200)
        with self.assertRaises(pacing.Waiting):
            run(M.fetch_quotes.direct(s, ("TLV.RO",)))
        self.assertEqual(len(s.asked), 1, "nothing is sent while it waits")
        self.assertTrue(any(e["name"] == "Yahoo Finance" and e["error"] for e in health.status()), "and the failure is said")

    def test_each_failure_waits_longer_up_to_a_limit(self):
        pace = pacing.Pace("Test", first=300, most=3600)
        self.assertEqual([pace.failed() for _ in range(6)], [300, 600, 1200, 2400, 3600, 3600])
        pace.ok()
        self.assertEqual(pace.waiting(), 0)

    def test_an_unreadable_answer_is_a_failure_too(self):
        s = FakeSession(lambda m, u, d: (200, "<html>maintenance</html>", {}))
        with self.assertRaises(LookupError):
            run(M.fetch_quotes.direct(s, ("TLV.RO",)))
        self.assertGreater(M.PACE_YAHOO.waiting(), 0)

    def test_try_again_ends_the_wait(self):
        import services
        M.PACE_YAHOO.failed(3600)
        services.get("yahoo_finance").forget()
        self.assertEqual(M.PACE_YAHOO.waiting(), 0)

    def test_the_last_prices_stay_with_their_age(self):
        now = datetime(2026, 10, 30, 14, 0, tzinfo=ZoneInfo("Europe/Bucharest"))
        data = {"rows": [{"kind": "quote", "symbol": "TLV.RO", "label": "BT", "price": 36.02, "currency": "RON",
                          "change_pct": 0.39, "decimals": 2, "trend": [1, 2], "open": True}],
                "at": now.timestamp() - 40 * 60, "tz": "Europe/Bucharest"}
        with words.speaking("en"):
            self.assertEqual(draw.plan(data, (0, 0, 744, 208), now=now).note, "Prices from 13:20")
            data["at"] = now.timestamp() - 60
            self.assertEqual(draw.plan(data, (0, 0, 744, 208), now=now).note, "")


class TestWhatThePageSays(unittest.TestCase):
    def test_money_in_each_language(self):
        plain = lambda t: t.replace("\u00a0", " ").replace("\u202f", " ")      # the kinds of space, as one
        cases = {"en": ("36.02 lei", "€25,842.65", "+0.39%"), "ro": ("36,02 lei", "25.842,65 €", "+0,39%"),
                 "de": ("36,02 lei", "25.842,65 €", "+0,39 %"), "fr": ("36,02 lei", "25 842,65 €", "+0,39 %"),
                 "es": ("36,02 lei", "25.842,65 €", "+0,39 %")}
        for lang, (lei, eur, pct) in cases.items():
            with self.subTest(lang=lang), words.speaking(lang):
                self.assertEqual(plain(words.money(36.02, "RON")), lei)
                self.assertEqual(plain(words.money(25842.65, "EUR")), eur)
                self.assertEqual(plain(words.percent(0.391)), pct)
        with words.speaking("en"):
            self.assertEqual(words.percent(-0.757), "−0.76%")
            self.assertEqual(words.money(1234.5, "GBp", 1), "1,234.5 p")
        with words.speaking("de"):
            self.assertEqual(plain(words.money(-3.5, "USD")), "−3,50 $", "a real minus sign")

    def test_messages(self):
        with words.speaking("en"):
            self.assertEqual(draw.plan({"rows": []}, (0, 0, 744, 208)).message, "Add what you hold")
            failing = {"rows": [{"symbol": "X", "price": None}], "failing": True}
            self.assertIn("aren’t coming in", draw.plan(failing, (0, 0, 744, 208)).message)
        self.assertIsNone(draw.plan(None, (0, 0, 744, 208)), "nothing fetched yet stays blank")

    def test_a_symbol_not_found_says_so(self):
        row = {"kind": "quote", "symbol": "NOPE.XX", "missing": True, "price": None}
        with words.speaking("de"):
            self.assertEqual(draw._sub(row, datetime.now(timezone.utc)), "Nicht gefunden")

    def test_rows_keep_their_order_and_currency(self):
        hs = M.holdings_of({"holdings": [{"coin": "bitcoin"}, {"symbol": "TLV.RO"}, {"symbol": "NOPE.XX"}]})
        quotes = {"at": 1.0, "quotes": M.read_spark(sample("yahoo_spark.json"))}
        coins = {"at": 1.0, "coins": {"bitcoin": {"name": "Bitcoin", "trend": [1, 2],
                                                  **M.read_coin_prices(sample("coingecko_price.json"))["bitcoin"]}}}
        rows = M.rows(hs, quotes, {"TLV.RO": ABOUT["TLV.RO"], "NOPE.XX": {"missing": True}}, coins, "RON",
                      at("2026-10-30T12:10:00+00:00"))
        self.assertEqual([r["symbol"] for r in rows], ["bitcoin", "TLV.RO", "NOPE.XX"])
        self.assertEqual((rows[0]["currency"], rows[0]["price"]), ("RON", 369354))
        self.assertEqual((rows[1]["currency"], rows[1]["open"]), ("RON", True))
        self.assertTrue(rows[2]["missing"])


class TestEveryWordFits(unittest.TestCase):
    """Rows at every size offered, the preset's box placed there and the whole canvas, in every language."""

    def boxes(self):
        base = arrange.canvas_key(792, 272)
        for key, d in T.DISPLAYS.items():
            if d.get("offered") is False:
                continue
            placed = arrange.auto_box({"x": 24, "y": 14, "w": 744, "h": 208}, base, arrange.canvas_key(d["w"], d["h"]))
            yield key, (placed["x"], placed["y"], placed["w"], placed["h"])
            yield key + " filled", (20, 14, d["w"] - 40, d["h"] - T.band_height(d["h"]) - 24)

    def test_every_size_every_language(self):
        now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        for n in (1, 4, 8):
            data = widgets.example({"type": "markets", "holdings": [{"symbol": f"S{k}"} for k in range(n)]}, now)
            data["rows"][0].update(open=False, since="2026-10-30")
            data["at"] = now.timestamp() - 3600
            for key, box in self.boxes():
                for lang in words.LANGUAGES:
                    with self.subTest(n=n, display=key, lang=lang), words.speaking(lang):
                        pl = draw.plan(data, box, now=now)
                        self.assertTrue(pl.cells)
                        for c in pl.cells:
                            lf, sf = T.font(c.label_px, bold=True), T.font(c.sub_px, bold=False)
                            pf = T.font(round(c.label_px * 1.12), bold=True)
                            self.assertLessEqual(T.text_width(c.label, lf), c.label_w)
                            self.assertLessEqual(T.text_width(c.sub, sf), c.label_w)
                            self.assertLessEqual(T.text_width(c.price, pf), c.right_w)
                            self.assertGreaterEqual(c.label_px, draw.MIN_LABEL)
                            cx, cy, cw, rh = c.box
                            self.assertLessEqual(cx + cw, box[0] + box[2])
                            self.assertLessEqual(cy + rh, box[1] + box[3])
                        shown = len(pl.cells)
                        if shown < n:
                            self.assertIn(words.say("markets.more", n - shown).split()[0], pl.note)

    def test_it_draws(self):
        from PIL import Image, ImageDraw
        img = Image.new("L", (792, 272), T.WHITE)
        draw.draw(img, ImageDraw.Draw(img), (24, 14, 744, 208), {}, widgets.example({"type": "markets"}, datetime.now()))
        self.assertLess(min(img.getdata()), 128)


if __name__ == "__main__":
    unittest.main()
