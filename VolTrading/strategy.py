# strategy.py - core strategy: signal generation, sizing, hedging, limit checks
import math
from typing import Dict, Any, List, Union, Tuple
import numpy as np
import re

from config import *
from bs_utils import bs_price_flag, bs_delta_flag, bs_vega_flag, implied_vol_from_market, years_remaining
from rit_api import post_order, get_securities, get_limits
from ledger import Ledger

def safe_mid(row: Dict[str,Any]) -> float:
    bid = row.get('bid', float('nan'))
    ask = row.get('ask', float('nan'))
    if not math.isnan(bid) and not math.isnan(ask):
        return 0.5*(bid+ask)
    return row.get('last', float('nan'))

def parse_strike(ticker: str) -> float:
    # expecting RTM48C format
    try:
        return float(ticker[3:5])
    except Exception:
        # fallback if formatting differs
        digits = ''.join([c for c in ticker if c.isdigit()])
        return float(digits) if digits else float('nan')

# def update_working_vol_from_news(news_items: List[Dict[str,Any]], current_vol: float) -> float:
#     """
#     Parse news text; if it contains a volatility announcement, extract numeric vol (e.g. '20%' or '0.20').
#     The RIT news format may vary; this attempts simple heuristics.
#     """
#     import re
#     vol = current_vol
#     for item in news_items:
#         text = (item.get('headline','') + ' ' + item.get('body','')).lower()
#         # find percent number
#         m = re.search(r'(\d{1,2}(?:\.\d+)?)\s*%', text)

#         if m:
#             val = float(m.group(1))/100.0
#             vol = val
#         else:
#             # try decimal forms like 0.20
#             m2 = re.search(r'0\.\d{1,3}', text)
#             if m2:
#                 vol = float(m2.group(0))
#     return vol

def update_working_vol_from_news(
    news_items: List[Dict[str, Any]], 
    current_vol: float
) -> Union[float, Tuple[float, float]]:
    """
    Parse RIT news text for volatility updates.

    Handles cases:
    - "current annualized realized volatility is 36%"
    - "realized volatility ... this week will be 11%"
    - "realized volatility ... next week will be between 08% and 13%"

    Ignores "risk free rate is 0%" announcements.

    Returns:
        - float if a single vol value is found
        - tuple (low, high) if a range is found
        - current_vol if nothing found
    """
    vol = current_vol

    for item in news_items:
        text = (item.get("headline", "") + " " + item.get("body", "")).lower()

        # Split into sentences for precision
        sentences = re.split(r'[.!?]', text)

        for sentence in sentences:
            if "volatil" not in sentence:
                continue

            # Case 1: range "08% and 13%"
            range_match = re.findall(r"(\d{1,2}(?:\.\d+)?)\s*%", sentence)
            if len(range_match) >= 2:
                try:
                    low, high = float(range_match[0]) / 100.0, float(range_match[1]) / 100.0
                    return (low + high)/2#(low, high)
                except ValueError:
                    continue

            # Case 2: single percent "36%"
            single_match = re.search(r"(\d{1,2}(?:\.\d+)?)\s*%", sentence)
            if single_match:
                try:
                    val = float(single_match.group(1)) / 100.0
                    vol = val
                    continue
                except ValueError:
                    continue

            # Case 3: decimal like "0.20"
            decimal_match = re.search(r"0\.\d{1,3}", sentence)
            if decimal_match:
                try:
                    vol = float(decimal_match.group(0))
                    continue
                except ValueError:
                    continue

    return vol

# def generate_signals(assets: List[Dict[str,Any]], S: float, current_tick:int, mat_tick:int, working_vol: float) -> List[Dict[str,Any]]:
#     T = years_remaining(mat_tick, current_tick)
#     signals = []
#     if T <= 0:
#         return signals

#     # Simple regime flag: tune thresholds to your sim
#     HIGH_VOL = working_vol >= 0.25
#     # Dynamic thresholds (stricter when vol is high)
#     price_thresh = PRICE_THRESH * (1.5 if HIGH_VOL else 1.0)          # contract $
#     vol_thresh   = VOL_THRESH   * (1.0 if HIGH_VOL else 0.8)

#     # Precompute best-ATM strike for later short-vol bias
#     option_rows = [r for r in assets if r.get('ticker') and (('C' in r['ticker']) or ('P' in r['ticker']))]
#     def moneyness_abs(row):
#         k = parse_strike(row['ticker'])
#         return abs((k - S) / max(S, 1e-9))
#     if option_rows:
#         best_atm_strike = parse_strike(min(option_rows, key=moneyness_abs)['ticker'])
#     else:
#         best_atm_strike = None

