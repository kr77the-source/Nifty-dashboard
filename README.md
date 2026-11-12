# Nifty Options Dashboard (Streamlit)

Compact option-chain dashboard for Nifty, Bank Nifty, FinNifty and F&O stocks.

- Searchable symbol dropdown (type to filter) and expiry dropdown
- Search button, plus Auto-run toggle (refreshes every N seconds)
- One-line market trend (Trend, Structure, Momentum, PCR) and one-line R1-R3 / S1-S3 (pivots)
- Trade idea: BUY CALL / BUY PUT / NO TRADE with entry, exit (stop-loss), target, plus spot exit/target from pivot levels
- Chain review (bid, ask, volume, OI, IV) and score breakdown in collapsed sections

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
NSE's endpoints are unofficial and often block cloud servers, so run locally from an Indian connection if the deployed app shows no data.

Heuristics only: not backtested, not investment advice.
