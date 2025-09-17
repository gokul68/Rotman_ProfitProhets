import os
import sys
import time
import math
import traceback
from typing import Dict, Any, List, Optional, Tuple

import requests

# =========================
# ----- CONFIG / PARAMS ----
# =========================
BASE = os.environ.get("RIT_BASE", "http://localhost:9999/v1")
API_KEY = {"X-API-Key": os.environ.get("RIT_API_KEY", "IIFLZK1")}

TICK_LIMIT = 300           # 5-minute heat in Rotman
POLL_SLEEP = 0.25          # main loop sleep (sec)
BOOK_LOOK = True           # use order book to estimate spread/slippage

# Fees/limits from the case
FEE_MARKET_PER_SHARE = 0.02     # market orders cost
REBATE_LIMIT_PER_SHARE = 0.01   # rebate when your limit order gets filled
MAX_ORDER = 10_000              # per order cap (ETF and stocks)
CONVERTER_BATCH = 10_000        # creation/redemption batch size
CONVERTER_COST = 1500.0         # per use (CAD)
CONVERTER_COST_PER_SHARE = CONVERTER_COST / CONVERTER_BATCH  # 0.15 CAD/share

# Safety: do not exceed gross/net
RISK_MAX_GROSS = 1_000_000_000  # read from API, but keep a huge guard
RISK_MAX_NET   = 1_000_000_000

# Tender accept thresholds (CAD)
# We require per-share edge >= (unwind_cost + safety_buffer)
SAFETY_BUFFER = 0.01   # extra cushion
MIN_EDGE_TO_CONSIDER = 0.03  # ignore tiny edges even if costs are low

# Order preference
USE_LIMIT_FIRST = True
LIMIT_IMPROVE = 0.01   # improve best bid/ask by 1c if needed to be marketable
LIMIT_TIMEOUT = 0.6    # seconds to wait before fallback to market


# =========================
# ----- API WRAPPERS -------
# =========================
session = requests.Session()
session.headers.update(API_KEY)

def _get(path: str, params: Dict[str, Any] = None) -> Any:
    r = session.get(f"{BASE}{path}", params=params or {})
    r.raise_for_status()
    return r.json()

def _post(path: str, params: Dict[str, Any] = None) -> Any:
    r = session.post(f"{BASE}{path}", params=params or {})
    if r.status_code >= 400:
        print(f"[WARN] POST {path} failed {r.status_code}: {r.text}")
    r.raise_for_status()
    return r.json() if r.text else {}

def _delete(path: str, params: Dict[str, Any] = None) -> Any:
    r = session.delete(f"{BASE}{path}", params=params or {})
    if r.status_code >= 400:
        print(f"[WARN] DELETE {path} failed {r.status_code}: {r.text}")
    r.raise_for_status()
    return r.json() if r.text else {}

def get_tick() -> int:
    return _get("/case")["tick"]

def get_limits() -> Dict[str, Any]:
    return _get("/limits")

def get_securities() -> List[Dict[str, Any]]:
    return _get("/securities")

def get_book(ticker: str) -> Dict[str, Any]:
    # returns dict: { 'bids':[{'price','quantity'}], 'asks':[...], ... }
    return _get("/securities/book", params={"ticker": ticker})

def get_tenders() -> List[Dict[str, Any]]:
    return _get("/tenders")

def accept_tender(tender_id: int) -> Dict[str, Any]:
    return _post(f"/tenders/{tender_id}")

def decline_tender(tender_id: int) -> Dict[str, Any]:
    return _delete(f"/tenders/{tender_id}")

def post_order(tkr: str, qty: int, action: str, order_type="LIMIT", price: Optional[float]=None) -> Optional[Dict[str, Any]]:
    """
    action: BUY/SELL
    type: LIMIT or MARKET
    """
    payload = {"ticker": tkr, "type": order_type, "quantity": int(qty), "action": action}
    if order_type == "LIMIT":
        if price is None:
            raise ValueError("Limit order requires price")
        payload["price"] = float(price)
    try:
        return _post("/orders", params=payload)
    except Exception as e:
        print("[WARN] post_order failed:", e)
        return None

