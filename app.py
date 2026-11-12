import pandas as pd
import streamlit as st

import nse
import strategy as sg

LOT = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60}  # defaults - verify on NSE, editable in sidebar
st.set_page_config("Index Options Dashboard", layout="wide")
st.title("📈 Index Options Dashboard")


@st.cache_data(ttl=600)
def get_exp(sym): return nse.expiries(sym)
@st.cache_data(ttl=300)
def get_hist(sym): return nse.history(sym)
@st.cache_data(ttl=30)
def get_chain(sym, ex): return nse.chain(sym, ex)


with st.sidebar:
    sym = st.selectbox("Index", list(LOT))
    exps = get_exp(sym)
    if not exps:
        st.error("Could not load expiries from NSE. Retry in a minute.")
        st.stop()
    ex = st.selectbox("Expiry", exps)
    lot = st.number_input("Lot size (verify on NSE)", 1, 1000, LOT[sym])
    budget = st.number_input("Budget per lot (₹)", 0, 10_000_000, 10_000, 500)
    th = st.slider("Signal threshold (|score| >=)", 1, 6, 3)
    off = st.slider("Strike offset (0 = ATM)", 0, 3, 0)
    sl = st.slider("Stop-loss on premium (%)", 10, 60, 30)
    rr = st.slider("Reward : risk", 1.0, 4.0, 2.0, 0.5)
    mx_sp = st.slider("Max bid-ask spread (%)", 1, 20, 5)
    mn_vol = st.number_input("Min volume", 0, value=1000, step=500)
    mn_oi = st.number_input("Min OI", 0, value=10000, step=1000)
    if st.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()

try:
    spot, ch, ts = get_chain(sym, ex)
    h = get_hist(sym)
except Exception as e:
    st.error(f"Data error: {e}")
    st.stop()

done = h[h.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
piv = sg.pivots(done.iloc[-1])
sc, rv = sg.price_scores(h)
cs, pcr, atm_iv, win = sg.chain_scores(ch, spot)
sc.update(cs)
total = sum(v[0] for v in sc.values())
side = "ce" if total >= th else "pe" if total <= -th else None
dte = (pd.to_datetime(ex, format="%d-%b-%Y") - pd.Timestamp.now().normalize()).days

m = st.columns(5)
m[0].metric("Spot", f"{spot:,.2f}")
m[1].metric("PCR (OI)", f"{pcr:.2f}")
m[2].metric("ATM IV", f"{atm_iv:.1f}%")
m[3].metric("20d realised vol", f"{rv:.1f}%")
m[4].metric("Days to expiry", dte)
st.caption(f"NSE timestamp: {ts}")

s_oi, r_oi = sg.oi_levels(ch, spot)
keys = ["R3", "R2", "R1", "Pivot", "S1", "S2", "S3"]
a, b = st.columns(2)
a.subheader("Pivot levels (previous session)")
a.dataframe(pd.DataFrame({"Level": keys, "Price": [round(piv[k], 1) for k in keys]}), hide_index=True)
b.subheader("OI walls (highest-OI strikes)")
b.dataframe(pd.DataFrame({"Level": ["R3", "R2", "R1", "S1", "S2", "S3"],
                          "Strike": (r_oi + [None] * 3)[:3][::-1] + (s_oi + [None] * 3)[:3]}), hide_index=True)

st.subheader("Strategy: Trend · Structure · Momentum · Chain")
st.dataframe(pd.DataFrame([{"Factor": k, "Score": v[0], "Reading": v[1]} for k, v in sc.items()]), hide_index=True)
st.metric("Total score (-8 bearish ... +8 bullish)", f"{total:+d}")

st.subheader("Chain near ATM: bid · ask · volume · OI · IV")
cols = {"ce_oi": "CE OI", "ce_chg": "CE ΔOI", "ce_vol": "CE Vol", "ce_iv": "CE IV", "ce_bid": "CE Bid",
        "ce_ask": "CE Ask", "strike": "Strike", "pe_bid": "PE Bid", "pe_ask": "PE Ask", "pe_iv": "PE IV",
        "pe_vol": "PE Vol", "pe_chg": "PE ΔOI", "pe_oi": "PE OI"}
st.dataframe(win[list(cols)].rename(columns=cols), hide_index=True)

st.subheader("Trade idea")
if side is None:
    st.warning(f"NO TRADE: score {total:+d} is inside ±{th}. Trend, structure, momentum and chain do not agree enough.")
else:
    row = sg.pick(ch, spot, side, off)
    checks, sp, q = sg.liquidity(row, side, mx_sp, mn_vol, mn_oi)
    entry = row[f"{side}_ask"] if q else row[f"{side}_ltp"]
    kind, tag = ("CALL", "S1") if side == "ce" else ("PUT", "R1")
    if entry <= 0 or not all(checks.values()):
        st.warning(f"WAIT: {kind} bias (score {total:+d}) but {int(row.strike)} {side.upper()} fails: "
                   + ", ".join(k for k, v in checks.items() if not v))
    else:
        slp, tgt, cost = entry * (1 - sl / 100), entry * (1 + sl * rr / 100), entry * lot
        st.success(f"BUY {kind}: {sym} {int(row.strike)} {side.upper()} · expiry {ex}")
        t = st.columns(4)
        t[0].metric("Entry (ask)" if q else "Entry (LTP)", f"₹{entry:.2f}")
        t[1].metric("Stop-loss", f"₹{slp:.2f}")
        t[2].metric("Target", f"₹{tgt:.2f}")
        t[3].metric("Cost / lot", f"₹{cost:,.0f}")
        st.write(f"Max loss at stop ≈ ₹{(entry - slp) * lot:,.0f} per lot. Also exit if {sym} closes "
                 f"{'below' if side == 'ce' else 'above'} {tag} ({piv[tag]:,.0f}).")
        st.caption(f"Bid {row[side + '_bid']} · Ask {row[side + '_ask']} · Spread {sp:.1f}% · "
                   f"Vol {row[side + '_vol']:,} · OI {row[side + '_oi']:,} · IV {row[side + '_iv']}%")
        near = piv["R1" if side == "ce" else "S1"]
        for n in [
            cost > budget and f"Cost ₹{cost:,.0f} is above your budget ₹{budget:,.0f}.",
            not q and "Bid/ask unavailable (market closed?). LTP used; re-check at open.",
            rv and atm_iv > 1.5 * rv and f"ATM IV {atm_iv:.0f}% is rich vs realised {rv:.0f}%: IV-crush risk for buyers.",
            dte <= 1 and "Expiry within a day: theta decay is extreme, keep size tiny.",
            abs(spot - near) / spot < 0.003 and f"Spot is within 0.3% of {'R1' if side == 'ce' else 'S1'}: limited room.",
        ]:
            if n:
                st.warning(n)

st.caption("Rule-based screen, not backtested, not investment advice. Most retail option buyers lose money.")
