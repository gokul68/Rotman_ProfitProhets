# main.py - orchestrates the trading simulation loop
import time
import math
from datetime import datetime
from config import *
from rit_api import get_tick, get_securities, get_news, get_limits
from strategy import generate_signals, update_working_vol_from_news, enforce_limits_and_place, compute_portfolio_delta, delta_hedge_if_needed, safe_mid
from ledger import Ledger

def find_etf_row(assets):
    for r in assets:
        tk = r.get('ticker','')
        if tk == 'RTM' or (len(tk)==3 and tk.upper()=='RTM'):
            return r
    # fallback: non-option ticker (no C/P)
    for r in assets:
        tk = r.get('ticker','')
        if not ('C' in tk or 'P' in tk):
            return r
    return None

def compute_option_gross_net(assets):
    gross = 0
    net = 0
    for r in assets:
        tk = r.get('ticker','')
        if 'C' in tk or 'P' in tk:
            pos = int(r.get('position',0))
            size = abs(pos)
            gross += size
            net += pos
    return gross, net

def main_loop():
    ledger = Ledger()
    working_vol = WORKING_VOL_INITIAL
    mat_tick = MAT_TICKS
    print("Starting trading loop. Press Ctrl+C to stop.")
    while True:
        try:
            tick = get_tick()
        except Exception as e:
            print("Error getting tick:", e)
            time.sleep(1.0)
            continue
        if tick >= mat_tick:
            print("Heat ended (tick >= mat_tick). Exiting loop.")
            break

        # pull latest market & news
        assets = get_securities()
        news = get_news()
        
        # update working volatility from news (analyst updates)
        working_vol_prev = working_vol
        working_vol = update_working_vol_from_news(news, working_vol)
        if working_vol != working_vol_prev:
            print(f"{datetime.now()} - Working vol updated from news: {working_vol_prev:.3f} -> {working_vol:.3f}")

        # find ETF row & spot
        etf_row = find_etf_row(assets)
        if etf_row is None:
            print("Cannot find ETF row; skipping tick")
            time.sleep(TICK_SLEEP)
            continue
        S = float(etf_row.get('last', math.nan))
        current_etf_pos = int(etf_row.get('position',0))

        # compute signals
        signals = generate_signals(assets, S, tick, mat_tick, working_vol)

        # compute current option gross/net
        opt_gross, opt_net = compute_option_gross_net(assets)

        # display top few potential signals
        top_signals = [s for s in signals if s['decision'] != 'NO_DECISION'][:6]
        if top_signals:
            print(f"\nTick {tick} | S={S:.2f} | WorkingVol={working_vol:.3f} | top signals:")
            for s in top_signals:
                print(f"  {s['ticker']}: {s['decision']} edge ${s['edge_contract_$']:.2f} delta {s['delta']:.3f} vega {s['vega']:.3f}")
        else:
            print(f"Tick {tick} | S={S:.2f} | no actionable signals")

        # place trades for sorted signals until limits (simple sequential)
        for s in signals:
            if s['decision'] == 'NO_DECISION':
                continue
            # Enforce naive risk checks and place
            order = enforce_limits_and_place(ledger, s, opt_gross, opt_net)
            if order:
                # update gross/net after placing
                opt_gross += abs(int(order.get('quantity',0)))
                opt_net += int(order.get('quantity',0)) if order.get('action','').upper()=='BUY' else -int(order.get('quantity',0))
            time.sleep(0.05)  # small throttle

        # recompute portfolio delta after possible fills
        assets_after = get_securities()
        # optional: fill in 'delta' fields using current market IV and bs_delta — omitted here for brevity
        option_delta = compute_portfolio_delta(assets_after, working_vol, mat_tick, tick)
        current_etf_pos_after = int([r for r in assets_after if r.get('ticker','')=='RTM'][0].get('position',0))

        # delta hedge if needed
        hedge = delta_hedge_if_needed(ledger, option_delta, current_etf_pos_after)
        if hedge:
            print("Placed hedge:", hedge)

        # compute delta penalty for this second
        net_delta = option_delta + current_etf_pos_after
        penalty = 0.0
        if abs(net_delta) > DELTA_LIMIT:
            penalty = (abs(net_delta) - DELTA_LIMIT) * DELTA_PENALTY_RATE
            ledger.record_penalty(penalty, tick)
            print(f"Delta penalty at tick {tick}: ${penalty:.2f} (net_delta={net_delta})")

        # optional: compute / log unrealized P&L using mid prices (not implemented fully)
        # sleep to next iteration
        time.sleep(TICK_SLEEP)

    # loop done: final ledger export
    print("Exporting ledger...")
    ledger_csv = ledger.export()
    print("Ledger saved to", ledger_csv)
    print("Summary:", ledger.summary())

if __name__ == '__main__':
    main_loop()