def cancel_all_orders() -> None:
    try:
        _post("/commands/cancel")
    except Exception as e:
        print("[WARN] bulk cancel failed:", e)

# Converters via /leases (ETF Creation/Redemption)
def list_leases() -> List[Dict[str, Any]]:
    return _get("/leases")

def lease_asset(ticker: str, asset_type: str="CONVERTER", convert_from: List[Dict[str, Any]]=None, convert_to: List[Dict[str, Any]]=None) -> Optional[Dict[str, Any]]:
    """
    The exact payload varies by case; we construct a generic one that RIT commonly accepts.
    If your server needs different fields, adjust here. We'll log errors if it fails.
    """
    payload = {"ticker": ticker, "type": asset_type}
    if convert_from: payload["convert_from"] = convert_from
    if convert_to: payload["convert_to"] = convert_to
    try:
        return _post("/leases", params=payload)
    except Exception as e:
        print("[WARN] lease_asset failed:", e)
        return None

def use_lease(lease_id: int) -> Optional[Dict[str, Any]]:
    try:
        return _post(f"/leases/{lease_id}")
    except Exception as e:
        print("[WARN] use_lease failed:", e)
        return None

def release_lease(lease_id: int) -> Optional[Dict[str, Any]]:
    try:
        return _delete(f"/leases/{lease_id}")
    except Exception as e:
        print("[WARN] release_lease failed:", e)
        return None


# =========================
# ----- HELPERS ------------
# =========================
def find_row(secs: List[Dict[str, Any]], ticker: str) -> Optional[Dict[str, Any]]:
    for r in secs:
        if r.get("ticker") == ticker:
            return r
    return None

def estimate_spread_cad(ticker: str, fx_cad_per_usd: float, quote_ccy_is_usd: bool) -> float:
    """
    Rough spread estimate from order book (best ask - best bid); convert to CAD if needed.
    """
    try:
        book = get_book(ticker)
        best_bid = book["bids"][0]["price"] if book.get("bids") else None
        best_ask = book["asks"][0]["price"] if book.get("asks") else None
        if best_bid is None or best_ask is None:
            return 0.04  # conservative fallback
        spread = max(best_ask - best_bid, 0.0)
        if quote_ccy_is_usd:
            spread *= fx_cad_per_usd
        return spread
    except Exception:
        return 0.04

def fair_value_and_edge(secs: List[Dict[str, Any]]) -> Tuple[float, float, float, float]:
    """
    Returns:
        FV_cad       : BULL + BEAR (in CAD)
        ritc_usd     : RITC price in USD
        fx_cad_per_usd: direct FX CAD per USD
        ritc_cad     : RITC converted to CAD
    """
    bull = find_row(secs, "BULL")
    bear = find_row(secs, "BEAR")
    ritc = find_row(secs, "RITC")
    fx   = find_row(secs, "USD")

    if not all([bull, bear, ritc, fx]):
        raise RuntimeError("Missing one of BULL/BEAR/RITC/USD in /securities")

    bull_px = float(bull["last"])
    bear_px = float(bear["last"])
    ritc_usd = float(ritc["last"])
    fx_cad_per_usd = float(fx["last"])

    fv_cad = bull_px + bear_px
    ritc_cad = ritc_usd * fx_cad_per_usd
    return fv_cad, ritc_usd, fx_cad_per_usd, ritc_cad

