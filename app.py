from math import erf, exp, log, sqrt

import pandas as pd
import streamlit as st

import nse
import strategy as sg

TH, SL, RR, MIN_VOL, MIN_OI, FAR = 3, 30, 2.0, 1000, 10000, 0.02  # far OTM = ~2% from spot
STEP = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50}


def est_expiries(symbol, n=5):
    """Estimated expiry dates (Tuesdays) when NSE is unreachable; holidays are not adjusted."""
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


def bs(s, k, iv, t, call, r=0.065):
    """Black-Scholes premium estimate (iv as a decimal, t in years)."""
    if t <= 0 or iv <= 0:
        return max(s - k, 0) if call else max(k - s, 0)
    v = iv * sqrt(t)
    d1 = (log(s / k) + (r + iv * iv / 2) * t) / v
    N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
    return s * N(d1) - k * exp(-r * t) * N(d1 - v) if call else k * exp(-r * t) * N(v - d1) - s * N(-d1)


st.set_page_config("Nifty Options", layout="centered")
st.markdown("<style>.block-container{padding-top:4.5rem}</style>"
            "<div style='font-size:13px;font-weight:600;letter-spacing:1px;opacity:.7'>NIFTY OPTIONS</div>",
            unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def get_syms(): return nse.symbols()
@st.cache_data(ttl=3600)
def get_lots(): return nse.lot_sizes()
@st.cache_data(ttl=300)
def get_hist(s): return nse.history(s)


@st.cache_data(ttl=120)
def get_exp(s):
    try:
        return nse.expiries(s)
    except Exception:
        return []


@st.cache_data(ttl=20)
def get_chain(s, e):
    try:
        return nse.chain(s, e)
    except Exception:
        return None


a, b = st.columns(2)
sym = a.selectbox("Symbol (type to search)", get_syms())
exps = get_exp(sym)
ex = b.selectbox("Expiry" if exps else "Expiry (estimated)", exps or est_expiries(sym))
c, d = st.columns([2, 1])
go = c.button("🔍 Search", type="primary", use_container_width=True)
auto = d.toggle("Auto-run")
if go:
    st.session_state.run = True
if not (st.session_state.get("run") or auto):
    st.caption("Symbol aur expiry chuno, phir Search dabao.")
    st.stop()


@st.fragment(run_every=30 if auto else None)
def view():
    try:
        h = get_hist(sym)
        assert len(h) > 60
    except Exception:
        st.error("Price history nahi mili (Yahoo). Thodi der baad Search dabao.")
        return
    got = get_chain(sym, ex)
    spot, ch, ts = got if got else (float(h["Close"].iloc[-1]), None, "")
    done = h[h.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
    piv = sg.pivots(done.iloc[-1])
    sc, rv = sg.price_scores(h)
    pcr = atm_iv = 0.0
    if ch is not None:
        cs, pcr, atm_iv, _ = sg.chain_scores(ch, spot)
        sc.update(cs)
    total = sum(v[0] for v in sc.values())
    side = "ce" if total >= TH else "pe" if total <= -TH else None
    dte = (pd.to_datetime(ex, format="%d-%b-%Y") - pd.Timestamp.now().normalize()).days

    mood = "🟢 BULLISH" if side == "ce" else "🔴 BEARISH" if side == "pe" else "🟡 SIDEWAYS"
    st.markdown(f"**{sym} {spot:,.1f}** · {mood} ({total:+d}) · Trend {sc['Trend'][0]:+d} · "
                f"Structure {sc['Structure'][0]:+d} · Momentum {sc['Momentum'][0]:+d}"
                + (f" · PCR {pcr:.2f}" if ch is not None else ""))
    st.markdown(" · ".join(f"R{i} {piv[f'R{i}']:,.1f}" for i in (1, 2, 3)) + "  |  "
                + " · ".join(f"S{i} {piv[f'S{i}']:,.1f}" for i in (1, 2, 3)))

    if side is None:
        st.warning(f"NO TRADE · score {total:+d}, need ±{TH} or more")
    else:
        call = side == "ce"
        lv = sorted((v, k) for k, v in piv.items())
        up = [(v, k) for v, k in lv if v > spot]
        dn = [(v, k) for v, k in lv if v < spot][::-1]
        stop, tgts = (dn[:1], up[:2]) if call else (up[:1], dn[:2])
        fmt = lambda L: " / ".join(f"{k} {v:,.1f}" for v, k in L) or "n/a"
        st.success(f"BUY {'CALL' if call else 'PUT'} · {sym} · {ex}")
        t = max(dte, 0.3) / 365
        iv0 = atm_iv or (rv * 1.2 if rv == rv else 0.0)  # % ; realised-vol proxy when no chain
        tspot = tgts[0][0] if tgts else None
        lot = get_lots().get(sym) or nse.DEFAULT_LOT.get(sym)
        for name, far in (("ATM", False), ("Far OTM ~2%", True)):
            goal = spot * ((1 + FAR) if call else (1 - FAR)) if far else spot
            if ch is not None:
                row = ch.iloc[(ch.strike - goal).abs().idxmin()]
                strike = float(row.strike)
                checks, sp, q = sg.liquidity(row, side, 15 if far else 5, MIN_VOL, MIN_OI)
                entry = row[f"{side}_ask"] if q else row[f"{side}_ltp"]
                iv = row[f"{side}_iv"] or atm_iv
                bad = [n for n, ok in checks.items() if not ok]
                if entry <= 0 or bad:
                    st.caption(f"{name} {int(strike)} {side.upper()}: skipped ({', '.join(bad) or 'no price'})")
                    continue
            elif sym in STEP:
                strike = float(round(goal / STEP[sym]) * STEP[sym])
                iv = iv0
                entry = bs(spot, strike, iv / 100, t, call) if iv else 0
                if entry <= 0:
                    st.caption(f"{name} {int(strike)} {side.upper()}: premium estimate unavailable")
                    continue
            else:
                st.caption(f"{name}: strike not available here, pick it in your broker chain")
                continue
            tgt = bs(tspot, strike, iv / 100, max(t - 1 / 365, 0.1 / 365), call) if tspot and iv else 0
            if tgt <= entry:
                tgt = entry * (1 + SL * RR / 100)
            slp = entry * (1 - (50 if far else SL) / 100)
            pre = "~" if ch is None else ""
            cost = f" · Cost/lot ₹{entry * lot:,.0f}" if lot else ""
            st.markdown(f"**{name} · {int(strike)} {side.upper()}** — Entry {pre}₹{entry:.2f} · "
                        f"Exit {pre}₹{slp:.2f} · Target ~₹{tgt:.2f}{cost}")
        st.markdown(f"**Spot exit:** close {'below' if call else 'above'} {fmt(stop)} · **Spot target:** {fmt(tgts)}")
        st.caption("~ = model estimate (target is the premium if spot reaches the first spot target"
                   + ("; entry/exit too, as NSE chain is unreachable here, so confirm in your broker app" if ch is None else "")
                   + "). Far OTM is a low-probability trade: the whole premium can go to zero.")
        if ch is not None and rv and atm_iv > 1.5 * rv:
            st.caption(f"⚠ IV {atm_iv:.0f}% is rich vs realised {rv:.0f}%: IV-crush risk for buyers.")
        if dte <= 1:
            st.caption("⚠ Expiry within a day: heavy theta decay, keep size tiny.")
    st.caption(f"{ts or 'Price data: Yahoo'} · Rule-based, not backtested, not advice.")


view()
