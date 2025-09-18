# config.py
# Tickers - adapt to your case instance tickers if different
ETF_TICKER = "RITC"      # ETF (USD)
BULL_TICKER = "BULL"     # stock 1 (CAD)
BEAR_TICKER = "BEAR"     # stock 2 (CAD)
FX_TICKER = "USD"        # USD quoted in CAD (CAD per 1 USD)

# Trading/risk knobs
MAX_ORDER_SIZE = 10000   # API enforced, keep <= this
SLICE_SIZE = 1000        # per-slice quantity when unwinding
SLEEP_BETWEEN_CYCLES = 0.5  # seconds between main loop iterations
ACCEPTANCE_THRESHOLD = 0.02 # 2% margin relative to fair value required for auto-accept tender
CONVERTER_COST_PER_SHARE = 1_500.0 / 10000.0  # $1,500 per 10k shares -> per-share
MAX_GROSS_LIMIT = 20000   # example gross limit (units count; adapt from /limits)