def tender_fields(t: Dict[str, Any]) -> Tuple[int, str, float, int, str]:
    """
    Try to normalize tender object:
    Returns: (id, ticker, price, quantity, side)
    side = 'BUY' means tender lets YOU SELL to them at that price (they buy from you).
    side = 'SELL' means tender offers to SELL to you at that price (you buy from them).
    """
    tid = int(t.get("id", t.get("tender_id", -1)))
    tkr = t.get("ticker", "RITC")
    price = float(t.get("price", t.get("tender_price", 0.0)))
    qty = int(t.get("quantity", t.get("size", CONVERTER_BATCH)))
    # Guess side if not explicit:
    side = t.get("action") or t.get("side") or t.get("direction")
    if isinstance(side, str):
        side = side.upper()
    else:
        # Heuristic: many RIT tenders default to SELL (i.e., you BUY from them)
        side = "SELL"
    return tid, tkr, price, qty, side

def per_share_unwind_cost_etf(ritc_spread_cad: float) -> float:
    """
    ETF trading cost estimate per share when using marketable orders:
    half-spread + market fee; if our limit fills passively, rebate reduces cost.
    We'll be conservative and assume half-spread + 0.5*FEE.
    """
    return (ritc_spread_cad / 2.0) + (FEE_MARKET_PER_SHARE * 0.5)

def should_use_converter(ritc_spread_cad: float) -> bool:
    """
    Converter costs 0.15 CAD per share. If our expected ETF unwind cost per share is
    greater than converter cost, prefer converter path.
    """
    return per_share_unwind_cost_etf(ritc_spread_cad) > CONVERTER_COST_PER_SHARE

def place_sliced_orders(ticker: str, total_qty: int, action: str, price_hint: Optional[float], quote_is_usd: bool, fx: float) -> None:
    """
    Slice into <= MAX_ORDER chunks. Try limit-first; fallback to market.
    price_hint is in the ticker's native currency.
    """
    remaining = abs(int(total_qty))
    side = action.upper()
    while remaining > 0:
        clip = min(remaining, MAX_ORDER)
        px = None
        typ = "MARKET"

        if USE_LIMIT_FIRST and price_hint is not None:
            # Nudge to be marketable
            px = price_hint + (LIMIT_IMPROVE if side == "BUY" else -LIMIT_IMPROVE)
            typ = "LIMIT"

        ord_resp = post_order(ticker, clip, side, order_type=typ, price=px)
        if ord_resp is None:
            # Try market as fallback if limit failed
            if typ == "LIMIT":
                time.sleep(LIMIT_TIMEOUT)
                ord_resp = post_order(ticker, clip, side, order_type="MARKET")
                if ord_resp is None:
                    print(f"[WARN] Order failed for {ticker} {side} {clip}. Aborting slice.")
                    break
            else:
                print(f"[WARN] Market order failed for {ticker} {side} {clip}. Aborting slice.")
                break

        remaining -= clip

def try_convert(direction: str) -> bool:
    """
    Attempt to use converter via /leases.
    direction: 'REDEEM' (ETF->stocks) or 'CREATE' (stocks->ETF)
    """
    try:
        # In some RIT configs, you first lease an asset with ticker 'RITC' and type 'CONVERTER'
        leased = lease_asset("RITC", asset_type="CONVERTER")
        if not leased or "id" not in leased:
            print("[WARN] Converter lease failed (payload may differ in your server).")
            return False
        lid = leased["id"]
        used = use_lease(lid)
        if not used:
            print("[WARN] Converter use failed.")
            release_lease(lid)
            return False
        release_lease(lid)
        print(f"[INFO] Converter {direction} invoked.")
        return True
    except Exception as e:
        print("[WARN] Converter path error:", e)
        return False

