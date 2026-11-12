"""NSE option chain + Yahoo Finance price history (no Streamlit dependency)."""
import io
from urllib.parse import quote

import pandas as pd
import requests
import yfinance as yf

BASE = "https://www.nseindia.com"
HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE + "/option-chain",
}
INDEX = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS"}
DEFAULT_LOT = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60}  # verify on NSE
FALLBACK = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "AXISBANK", "KOTAKBANK", "LT", "ITC",
            "BHARTIARTL", "TATASTEEL", "MARUTI", "SUNPHARMA", "BAJFINANCE", "HINDUNILVR", "ADANIENT",
            "ADANIPORTS", "WIPRO", "HCLTECH", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "M&M", "TITAN",
            "ASIANPAINT", "ULTRACEMCO", "JSWSTEEL", "SBILIFE"]


def _session():
    s = requests.Session()
    s.headers.update(HDRS)
    s.get(BASE + "/option-chain", timeout=8)  # sets the cookies NSE expects
    return s


def _legacy(symbol):
    return f"/api/option-chain-{'indices' if symbol in INDEX else 'equities'}?symbol={quote(symbol)}"


def symbols():
    """Indices first, then F&O stocks (NSE list, or a short fallback list)."""
    try:
        d = _session().get(BASE + "/api/underlying-information", timeout=8).json()["data"]
        stocks = sorted({x["symbol"] for x in d["UnderlyingList"]})
        if stocks:
            return list(INDEX) + stocks
    except Exception:
        pass
    return list(INDEX) + sorted(FALLBACK)


def lot_sizes():
    """{symbol: lot size} from NSE's market-lots file; {} if unavailable."""
    try:
        t = requests.get("https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv", headers=HDRS, timeout=8).text
        df = pd.read_csv(io.StringIO(t), skipinitialspace=True)
        sym, first = df.iloc[:, 1].astype(str).str.strip(), pd.to_numeric(df.iloc[:, 2], errors="coerce")
        return {s: int(v) for s, v in zip(sym, first) if pd.notna(v)}
    except Exception:
        return {}


def expiries(symbol):
    s = _session()
    for path in (f"/api/option-chain-contract-info?symbol={quote(symbol)}", _legacy(symbol)):
        try:
            j = s.get(BASE + path, timeout=8).json()
            e = j.get("expiryDates") or j.get("records", {}).get("expiryDates")
            if e:
                return e
        except Exception:
            pass
    return []


def _leg(x, p):
    x = x or {}
    g = lambda *k: next((x[i] for i in k if x.get(i)), 0)
    return {f"{p}_oi": g("openInterest"), f"{p}_chg": x.get("changeinOpenInterest", 0),
            f"{p}_vol": g("totalTradedVolume"), f"{p}_iv": g("impliedVolatility"),
            f"{p}_bid": g("bidprice", "bidPrice"), f"{p}_ask": g("askPrice", "askprice"),
            f"{p}_ltp": g("lastPrice")}


def chain(symbol, expiry):
    """Returns (spot, DataFrame sorted by strike, NSE timestamp)."""
    s = _session()
    kind = "Indices" if symbol in INDEX else "Equity"
    for path in (f"/api/option-chain-v3?type={kind}&symbol={quote(symbol)}&expiry={expiry}", _legacy(symbol)):
        try:
            rec = s.get(BASE + path, timeout=8).json()["records"]
            rows = [{"strike": d["strikePrice"], **_leg(d.get("CE"), "ce"), **_leg(d.get("PE"), "pe")}
                    for d in rec["data"] if (d.get("expiryDate") or d.get("expiryDates") or expiry) == expiry]
            if rows:
                df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)
                return float(rec["underlyingValue"]), df, rec.get("timestamp", "")
        except Exception:
            pass
    raise RuntimeError("NSE option chain unavailable (blocked, rate-limited or format changed)")


def history(symbol):
    df = yf.Ticker(INDEX.get(symbol, symbol + ".NS")).history(period="1y", interval="1d")
    return df[["Open", "High", "Low", "Close"]].dropna()


def est_expiries(symbol, n=5):
    """Estimated expiry dates (Tuesdays), used when NSE is unreachable. Holidays are not adjusted."""
    today = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    out = []
    if symbol == "NIFTY":  # weekly
        d = today + pd.Timedelta(days=(1 - today.weekday()) % 7)
        out = [d + pd.Timedelta(weeks=i) for i in range(n)]
    else:  # monthly: last Tuesday
        m = today.replace(day=1)
        while len(out) < n:
            last = m + pd.offsets.MonthEnd(0)
            tue = last - pd.Timedelta(days=(last.weekday() - 1) % 7)
            if tue >= today:
                out.append(tue)
            m = m + pd.offsets.MonthBegin(1)
    return [d.strftime("%d-%b-%Y") for d in out]
