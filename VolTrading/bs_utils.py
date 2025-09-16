# bs_utils.py - Black-Scholes helpers: price, greeks, implied vol
import numpy as np
from py_vollib.black_scholes import black_scholes as bs_price
from py_vollib.black_scholes.greeks.analytical import delta as bs_delta
from py_vollib.black_scholes.greeks.analytical import vega as bs_vega
import py_vollib.black.implied_volatility as iv_mod

RISK_FREE = 0.0

def years_remaining(mat_tick:int, current_tick:int) -> float:
    """
    Uses the same mapping as the case starter files:
    T_years = max((mat_tick - current_tick) / 3600, 0)
    (This mapping was used in your original helper.)
    """
    return max((mat_tick - current_tick) / 3600.0, 0.0)

def implied_vol_from_market(market_price: float, S: float, K: float, r: float, T: float, flag: str) -> float:
    try:
        return iv_mod.implied_volatility(market_price, S, K, r, T, flag)
    except Exception:
        return float('nan')

def bs_price_flag(flag: str, S: float, K: float, T: float, r: float, sigma: float) -> float:
    try:
        return float(bs_price(flag, S, K, T, r, sigma))
    except Exception:
        return float('nan')

def bs_delta_flag(flag: str, S: float, K: float, T: float, r: float, sigma: float) -> float:
    try:
        return float(bs_delta(flag, S, K, T, r, sigma))
    except Exception:
        return float('nan')

def bs_vega_flag(flag: str, S: float, K: float, T: float, r: float, sigma: float) -> float:
    try:
        return float(bs_vega(flag, S, K, T, r, sigma))
    except Exception:
        return float('nan')
