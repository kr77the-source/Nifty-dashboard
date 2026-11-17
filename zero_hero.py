"""Expiry-day Zero-to-Hero screen. No account, no API key, no Streamlit. Needs only:  pip install requests
Runs on a phone (Pydroid 3 app) or a laptop with Indian internet.  Usage:  python zero_hero.py [SYMBOL] [auto]
Data: NSE option chain (live bid/ask, OI, volume, IV) + Yahoo Finance 5-minute candles. Rule-based, not advice."""
import csv
import io
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

IST = timezone(timedelta(hours=5, minutes=30))
BASE = "https://www.nseindia.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
HDRS = {**UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9", "Referer": BASE + "/option-chain"}
YF = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS"}
DEFAULT_LOT = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60}  # only if NSE's lot file can't be read
TH, LO, HI, LOTS, MIN_VOL, MIN_OI, MAX_SP, MAX_LAG = 4, 3.0, 5.0, 2, 1000, 10000, 15, 30
_S = {}


def now():
    return datetime.now(IST)


def sgn(x):
    return (x > 0) - (x < 0)


def dfmt(iso):
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%b-%Y")


# ---------------- data ----------------
def api(path):
    err = "no response"
    for attempt in (0, 1):
        try:
            if attempt or _S.get("s") is None or time.time() - _S["t"] > 300:
                s = requests.Session()
                s.headers.update(HDRS)
                s.get(BASE + "/option-chain", timeout=10)  # NSE hands out cookies here
                _S.update(s=s, t=time.time())
            r = _S["s"].get(BASE + path, timeout=12)
            if r.status_code == 200:
                return r.json()
            err = f"HTTP {r.status_code}"
        except Exception as e:
            err = str(e)[:120]
    raise RuntimeError(f"NSE se data nahi aaya ({err}). Phone/laptop ke Indian internet par chalao (VPN band rakho).")


def expiries(sym):
    j = api(f"/api/option-chain-contract-info?symbol={quote(sym)}")
    return sorted(datetime.strptime(e, "%d-%b-%Y").strftime("%Y-%m-%d") for e in j["expiryDates"])


def lot_size(sym):
    try:
        t = requests.get("https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv", headers=UA, timeout=10).text
        for row in csv.reader(io.StringIO(t)):
            if len(row) > 2 and row[1].strip() == sym:
                return int(float(row[2]))
    except Exception:
        pass
    return DEFAULT_LOT.get(sym)


def chain(sym, expiry):
    """Live chain: (spot, rows sorted by strike). IV in %, chg = change in OI."""
    exp = datetime.strptime(expiry, "%Y-%m-%d").strftime("%d-%b-%Y")
    kind = "Indices" if sym in YF else "Equity"
    rec = api(f"/api/option-chain-v3?type={kind}&symbol={quote(sym)}&expiry={exp}")["records"]
    rows = []
    for d in rec["data"]:
        e = d.get("expiryDate") or d.get("expiryDates") or exp
        if isinstance(e, list):
            e = e[0] if e else exp
        if e != exp:
            continue
        r = {"strike": float(d["strikePrice"])}
        for p, leg in (("ce", d.get("CE")), ("pe", d.get("PE"))):
            x = leg or {}
            r.update({f"{p}_oi": float(x.get("openInterest") or 0), f"{p}_chg": float(x.get("changeinOpenInterest") or 0),
                      f"{p}_vol": float(x.get("totalTradedVolume") or 0), f"{p}_iv": float(x.get("impliedVolatility") or 0),
                      f"{p}_bid": float(x.get("bidprice") or x.get("bidPrice") or 0),
                      f"{p}_ask": float(x.get("askPrice") or x.get("askprice") or 0), f"{p}_ltp": float(x.get("lastPrice") or 0)})
        rows.append(r)
    if not rows or not rec.get("underlyingValue"):
        raise RuntimeError("NSE ki option chain khali aayi")
    return float(rec["underlyingValue"]), sorted(rows, key=lambda r: r["strike"])


