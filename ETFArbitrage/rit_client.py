# rit_client.py
import os
import time
import requests
from typing import Any, Dict, List, Optional

class RITError(Exception): pass
class RITAuthError(RITError): pass
class RITRateLimit(RITError): pass

class RITClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = "http://localhost:9999/v1", timeout=10, max_retries=4):
        self.api_key = api_key or os.environ.get("RIT_API_KEY")
        if not self.api_key:
            raise ValueError("API key required (env RIT_API_KEY or pass to constructor)")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.s = requests.Session()
        self.s.headers.update({"X-API-Key": self.api_key, "Accept": "application/json", "User-Agent":"rit-trader/1.0"})

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = self._url(path)
        attempt = 0
        while True:
            attempt += 1
            resp = self.s.request(method, url, timeout=self.timeout, **kwargs)
            if 200 <= resp.status_code < 300:
                if resp.text:
                    try:
                        return resp.json()
                    except Exception:
                        return resp.text
                return None
            if resp.status_code == 401:
                raise RITAuthError("401 Unauthorized")
            if resp.status_code == 429:
                # rate limit
                wait = None
                if "Retry-After" in resp.headers:
                    try:
                        wait = int(resp.headers["Retry-After"])
                    except:
                        pass
                if wait is None:
                    try:
                        body = resp.json()
                        wait = int(body.get("wait", 1))
                    except:
                        wait = 1
                if attempt > self.max_retries:
                    raise RITRateLimit(f"429 rate-limited; exhausted retries")
                time.sleep(wait)
                continue
            if 500 <= resp.status_code < 600:
                if attempt > self.max_retries:
                    raise RITError(f"Server error {resp.status_code}: {resp.text}")
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            # other errors
            try:
                err = resp.json()
            except:
                err = resp.text
            raise RITError(f"HTTP {resp.status_code}: {err}")

    # convenience endpoints used by strategy/trader
    def get_case(self) -> Dict: return self._request("GET", "/case")
    def get_securities(self, ticker: Optional[str] = None) -> List[Dict]:
        params = {"ticker": ticker} if ticker else None
        return self._request("GET", "/securities", params=params)
    def get_security_book(self, ticker: str) -> Dict:
        return self._request("GET", "/securities/book", params={"ticker": ticker})
    def get_tenders(self) -> List[Dict]:
        return self._request("GET", "/tenders")
    def accept_tender(self, tender_id: int) -> Dict:
        return self._request("POST", f"/tenders/{tender_id}")
    def decline_tender(self, tender_id: int) -> Dict:
        return self._request("DELETE", f"/tenders/{tender_id}")
    def get_orders(self) -> List[Dict]:
        return self._request("GET", "/orders")
    def post_order(self, payload: Dict) -> Dict:
        return self._request("POST", "/orders", json=payload)
    def get_order(self, order_id: int) -> Dict:
        return self._request("GET", f"/orders/{order_id}")
    def cancel_order(self, order_id: int) -> Dict:
        return self._request("DELETE", f"/orders/{order_id}")
    def get_leases(self) -> Dict:
        return self._request("GET", "/leases")
    def use_lease(self, lease_id: int, payload: Dict) -> Dict:
        return self._request("POST", f"/leases/{lease_id}", json=payload)
    def get_limits(self) -> Dict:
        return self._request("GET", "/limits")
    