# =========================
# ----- CORE LOGIC --------
# =========================
def evaluate_and_maybe_accept_tender(t: Dict[str, Any], secs: List[Dict[str, Any]]) -> bool:
    """
    Decide accept/reject, and accept if profitable.
    Returns True if accepted.
    """
    fv_cad, ritc_usd, fx_cad_per_usd, ritc_cad = fair_value_and_edge(secs)
    ritc_spread_cad = estimate_spread_cad("RITC", fx_cad_per_usd, quote_ccy_is_usd=True) if BOOK_LOOK else 0.04

    tid, tkr, price_usd, qty, side = tender_fields(t)
    if tkr != "RITC":
        # Case is about RITC tenders; ignore others
        return False

    tender_cad = price_usd * fx_cad_per_usd
    # Compute edge per share (CAD):
    if side == "SELL":
        # Tender sells ETF to you at tender_cad -> you BUY low, then unwind by SELLING or REDEEMING
        edge = fv_cad - tender_cad
        unwind_cost = min(per_share_unwind_cost_etf(ritc_spread_cad), CONVERTER_COST_PER_SHARE)
    else:
        # side == "BUY": Tender buys ETF from you at tender_cad -> you SELL high, then cover by BUYING or CREATING
        edge = tender_cad - fv_cad
        unwind_cost = min(per_share_unwind_cost_etf(ritc_spread_cad), CONVERTER_COST_PER_SHARE)

    if edge < 0:
        # negative edge, definitely reject
        decline_tender(tid)
        print(f"[TENDER] REJECT id={tid} side={side} qty={qty} edge={edge:.3f} (CAD/sh)")
        return False

    # Require cushion to cover costs + buffer
    min_needed = max(MIN_EDGE_TO_CONSIDER, unwind_cost + SAFETY_BUFFER)

    if edge >= min_needed:
        try:
            accept_tender(tid)
            print(f"[TENDER] ACCEPT id={tid} side={side} qty={qty} edge={edge:.3f} >= {min_needed:.3f} (CAD/sh)")
            return True
        except Exception as e:
            print(f"[TENDER] Accept failed id={tid}: {e}")
            return False
    else:
        decline_tender(tid)
        print(f"[TENDER] REJECT id={tid} side={side} qty={qty} edge={edge:.3f} < {min_needed:.3f}")
        return False

def positions_by_ticker(secs: List[Dict[str, Any]]) -> Dict[str, int]:
    return {r["ticker"]: int(r.get("position", 0)) for r in secs}

def mid_price(row: Dict[str, Any]) -> float:
    bid = row.get("bid")
    ask = row.get("ask")
    last = float(row.get("last", 0.0))
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return 0.5 * (float(bid) + float(ask))
    return last

def unwind_inventory(secs: List[Dict[str, Any]]) -> None:
    """
    If we’re long/short RITC after a tender, unwind profitably.
    Use ETF orderbook when cheap; otherwise use converters.
    """
    fv_cad, ritc_usd, fx, ritc_cad = fair_value_and_edge(secs)
    ritc_row = find_row(secs, "RITC")
    if not ritc_row:
        return

    pos = int(ritc_row.get("position", 0))
    if pos == 0:
        return

    # Determine path
    spread_cad = estimate_spread_cad("RITC", fx, quote_ccy_is_usd=True) if BOOK_LOOK else 0.04
    prefer_converter = should_use_converter(spread_cad)

    # Price hints
    book = {}
    try:
        book = get_book("RITC")
    except Exception:
        pass
    best_bid = book.get("bids", [{}])[0].get("price")
    best_ask = book.get("asks", [{}])[0].get("price")
    hint_price = None
    side = None

    if pos > 0:
        # We are LONG RITC → need to SELL
        side = "SELL"
        hint_price = best_bid if best_bid is not None else ritc_usd
    else:
        # We are SHORT RITC → need to BUY
        side = "BUY"
        hint_price = best_ask if best_ask is not None else ritc_usd

    if prefer_converter:
        # Try to convert in 10k blocks
        todo = abs(pos)
        while todo >= CONVERTER_BATCH:
            ok = try_convert("REDEEM" if pos > 0 else "CREATE")
            if not ok:
                break
            # Converter adjusts positions in /securities; refresh
            secs = get_securities()
            ritc_row = find_row(secs, "RITC")
            pos = int(ritc_row.get("position", 0))
            todo = abs(pos)

        # Residual position → use orders
        if pos != 0:
            place_sliced_orders("RITC", abs(pos), "SELL" if pos > 0 else "BUY", hint_price, True, fx)
    else:
        place_sliced_orders("RITC", abs(pos), side, hint_price, True, fx)