def candles(sym, interval="5m", rng="8d"):
    """[(time, open, high, low, close)] from Yahoo Finance, oldest first."""
    y = YF.get(sym, sym + ".NS")
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(y)}?interval={interval}&range={rng}", headers=UA, timeout=12)
    r.raise_for_status()
    j = r.json()["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    out = [(datetime.fromtimestamp(t, IST), o, h, l, c) for t, o, h, l, c in zip(j["timestamp"], q["open"], q["high"], q["low"], q["close"])
           if None not in (o, h, l, c)]
    if not out:
        raise RuntimeError("Yahoo se candles nahi aayi")
    return out


# ---------------- strategy ----------------
def ema(v, span=None, alpha=None):
    a = alpha if alpha is not None else 2 / (span + 1)
    out, e = [], None
    for x in v:
        e = x if e is None else a * x + (1 - a) * e
        out.append(e)
    return out


def price_scores(cl, hi, lo):
    """Trend, Structure, Momentum, each -2..+2, from 5-minute candles."""
    px, e20, e50 = cl[-1], ema(cl, 20)[-1], ema(cl, 50)[-1]
    d = [b - a for a, b in zip(cl, cl[1:])]
    up, dn = ema([max(x, 0) for x in d], alpha=1 / 14)[-1], ema([max(-x, 0) for x in d], alpha=1 / 14)[-1]
    rsi = 100 - 100 / (1 + up / dn) if dn else 100.0
    macd = [a - b for a, b in zip(ema(cl, 12), ema(cl, 26))]
    hist = macd[-1] - ema(macd, 9)[-1]
    sh = [hi[i] for i in range(3, len(hi) - 3) if hi[i] == max(hi[i - 3:i + 4])]
    sl = [lo[i] for i in range(3, len(lo) - 3) if lo[i] == min(lo[i - 3:i + 4])]
    out = {"Trend": (sgn(px - e20) + sgn(e20 - e50), "")}
    if len(sh) > 1 and len(sl) > 1:
        out["Structure"] = ((1 if sh[-1] > sh[-2] else -1) + (1 if sl[-1] > sl[-2] else -1), "")
    else:
        out["Structure"] = (0, "")
    out["Momentum"] = ((1 if rsi > 55 else -1 if rsi < 45 else 0) + sgn(hist), "")
    return out


def pivots(h, l, c):
    p = (h + l + c) / 3
    return {"R3": h + 2 * (p - l), "R2": p + (h - l), "R1": 2 * p - l, "Pivot": p, "S1": 2 * p - h, "S2": p - (h - l), "S3": l - 2 * (h - p)}


def chain_scores(rows, spot):
    i = min(range(len(rows)), key=lambda k: abs(rows[k]["strike"] - spot))
    w = rows[max(i - 6, 0):i + 7]
    pcr = sum(r["pe_oi"] for r in rows) / max(sum(r["ce_oi"] for r in rows), 1)
    dchg = sum(r["pe_chg"] for r in w) - sum(r["ce_chg"] for r in w)
    iv = [v for v in (rows[i]["ce_iv"], rows[i]["pe_iv"]) if v]
    sc = {"PCR": 1 if pcr > 1.1 else -1 if pcr < 0.9 else 0, "OI": sgn(dchg)}
    return sc, pcr, (sum(iv) / len(iv) if iv else 0.0)


def max_pain(rows):
    return min((r["strike"] for r in rows), key=lambda x: sum(r["ce_oi"] * max(x - r["strike"], 0) + r["pe_oi"] * max(r["strike"] - x, 0) for r in rows))