#     for row in option_rows:
#         tk = row['ticker']
#         mid = safe_mid(row)
#         if math.isnan(mid):
#             continue
#         K = parse_strike(tk)
#         flag = 'c' if 'C' in tk else 'p'

#         # Skip very deep ITM/OTM to avoid noisy IV and nasty gamma when shorting
#         if abs((K - S) / max(S, 1e-9)) > 0.10:  # 10% moneyness band
#             continue

#         # Market IV and theo at analyst vol
#         iv_m = implied_vol_from_market(mid, S, K, RISK_FREE, T, flag)
#         theo = bs_price_flag(flag, S, K, T, RISK_FREE, working_vol)

#         # Greeks (prefer market IV for greeks if available)
#         vol_for_greeks = iv_m if not math.isnan(iv_m) else working_vol
#         d = bs_delta_flag(flag, S, K, T, RISK_FREE, vol_for_greeks)
#         v = bs_vega_flag(flag, S, K, T, RISK_FREE, vol_for_greeks)

#         edge_per_option   = mid - theo
#         edge_per_contract = edge_per_option * 100.0
#         iv_diff = (iv_m - working_vol) if not math.isnan(iv_m) else float('nan')

#         decision = 'NO_DECISION'
#         # Require both an IV gap and a dollar edge (stricter when vol is high)
#         if (not math.isnan(iv_diff)) and (abs(iv_diff) >= vol_thresh) and (abs(edge_per_contract) >= price_thresh):
#             # If implied > forecast -> overpriced -> SELL; else BUY
#             decision = 'SELL' if iv_diff > 0 else 'BUY'

#             # When shorting vol, prefer ATM to reduce directional surprise
#             if decision == 'SELL' and best_atm_strike is not None:
#                 # light nudge: penalize distance from best_atm_strike in the ranking later
#                 atm_penalty = abs(K - best_atm_strike)
#             else:
#                 atm_penalty = 0.0
#         else:
#             atm_penalty = 0.0

#         signals.append({
#             'ticker': tk,
#             'flag': flag,
#             'K': K,
#             'mid': mid,
#             'iv_market': iv_m,
#             'bs_theo_at_working_vol': theo,
#             'delta': d,
#             'vega': v,
#             'edge_contract_$': edge_per_contract,
#             'iv_diff': iv_diff,
#             'decision': decision,
#             # regime-aware sizing hint (smaller vega target when shorting high vol)
#             'target_vega_hint': (120.0 if (decision == 'BUY' and not HIGH_VOL) else
#                                  90.0  if (decision == 'BUY' and HIGH_VOL) else
#                                  80.0  if (decision == 'SELL' and HIGH_VOL) else
#                                  120.0),
#             'atm_penalty': atm_penalty,
#             'moneyness_abs': abs((K - S) / max(S, 1e-9))
#         })

#     # Rank: bigger $ edge first; then prefer smaller atm_penalty; then closer to ATM
#     signals_sorted = sorted(
#         signals,
#         key=lambda x: (x['decision'] == 'NO_DECISION',
#                        -abs(x['edge_contract_$']),
#                        x.get('atm_penalty', 0.0),
#                        x.get('moneyness_abs', 0.0))
#     )
#     return signals_sorted

def generate_signals(assets: List[Dict[str,Any]], S: float, current_tick:int, mat_tick:int, working_vol: float) -> List[Dict[str,Any]]:
    T = years_remaining(mat_tick, current_tick)
    signals = []
    for row in assets:
        tk = row.get('ticker')
        if not tk: continue
        if ('C' not in tk) and ('P' not in tk):
            continue
        mid = safe_mid(row)
        if math.isnan(mid):
            continue
        K = parse_strike(tk)
        flag = 'c' if 'C' in tk else 'p'
        # market implied vol
        iv_m = implied_vol_from_market(mid, S, K, RISK_FREE, T, flag)
        # theoretical model price using analyst working_vol
        theo = bs_price_flag(flag, S, K, T, RISK_FREE, working_vol)
        # greeks (use market IV if available else working vol)
        vol_for_greeks = iv_m if not math.isnan(iv_m) else working_vol
        d = bs_delta_flag(flag, S, K, T, RISK_FREE, vol_for_greeks)
        v = bs_vega_flag(flag, S, K, T, RISK_FREE, vol_for_greeks)
        edge_per_option = mid - theo
        edge_per_contract = edge_per_option * 100.0
        iv_diff = (iv_m - working_vol) if not math.isnan(iv_m) else float('nan')
        decision = 'NO_DECISION'
        if (not math.isnan(iv_diff)) and (abs(iv_diff) >= VOL_THRESH) and (abs(edge_per_contract) >= PRICE_THRESH):
            decision = 'SELL' if iv_diff > 0 else 'BUY'
        signals.append({
            'ticker': tk,
            'flag': flag,
            'K': K,
            'mid': mid,
            'iv_market': iv_m,
            'bs_theo_at_working_vol': theo,
            'delta': d,
            'vega': v,
            'edge_contract_$': edge_per_contract,
            'iv_diff': iv_diff,
            'decision': decision
        })
    # rank by abs edge descending
    signals_sorted = sorted(signals, key=lambda x: abs(x['edge_contract_$']), reverse=True)
    return signals_sorted

