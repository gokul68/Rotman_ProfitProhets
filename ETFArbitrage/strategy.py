# strategy.py

from typing import Dict, Tuple
from rit_client import RITClient
from config import (
    ETF_TICKER, BULL_TICKER, BEAR_TICKER, FX_TICKER,
    CONVERTER_COST_PER_SHARE, MIN_ABS_EDGE, ABS_BUFFER,
    BOOK_FALLBACK_SPREAD_CAD, MIN_EDGE_TO_CONSIDER,
)


class StrategyEngine:
    def __init__(self, client: RITClient):
        self.client = client

    def check_spot_arbitrage(self, quotes: Dict[str, Dict]) -> Dict:
        """
        Look for ETF vs Basket mispricing in the live market (no tender).
        If ETF is too cheap -> BUY ETF, SELL basket.
        If ETF is too rich -> SELL ETF, BUY basket.
        Returns a dict with decision and details.
        """
        fair_cad, fair_usd, ritc_usd, fx_rate = self.compute_fair(quotes)

        edge_usd = fair_usd - ritc_usd   # +ve means ETF undervalued
        edge_cad = edge_usd * fx_rate

        spread_cad = self._book_spread_cad(fx_rate)
        unwind_cost = min(self._per_share_unwind_cost(spread_cad), CONVERTER_COST_PER_SHARE)
        min_needed = max(MIN_ABS_EDGE, unwind_cost + ABS_BUFFER)

        decision = "HOLD"
        reason = f"edge {edge_cad:.3f} < min_needed {min_needed:.3f}"

        if edge_cad > min_needed:
            decision = "BUY_ETF_SELL_BASKET"
            reason = f"ETF cheap: fair {fair_usd:.2f}, mkt {ritc_usd:.2f}, edge {edge_cad:.3f} CAD"
        elif -edge_cad > min_needed:  # ETF too rich
            decision = "SELL_ETF_BUY_BASKET"
            reason = f"ETF rich: fair {fair_usd:.2f}, mkt {ritc_usd:.2f}, edge {edge_cad:.3f} CAD"

        return {
            "decision": decision,
            "reason": reason,
            "edge_cad": edge_cad,
            "fair_usd": fair_usd,
            "ritc_usd": ritc_usd,
            "fx_rate": fx_rate,
        }


    def fetch_quotes(self) -> Dict[str, Dict]:
        """Fetch last/quote info for ETF, BULL, BEAR, FX"""
        quotes = {}
        for t in (ETF_TICKER, BULL_TICKER, BEAR_TICKER, FX_TICKER):
            items = self.client.get_securities(ticker=t)
            quotes[t] = items[0] if items else {}
        return quotes

    def compute_fair(self, quotes: Dict[str, Dict]) -> Tuple[float, float, float, float]:
        """
        Compute fair ETF prices.
        Returns: (fair_cad, fair_usd, ritc_usd, fx_rate)
        """
        bull = quotes.get(BULL_TICKER, {})
        bear = quotes.get(BEAR_TICKER, {})
        fx   = quotes.get(FX_TICKER, {})
        etf  = quotes.get(ETF_TICKER, {})

        bull_px = float(bull.get("last") or bull.get("ask") or bull.get("bid") or 0.0)
        bear_px = float(bear.get("last") or bear.get("ask") or bear.get("bid") or 0.0)
        fx_rate = float(fx.get("last")   or fx.get("ask")  or fx.get("bid")  or 1.0)
        ritc_usd = float(etf.get("last") or etf.get("ask") or etf.get("bid") or 0.0)

        fair_cad = bull_px + bear_px
        fair_usd = fair_cad / fx_rate if fx_rate else float("inf")
        return fair_cad, fair_usd, ritc_usd, fx_rate

    def _book_spread_cad(self, fx_rate: float) -> float:
        """Estimate ETF market spread in CAD terms"""
        try:
            book = self.client.get_security_book(ETF_TICKER)
            best_bid = book.get("bids", [{}])[0].get("price")
            best_ask = book.get("asks", [{}])[0].get("price")
            if best_bid is None or best_ask is None:
                return BOOK_FALLBACK_SPREAD_CAD
            return max(best_ask - best_bid, 0.0) * fx_rate
        except Exception:
            return BOOK_FALLBACK_SPREAD_CAD

    def _per_share_unwind_cost(self, spread_cad: float) -> float:
        """Estimate cost of unwinding ETF in CAD"""
        return (spread_cad / 2.0) + 0.01

    def evaluate_tender(self, tender: Dict, quotes: Dict[str, Dict]) -> Dict:
        """
        Decide ACCEPT/DECLINE using arbitrage logic.
        Only accept if we buy ETF cheap or sell ETF rich.
        """
        fair_cad, fair_usd, _, fx_rate = self.compute_fair(quotes)

        tender_price_usd = float(tender.get("price"))
        qty = int(tender.get("quantity", 0))
        side = (tender.get("action") or "SELL").upper()
        tender_cad = tender_price_usd * fx_rate

        # --- Edge calculation in USD terms ---
        if side == "SELL":  # they sell ETF → we BUY
            edge_usd = fair_usd - tender_price_usd
        else:  # they buy ETF → we SELL
            edge_usd = tender_price_usd - fair_usd

        # Convert edge to CAD for cost comparison
        edge_cad = edge_usd * fx_rate

        # --- Costs ---
        spread_cad = self._book_spread_cad(fx_rate)
        unwind_cost = min(self._per_share_unwind_cost(spread_cad), CONVERTER_COST_PER_SHARE)
        min_needed = max(MIN_ABS_EDGE, unwind_cost + ABS_BUFFER)

        # --- Decision ---
        if edge_cad >= min_needed and edge_cad >= MIN_EDGE_TO_CONSIDER:
            decision = "ACCEPT"
            reason = f"edge {edge_cad:.3f} >= min_needed {min_needed:.3f}, good arb"
        elif edge_cad <= 0:
            decision = "DECLINE"
            reason = f"edge negative (bad trade): tender={tender_price_usd:.2f}, fair={fair_usd:.2f}"
        else:
            decision = "DECLINE"
            reason = f"edge {edge_cad:.3f} < min_needed {min_needed:.3f} (too small)"

        return {
            "decision": decision,
            "reason": reason,
            "edge_per_share_cad": edge_cad,
            "unwind_cost_cad": unwind_cost,
            "min_needed_cad": min_needed,
            "side": side,
            "qty": qty,
            "fair_cad": fair_cad,
            "fair_usd": fair_usd,
            "tender_usd": tender_price_usd,
            "tender_cad": tender_cad,
        }