def pick_zero(rows, spot, side):
    """OTM strikes priced LO..HI (ask, or LTP when unquoted), liquid, most traded first; plus nearest misses."""
    otm = [dict(r) for r in rows if (r["strike"] > spot if side == "ce" else r["strike"] < spot)]
    for r in otm:
        r["px"] = r[f"{side}_ask"] if r[f"{side}_ask"] > 0 else r[f"{side}_ltp"]

    def wide(r):
        a, b = r[f"{side}_ask"], r[f"{side}_bid"]
        return a > 0 and b > 0 and (a - b) / ((a + b) / 2) * 100 > MAX_SP
    ok = [r for r in otm if LO <= r["px"] <= HI and r[f"{side}_vol"] >= MIN_VOL and r[f"{side}_oi"] >= MIN_OI and not wide(r)]
    ok.sort(key=lambda r: -r[f"{side}_vol"])
    above = [r for r in otm if r["px"] > HI]
    below = [r for r in otm if 0 < r["px"] < LO]
    miss = ([min(above, key=lambda r: r["px"])] if above else []) + ([max(below, key=lambda r: r["px"])] if below else [])
    return ok, miss


def touch_chance(spot, strike, iv_pct, years, call):
    if iv_pct <= 0 or years <= 0:
        return None
    s = iv_pct / 100 * math.sqrt(years)
    d2 = (math.log(spot / strike) - s * s / 2) / s
    phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    p = phi(d2) if call else phi(-d2)
    return p, min(2 * p, 1.0)