def size_by_vega(vega_per_contract: float, target_vega: float=TARGET_VEGA_PER_TRADE) -> int:
    if vega_per_contract <= 0 or math.isnan(vega_per_contract):
        return 1
    n = int(round(target_vega / vega_per_contract))
    if n < 1:
        n = 1
    return min(n, MAX_CONTRACTS_ORDER)

def enforce_limits_and_place(ledger: Ledger, signal: Dict[str,Any], current_option_gross:int, current_option_net:int) -> Dict[str,Any]:
    """
    Enforce case limits before placing order; returns order response or None.
    current_option_gross/net should be computed from positions.
    """
    action = signal['decision']
    ticker = signal['ticker']
    v_per = signal['vega']
    size = size_by_vega(v_per)
    # Check gross limit (will be absolute sum after executing)
    projected_gross = current_option_gross + size
    if projected_gross > MAX_OPTION_GROSS:
        print(f"Cannot place {ticker} {action} {size}: would exceed option gross limit ({projected_gross}>{MAX_OPTION_GROSS})")
        return None
    # Check net limit: naive check (assumes buy increases net long, sell increases net short)
    # For brevity, we rely on API /limits for enforcement in addition to this local check.
    # Place MARKET order
    order = post_order(ticker, size, action, order_type='MARKET')
    if order:
        # record commission to ledger
        ledger.record_order(order, side_commission=abs(size)*COMMISSION_OPTION)
    return order

# constant for commission (kept here to avoid circular import)
COMMISSION_OPTION = 1.0
COMMISSION_ETF = 0.01

def compute_portfolio_delta(assets: List[Dict[str,Any]],
                            vol: float,
                            maturity_tick: int, 
                            current_tick: int
                            ) -> float:
    """
    Sum over option positions: delta * position * 100
    """
    total = 0.0
    spot = assets[0].get('last',0)
    for row in assets:
        tk = row.get('ticker','')
        if ('C' in tk) or ('P' in tk):
            try:
                pos = int(row.get('position',0))
            except Exception:
                pos = 0

            # parse strike from ticker (e.g. "RTMC100" or "RTMP95")
            try:
                K = float(''.join([c for c in tk if c.isdigit()]))
            except ValueError:
                continue

            tau = years_remaining(maturity_tick, current_tick)
            if tau <= 0:
                continue

            opt_type = 'c' if 'C' in tk else 'p'
            d = bs_delta_flag(opt_type, spot, K, tau, 0, vol)

            # in RIT, 1 option contract = 100 shares
            #print(pos, d)
            total += d * pos * 100
    return total

def delta_hedge_if_needed(ledger: Ledger, option_delta: float, current_etf_position: int, session_post_order=post_order) -> Dict[str,Any]:
    """
    Option_delta is sum(delta * position * 100). current_etf_position is current ETF shares.
    If net delta outside DELTA_LIMIT, place hedge (market) to bring net delta close to zero.
    """
    net_delta = option_delta + current_etf_position
    print(net_delta)
    if abs(net_delta) <= DELTA_LIMIT:
        return None
    target_shares = -option_delta  # desire ETF shares = -option_delta
    shares_to_trade = int(round(target_shares - current_etf_position))
    print(option_delta, shares_to_trade)
    if shares_to_trade == 0:
        return None
    action = 'BUY' if shares_to_trade > 0 else 'SELL'
    qty = min(abs(shares_to_trade), 10000)  # per-trade cap
    order = session_post_order('RTM', qty, action, order_type='MARKET')
    if order:
        ledger.record_order(order, side_commission=qty*COMMISSION_ETF)
    return order

def compute_delta_penalty_per_second(net_delta:int) -> float:
    if abs(net_delta) <= DELTA_LIMIT:
        return 0.0
    return (abs(net_delta) - DELTA_LIMIT) * DELTA_PENALTY_RATE
