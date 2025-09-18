# executor.py
import time
from typing import Dict
from rit_client import RITClient
from config import SLICE_SIZE, MAX_ORDER_SIZE

class Executor:
    def __init__(self, client: RITClient):
        self.client = client

    def _place_order(self, ticker: str, action: str, quantity: int, order_type: str, price=None) -> Dict:
        payload = {
            "ticker": ticker,
            "type": order_type,  # "LIMIT" or "MARKET"
            "quantity": quantity,
            "action": action,
            "price": price
        }
        return self.client.post_order(payload)

    def slice_and_execute(self, ticker: str, action: str, total_qty: int, side_book: Dict = None, aggressive=False):
        """
        Slices total_qty into SLICE_SIZE chunks and either posts LIMIT orders at current NBBO or MARKET orders if aggressive.
        Returns list of order responses.
        """
        results = []
        remaining = total_qty
        slice_size = min(SLICE_SIZE, MAX_ORDER_SIZE)
        while remaining > 0:
            q = min(slice_size, remaining)
            if aggressive:
                # use MARKET orders for speed
                res = self._place_order(ticker, action, q, "MARKET", price=None)
                results.append(res)
            else:
                # try limit at near NBBO: if selling, use bid; if buying, use ask
                book = side_book or self.client.get_security_book(ticker)
                bid = book.get("bid") or book.get("bids", [{}])[0].get("price")
                ask = book.get("ask") or book.get("asks", [{}])[0].get("price")
                if action.upper() == "SELL":
                    price = bid or ask or None
                else:
                    price = ask or bid or None
                if price is None:
                    # fallback market
                    res = self._place_order(ticker, action, q, "MARKET", price=None)
                else:
                    # place a marketable-limit by using LIMIT at NBBO (this can execute immediately as taker or rest as passive)
                    res = self._place_order(ticker, action, q, "LIMIT", price=price)
                results.append(res)
            remaining -= q
            # small pause to avoid rate limits & market impact simulation
            time.sleep(0.1)
        return results
