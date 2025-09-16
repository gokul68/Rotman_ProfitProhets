# rit_api.py - wrappers around RIT REST Client API endpoints
import requests
from typing import Optional, Dict, Any, List
from config import API_KEY, BASE

session = requests.Session()
session.headers.update(API_KEY)

def get_case() -> Dict[str, Any]:
    r = session.get(f'{BASE}/case')
    r.raise_for_status()
    return r.json()

def get_tick() -> int:
    return get_case()['tick']

def get_securities() -> List[Dict[str, Any]]:
    r = session.get(f'{BASE}/securities')
    r.raise_for_status()
    return r.json()

def get_news() -> List[Dict[str, Any]]:
    r = session.get(f'{BASE}/news')
    r.raise_for_status()
    return r.json()

def get_limits() -> Dict[str, Any]:
    r = session.get(f'{BASE}/limits')
    r.raise_for_status()
    return r.json()

def post_order(ticker: str, quantity: int, action: str, order_type: str='MARKET', price: Optional[float]=None) -> Optional[Dict[str, Any]]:
    payload = {
        # "order_id": 123,
        # "period": 1,
        # "tick": 10,
        # "trader_id": "LSTM-2",
        # "ticker": ticker,
        # "type": order_type,
        # "quantity": int(quantity),
        # "action": action,
        # "price": 14.21,
        # "quantity_filled": 10,
        # "vwap": 14.21,
        # "status": "OPEN"
        "ticker": ticker,
        "type": order_type,
        "quantity": int(quantity),
        "action": action
    }
#     {
#   "order_id": 1221,
#   "period": 1,
#   "tick": 10,
#   "trader_id": "trader49",
#   "ticker": "CRZY",
#   "type": "LIMIT",
#   "quantity": 100,
#   "action": "BUY",
#   "price": 14.21,
#   "quantity_filled": 10,
#   "vwap": 14.21,
#   "status": "OPEN"
# }
    if order_type == 'LIMIT':
        if price is None:
            raise ValueError("Limit order requires price")
        payload['price'] = float(price)
    s = get_securities()
    #tickers = [d['ticker'] for d in s]
    r = session.post(f'{BASE}/orders', params=payload)
    if r.ok:
        return r.json()
    else:
        print(f"Order failed ({r.status_code}): {r.text}")
        return None

def get_orders() -> List[Dict[str, Any]]:
    r = session.get(f'{BASE}/orders')
    r.raise_for_status()
    return r.json()

def delete_order(order_id: int) -> bool:
    r = session.delete(f'{BASE}/orders/{order_id}')
    return r.ok
