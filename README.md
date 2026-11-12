# Index Options Dashboard (Streamlit)

Nifty / Bank Nifty / FinNifty option-chain dashboard with a rule-based call/put-buy screen.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
Run it locally from an Indian connection: NSE's public endpoints are unofficial and often block cloud IPs or change format.

## What it shows
- Index and expiry dropdowns (expiries come from NSE; Bank Nifty and FinNifty have monthly expiries only)
- S1-S3 / R1-R3: classic pivots from the previous session, plus OI walls (highest put/call OI strikes)
- Strategy score: Trend (close vs EMA20, EMA20 vs EMA50), Structure (last swing high/low: HH+HL vs LH+LL), Momentum (RSI14, MACD histogram), Chain (OI PCR, put-vs-call OI build-up near ATM)
- Chain review near ATM: bid, ask, volume, OI, change in OI, IV; ATM IV vs 20-day realised volatility
- Trade idea: score >= threshold gives BUY CALL, <= -threshold gives BUY PUT, otherwise NO TRADE. The picked strike must pass spread, volume and OI checks. Shows entry, stop, target, cost per lot and warnings (budget, IV rich, expiry day, near S/R)

## Caveats
Heuristics only: not backtested, not investment advice. Check lot sizes on NSE (editable in the sidebar).

## Push to GitHub
```bash
git init && git add . && git commit -m "Index options dashboard"
gh repo create nifty-options-dashboard --public --source=. --push
```
