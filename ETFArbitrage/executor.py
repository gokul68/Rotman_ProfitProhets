# executor.py
import time
import logging
from typing import Optional, Dict, List
from rit_client import RITClient
from config import DEFAULT_SLICE_SIZE, MAX_ORDER_SIZE, USE_PASSIVE_DEFAULT

class Executor:
    def __init__(self, client: RITClient):
        self.client = client

    def _place_order(self, ticker: str, action: str, qty: int, order_type: str = "MARKET",
                     price: Optional[float] = None) -> Dict:
        payload = {"ticker": ticker, "type": order_type, "quantity": int(qty), "action": action.upper()}
        if order_type == "LIMIT":
            if price is None:
                raise ValueError("Limit order needs price")
            payload["price"] = round(float(price), 2)
        logging.debug(f"POST /orders params={payload}")
        return self.client.post_order(payload)

    def slice_and_execute(self, ticker: str, action: str, qty: int,
                          side_book: Optional[Dict] = None,
                          aggressive: bool = False) -> List[Dict]:
        """
        Slices into <= DEFAULT_SLICE_SIZE chunks.
        If passive and we have a book, place at NBBO (rebate); otherwise MARKET.
        """
        results: List[Dict] = []
        remaining = abs(int(qty))
        side = action.upper()

        while remaining > 0:
            clip = min(DEFAULT_SLICE_SIZE, remaining, MAX_ORDER_SIZE)
            order_type = "MARKET"
            px = None

            if not aggressive and USE_PASSIVE_DEFAULT and side_book:
                bids = side_book.get("bids", [])
                asks = side_book.get("asks", [])
                best_bid = bids[0]["price"] if bids else None
                best_ask = asks[0]["price"] if asks else None
                if side == "BUY" and best_ask is not None:
                    order_type, px = "LIMIT", best_ask
                elif side == "SELL" and best_bid is not None:
                    order_type, px = "LIMIT", best_bid

            try:
                res = self._place_order(ticker, side, clip, order_type, price=px)
                results.append(res)
            except Exception as e:
                logging.error(f"Order failed {ticker} {side} {clip}: {e}")
                break

            remaining -= clip
            # tiny pause to avoid hammering
            time.sleep(0.05)

        return results

    # ----- Converters -----
    def use_converter(self, converter_type: str):
        logging.info(f"Using converter: {converter_type}")
        return self.client.use_converter(converter_type)