# ---------------- screen ----------------
def screen(sym, test=False):
    t = now()
    today = t.strftime("%Y-%m-%d")
    ex = next((e for e in expiries(sym) if e >= today), None)
    if ex is None:
        return ["Is symbol ki koi expiry nahi mili."]
    if ex != today and not test:
        return [f"Aaj {sym} ki expiry nahi hai. Next expiry {dfmt(ex)} ({(datetime.strptime(ex, '%Y-%m-%d').date() - t.date()).days} din baad).",
                "Ye script sirf expiry-day Zero-to-Hero ke liye hai. (Data check karna ho to: python zero_hero.py NIFTY test)"]
    t0, t1 = t.replace(hour=9, minute=15, second=0, microsecond=0), t.replace(hour=15, minute=30, second=0, microsecond=0)
    if t < t0:
        return ["Market 9:15 par khulega."]
    if t > t1:
        return ["Aaj ki expiry khatam ho chuki hai (3:30 PM)."]
    spot, rows = chain(sym, ex)
    bars = candles(sym)
    if len(bars) < 60 or (bars[-1][0] < t - timedelta(minutes=MAX_LAG) and t - t0 > timedelta(minutes=20)):
        return [f"Candles fresh nahi hain (last candle {bars[-1][0]:%d-%b %H:%M}). Purane data par trade nahi dikhaunga."]
    prev = [b for b in bars if b[0].date() < t.date()]
    td = [b for b in bars if b[0].date() == t.date()]
    if not prev:
        return ["Pichle session ka data nahi mila."]
    last = [b for b in prev if b[0].date() == prev[-1][0].date()]
    piv = pivots(max(b[2] for b in last), min(b[3] for b in last), last[-1][4])
    sc = {k: v[0] for k, v in price_scores([b[4] for b in bars], [b[2] for b in bars], [b[3] for b in bars]).items()}
    cs, pcr, atm_iv = chain_scores(rows, spot)
    sc.update(cs)
    chg = spot / td[0][1] - 1 if td else 0.0
    sc["Day"] = 1 if chg > 0.0015 else -1 if chg < -0.0015 else 0
    mp = max_pain(rows)
    dmp = (mp - spot) / spot
    sc["MaxPain"] = 1 if dmp > 0.002 else -1 if dmp < -0.002 else 0
    total = sum(sc.values())
    side = "ce" if total >= TH else "pe" if total <= -TH else None
    left = t1 - t
    mood = "BULLISH" if side == "ce" else "BEARISH" if side == "pe" else "SIDEWAYS"
    out = [f"LIVE NSE {t:%H:%M:%S} IST | expiry close mein {left.seconds // 3600}h {left.seconds % 3600 // 60}m | candles till {bars[-1][0]:%H:%M}",
           f"{sym} {spot:,.1f} | {mood} ({total:+d}/10) | Trend {sc['Trend']:+d} Structure {sc['Structure']:+d} Momentum {sc['Momentum']:+d} | PCR {pcr:.2f} | Max pain {mp:,.0f}",
           "R1 {R1:,.1f} R2 {R2:,.1f} R3 {R3:,.1f}  |  S1 {S1:,.1f} S2 {S2:,.1f} S3 {S3:,.1f}".format(**piv)]
    if side is None:
        return out + [f"NO TRADE: score {total:+d}, need +-{TH} or more. Zero-to-Hero mein direction pakki chahiye."]
    call, kind = side == "ce", "CALL" if side == "ce" else "PUT"
    ok, miss = pick_zero(rows, spot, side)
    if not ok:
        near = " / ".join(f"{int(r['strike'])} @ Rs{r['px']:.2f}" for r in miss)
        return out + [f"{kind} bias hai, par abhi Rs{LO:g}-{HI:g} wala liquid strike nahi." + (f" Nearest: {near}." if near else "") + " Thodi der baad dobara dekho."]
    r, lot = ok[0], lot_size(sym)
    entry, strike = r["px"], int(r["strike"])
    out += ["", f">>> ZERO-TO-HERO: BUY {kind} {sym} {strike} {side.upper()} ({dfmt(ex)})",
            f"Entry Rs{entry:.2f} ({'ask' if r[side + '_ask'] > 0 else 'LTP'})" + (f" | Cost/lot Rs{entry * lot:,.0f} | {LOTS} lots Rs{entry * lot * LOTS:,.0f} (yehi max loss)" if lot else " | Lot size nahi mila (premium per unit)"),
            f"Target 1 Rs{entry * 3:.2f} (3x, aadha becho) | Target 2 Rs{entry * 8:.2f} (8x, baaki) | Exit: spot {strike:,} touch kare ya 3:15 PM, jo pehle"]
    need = abs(strike - spot)
    tc = touch_chance(spot, strike, r[f"{side}_iv"] or atm_iv, left.total_seconds() / (365 * 24 * 3600), call)
    pc = lambda p: "<0.1%" if p < 0.001 else f"{p:.1%}"
    out.append(f"Spot ko {need:,.0f} pts ({need / spot:.2%}) {'upar' if call else 'neeche'} jana hoga" + (f" | market-implied chance: expiry par ITM {pc(tc[0])}, beech mein touch {pc(tc[1])}" if tc else ""))
    out.append(f"Bid {r[side + '_bid']:.2f} / Ask {r[side + '_ask']:.2f} | Vol {r[side + '_vol']:,.0f} | OI {r[side + '_oi']:,.0f} | IV {r[side + '_iv']:.1f}% | Lot {lot or 'n/a'}")
    more = ", ".join(f"{int(x['strike'])} (Rs{x['px']:.2f})" for x in ok[1:4])
    if more:
        out.append("Band mein aur: " + more)
    if left.total_seconds() > 4 * 3600:
        out.append("Abhi expiry mein 4 ghante se zyada hain; last 2-3 ghante mein explosion hota hai.")
    return out + ["Zero-to-Hero lottery hai: aksar poora premium zero hota hai. Sirf wahi paisa lagao jo doob jaye. Not advice."]


def main():
    args = [a for a in sys.argv[1:]]
    sym = (args[0] if args and args[0].lower() not in ("auto", "test") else input("Symbol [NIFTY]: ").strip().upper() or "NIFTY") if sys.stdin.isatty() or args else "NIFTY"
    test = "test" in [a.lower() for a in args]
    auto = "auto" in [a.lower() for a in args] or (not args and sys.stdin.isatty() and input("Har 30 sec refresh? (y/N): ").strip().lower() == "y")
    while True:
        try:
            print("\n".join(screen(sym.upper(), test)))
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
        if not auto:
            break
        print("-" * 40)
        try:
            time.sleep(30)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
