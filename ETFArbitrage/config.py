# config.py

# --- API ---
API_KEY = "IIFLZKL1"        # replace with your actual RIT key
BASE_URL = "http://localhost:9999/v1"

# --- Tickers (from case) ---
ETF_TICKER  = "RITC"   # ETF quoted in USD
BULL_TICKER = "BULL"   # CAD stock
BEAR_TICKER = "BEAR"   # CAD stock
FX_TICKER   = "USD"    # CAD per 1 USD

# --- Loop / Limits ---
SLEEP_BETWEEN_CYCLES = 0.40
MAX_GROSS_LIMIT      = 200_000     # fallback if /limits unavailable
CONVERTER_BATCH      = 10_000      # converters operate in 10k blocks

# --- Costs (per case) ---
CONVERTER_COST_PER_SHARE = 1500.0 / CONVERTER_BATCH   # 0.15 CAD/sh
BOOK_FALLBACK_SPREAD_CAD = 0.04                       # if book empty, assume 4c spread

# --- Tender acceptance thresholds (tune) ---
ABS_BUFFER          = 0.01   # safety cushion above costs (0.5c)
MIN_ABS_EDGE        = 0.02    # ignore edges smaller than 1c
MIN_EDGE_TO_CONSIDER= 0.00    # keep 0 if using abs/rel checks below

# --- Spot arbitrage (ETF vs basket) ---
ENABLE_SPOT_ARB        = True
SPOT_ARB_ETF_CLIP      = 1000       # ETF size per action
SPOT_ARB_STOCK_CLIP    = 500       # each of BULL/BEAR per action
SPOT_ARB_COOLDOWN_S    = 1.0       # pause after a spot-arb burst
SPOT_REL_EDGE_MIN      = 0.004      # 0.2% relative edge
SPOT_MIN_ABS_OVER_COST = 0.00       # extra absolute over cost to require (can keep 0)

# --- Execution ---
DEFAULT_SLICE_SIZE   = 2000
MAX_ORDER_SIZE       = 10000
USE_PASSIVE_DEFAULT  = True    # try limit at NBBO first; fallback to market in Executor