def arb_pair_trade_if_edge(secs: List[Dict[str, Any]]) -> None:
    """
    Continuous ETF vs basket arbitrage (independent of tenders), with tight safety control.
    """
    fv_cad, ritc_usd, fx, ritc_cad = fair_value_and_edge(secs)
    mispricing = ritc_cad - fv_cad  # >0: ETF rich; <0: ETF cheap
    spread_cad = estimate_spread_cad("RITC", fx, True) if BOOK_LOOK else 0.04
    cost = min(per_share_unwind_cost_etf(spread_cad), CONVERTER_COST_PER_SHARE) + SAFETY_BUFFER

    # Require decent edge
    if abs(mispricing) < max(MIN_EDGE_TO_CONSIDER, cost):
        return

    # Decide trade direction and size (very conservative; you can size up)
    size = MAX_ORDER  # clip trade
    if mispricing > 0:
        # ETF overpriced: SELL RITC, BUY basket (to be more robust, you can use converter create after)
        place_sliced_orders("RITC", size, "SELL", ritc_usd, True, fx)
        # Hedge via stocks if allowed (two buys); here we keep it minimal because of fees:
        place_sliced_orders("BULL", size, "BUY", find_row(secs, "BULL")["bid"], False, fx)
        place_sliced_orders("BEAR", size, "BUY", find_row(secs, "BEAR")["bid"], False, fx)
    else:
        # ETF underpriced: BUY RITC, SELL basket
        place_sliced_orders("RITC", size, "BUY", ritc_usd, True, fx)
        place_sliced_orders("BULL", size, "SELL", find_row(secs, "BULL")["ask"], False, fx)
        place_sliced_orders("BEAR", size, "SELL", find_row(secs, "BEAR")["ask"], False, fx)

def main():
    # Quick sanity of API key
    try:
        _get("/trader")
    except Exception as e:
        print("ERROR: API key/connection failed. Set RIT_API_KEY env var or edit script.")
        print(e)
        sys.exit(1)

    print("ETF Arbitrage Bot starting…")
    last_report = 0
    while True:
        try:
            tick = get_tick()
            if tick >= TICK_LIMIT:
                print("Heat ended (tick >= 300). Exiting.")
                break

            secs = get_securities()

            # 1) Check tenders and accept profitable ones
            tenders = []
            try:
                tenders = get_tenders()
            except Exception:
                pass

            for t in tenders:
                accepted = evaluate_and_maybe_accept_tender(t, secs)
                if accepted:
                    # After accept, refresh state and unwind
                    secs = get_securities()
                    unwind_inventory(secs)

            # 2) Opportunistic ETF-basket arbitrage
            arb_pair_trade_if_edge(secs)

            # 3) Periodic status print
            if tick - last_report >= 10:
                fv_cad, ritc_usd, fx, ritc_cad = fair_value_and_edge(secs)
                print(f"[t={tick}] USD={fx:.4f} RITC={ritc_usd:.4f} ({ritc_cad:.4f} CAD)  FV={fv_cad:.4f}  mis={ritc_cad - fv_cad:.4f}")
                last_report = tick

            time.sleep(POLL_SLEEP)

        except KeyboardInterrupt:
            print("Interrupted by user.")
            break
        except Exception as e:
            print("[ERROR] Main loop exception:", e)
            traceback.print_exc()
            time.sleep(0.5)

    # Cleanup
    try:
        cancel_all_orders()
    except Exception:
        pass

if __name__ == "__main__":
    main()
