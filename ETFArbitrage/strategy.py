# strategy.py
from typing import Dict, Tuple
from rit_client import RITClient
from config import ETF_TICKER, BULL_TICKER, BEAR_TICKER, FX_TICKER, ACCEPTANCE_THRESHOLD, CONVERTER_COST_PER_SHARE

class StrategyEngine:
    def __init__(self, client: RITClient):
        self.client = client

    def fetch_quotes(self) -> Dict[str, Dict]:
        """
        Returns latest quote dicts from /securities for ETF, BULL, BEAR, FX.
        """
        secs = {}
        for t in (ETF_TICKER, BULL_TICKER, BEAR_TICKER, FX_TICKER):
            items = self.client.get_securities(ticker=t)
            if items and isinstance(items, list) and len(items) >= 1:
                secs[t] = items[0]
            else:
                secs[t] = {}
        return secs

    def compute_fair_etf_usd(self, quotes: Dict[str, Dict]) -> Tuple[float, float]:
        """
        Compute fair ETF price in USD and CAD:
        ETF fair (CAD) = price(BULL,CAD) + price(BEAR,CAD)
        ETF fair (USD) = ETF_fair_CAD / FX_rate (CAD per 1 USD)
        Returns: (fair_usd, fair_cad)
        """
        bull = quotes.get(BULL_TICKER, {})
        bear = quotes.get(BEAR_TICKER, {})
        fx = quotes.get(FX_TICKER, {})
        bull_price = bull.get("last") or bull.get("ask") or bull.get("bid") or 0.0
        bear_price = bear.get("last") or bear.get("ask") or bear.get("bid") or 0.0
        fx_rate = fx.get("last") or fx.get("ask") or fx.get("bid") or 1.0
        fair_cad = (bull_price or 0.0) + (bear_price or 0.0)
        if fx_rate == 0:
            fair_usd = float("inf")
        else:
            fair_usd = fair_cad / fx_rate
        return fair_usd, fair_cad

    def evaluate_tender(self, tender: Dict, quotes: Dict[str, Dict]) -> Dict:
        """
        Given a tender dictionary and latest quotes, decide whether to accept.
        Returns an action dict: {"decision": "ACCEPT"|"DECLINE"|"HOLD", "reason": str, "expected_profit_per_share": float}
        """
        tender_price = tender.get("price")
        tender_qty = tender.get("quantity")
        fair_usd, fair_cad = self.compute_fair_etf_usd(quotes)
        # Convert fair_usd to USD price per ETF
        # compute per-share expected arbitrage:
        # If tender buy (they offer to buy ETF from you) vs you long? The tender payload typically indicates side; here we assume it's an offer to buy ETF at tender_price
        # We'll assume rational: if tender_price < fair_usd -> buying ETF low (you buy) OR if > fair_usd -> selling ETF high (you tender)
        # To be generic, compute mispricing magnitude:
        mispricing = tender_price - fair_usd
        # expected profit per share ignoring slippage: abs(mispricing) - fees - converter_cost
        # trading fees: assume market order cost = 0.02 per share, limit rebate = -0.01 (you earn 0.01). Conservative: assume 0.02
        trading_fee = 0.02
        converter_cost = CONVERTER_COST_PER_SHARE  # $0.15 per share approx
        expected_profit = abs(mispricing) - trading_fee - converter_cost
        decision = "HOLD"
        reason = "No actionable arbitrage"
        # require a relative threshold (ACCEPTANCE_THRESHOLD) times fair price
        rel = abs(mispricing) / max(1e-9, fair_usd)
        if expected_profit > 0 and rel >= ACCEPTANCE_THRESHOLD:
            decision = "ACCEPT"
            reason = f"Expected profit {expected_profit:.4f} > 0 and rel {rel:.4%} >= {ACCEPTANCE_THRESHOLD:.2%}"
        elif expected_profit > 0:
            decision = "HOLD"
            reason = f"Possible profit {expected_profit:.4f} but below relative threshold"
        else:
            decision = "DECLINE"
            reason = f"Negative expected profit {expected_profit:.4f}"
        return {
            "decision": decision,
            "reason": reason,
            "expected_profit_per_share": expected_profit,
            "fair_usd": fair_usd,
            "fair_cad": fair_cad
        }
