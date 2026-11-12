"""Support/resistance, trend-structure-momentum scoring, chain review, trade pick."""
import numpy as np

sgn = lambda x: int(x > 0) - int(x < 0)


def pivots(bar):
    h, l, c = bar["High"], bar["Low"], bar["Close"]
    p = (h + l + c) / 3
    return {"R3": h + 2 * (p - l), "R2": p + (h - l), "R1": 2 * p - l, "Pivot": p,
            "S1": 2 * p - h, "S2": p - (h - l), "S3": l - 2 * (h - p)}


def oi_levels(ch, spot):
    """Highest-OI strikes: puts below spot = supports, calls above spot = resistances."""
    s = ch[ch.strike < spot].nlargest(3, "pe_oi").strike.sort_values(ascending=False).tolist()
    r = ch[ch.strike > spot].nlargest(3, "ce_oi").strike.sort_values().tolist()
    return s, r


def price_scores(df):
    """Trend, Structure, Momentum from daily candles; each scored -2..+2."""
    c = df["Close"]
    ema = lambda n: c.ewm(span=n, adjust=False).mean()
    px, e20, e50 = c.iloc[-1], ema(20).iloc[-1], ema(50).iloc[-1]
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    rsi = 100 - 100 / (1 + up / dn) if dn else 100.0
    macd = ema(12) - ema(26)
    hist = (macd - macd.ewm(span=9, adjust=False).mean()).iloc[-1]
    hi, lo = df["High"], df["Low"]
    sh = hi[hi == hi.rolling(7, center=True).max()].dropna()
    sl = lo[lo == lo.rolling(7, center=True).min()].dropna()
    out = {"Trend": (sgn(px - e20) + sgn(e20 - e50), f"Close {px:,.0f} vs EMA20 {e20:,.0f} / EMA50 {e50:,.0f}")}
    if len(sh) > 1 and len(sl) > 1:
        hh, hl = sh.iloc[-1] > sh.iloc[-2], sl.iloc[-1] > sl.iloc[-2]
        out["Structure"] = ((1 if hh else -1) + (1 if hl else -1),
                            f"Swing high {'higher' if hh else 'lower'}, swing low {'higher' if hl else 'lower'}")
    else:
        out["Structure"] = (0, "Not enough swing points")
    out["Momentum"] = ((1 if rsi > 55 else -1 if rsi < 45 else 0) + sgn(hist), f"RSI {rsi:.0f}, MACD histogram {hist:+.1f}")
    rv = np.log(c).diff().tail(20).std() * np.sqrt(252) * 100  # 20-day realised vol, %
    return out, rv


def chain_scores(ch, spot):
    """PCR and OI build-up near ATM; returns scores, PCR, ATM IV, ATM window."""
    i = (ch.strike - spot).abs().idxmin()
    w = ch.iloc[max(i - 6, 0): i + 7]
    pcr = ch.pe_oi.sum() / max(ch.ce_oi.sum(), 1)
    dchg = w.pe_chg.sum() - w.ce_chg.sum()
    iv = [v for v in (ch.iloc[i].ce_iv, ch.iloc[i].pe_iv) if v]
    sc = {"PCR (OI)": (1 if pcr > 1.1 else -1 if pcr < 0.9 else 0, f"PCR {pcr:.2f}"),
          "OI build-up": (sgn(dchg), f"Put dOI minus Call dOI near ATM = {dchg:+,.0f}")}
    return sc, pcr, (sum(iv) / len(iv) if iv else 0.0), w


def pick(ch, spot, side, offset):
    i = (ch.strike - spot).abs().idxmin()
    j = i + offset if side == "ce" else i - offset
    return ch.iloc[min(max(j, 0), len(ch) - 1)]


def liquidity(row, p, max_spread, min_vol, min_oi):
    bid, ask = row[f"{p}_bid"], row[f"{p}_ask"]
    q = bool(bid > 0 and ask > 0)
    sp = (ask - bid) / ((ask + bid) / 2) * 100 if q else float("nan")
    checks = {f"Spread <= {max_spread:g}%": (not q) or sp <= max_spread,
              f"Volume >= {min_vol:,}": row[f"{p}_vol"] >= min_vol,
              f"OI >= {min_oi:,}": row[f"{p}_oi"] >= min_oi}
    return checks, sp, q
