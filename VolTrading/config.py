# config.py - global config and constants
API_KEY = {'X-API-Key': 'IIFLZKL1'}
BASE = 'http://localhost:9999/v1'
RISK_FREE = 0.0

# Decision thresholds
VOL_THRESH = 0.03           # 3 percentage points
PRICE_THRESH = 50           # $ per contract ($0.50 premium * 100)
TARGET_VEGA_PER_TRADE = 200 # target vega units per trade (tuneable)
MAX_CONTRACTS_ORDER = 100
MAX_OPTION_GROSS = 2500
MAX_OPTION_NET = 1000
MAX_ETF_GROSS = 50000
MAX_ETF_NET = 50000
DELTA_LIMIT = 5000
DELTA_PENALTY_RATE = 0.01   # $ per share per second above limit
TICK_SLEEP = 0.5            # seconds between loop iterations
WORKING_VOL_INITIAL = 0.20  # starting analyst forecast (20%)
MAT_TICKS = 300             # terminal tick for the heat
