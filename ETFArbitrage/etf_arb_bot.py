"""
rit_client.py
A lightweight Python client for the RIT Client REST API (v1.0.3).

Usage:
    client = RITClient(api_key="XXXXXXXX", base_url="http://localhost:9999/v1")
    case = client.get_case()
    securities = client.get_securities()
    orders = client.get_orders()
"""

from __future__ import annotations
import time
import typing as t
import requests
from dataclasses import dataclass, field

# -- Exceptions ----------------------------------------------------------------

class RITError(Exception):
    """Base exception for RIT client errors."""

class RITAuthError(RITError):
    """Authentication/authorization error (401)."""

class RITRateLimit(RITError):
    """Raised when a 429 is received and the client gives up after retries."""

class RITNotFound(RITError):
    """404 from the API."""

# -- Models --------------------------------------------------------------------

@dataclass
class Limit:
    name: str
    units: int

@dataclass
class Security:
    ticker: str
    type: str
    size: int
    position: int
    vwap: float
    nlv: float
    last: float
    bid: float
    bid_size: int
    ask: float
    ask_size: int
    volume: int
    unrealized: float
    realized: float
    currency: str
    total_volume: int
    limits: t.List[Limit] = field(default_factory=list)
    # plus additional optional fields...
    start_price: t.Optional[float] = None
    trading_fee: t.Optional[float] = None
    limit_order_rebate: t.Optional[float] = None
    max_trade_size: t.Optional[int] = None

    @staticmethod
    def from_dict(d: dict) -> "Security":
        limits = [Limit(name=l.get("name"), units=l.get("units")) for l in d.get("limits", [])]
        return Security(
            ticker=d.get("ticker"),
            type=d.get("type"),
            size=d.get("size", 0),
            position=d.get("position", 0),
            vwap=d.get("vwap", 0.0),
            nlv=d.get("nlv", 0.0),
            last=d.get("last", 0.0),
            bid=d.get("bid", 0.0),
            bid_size=d.get("bid_size", 0),
            ask=d.get("ask", 0.0),
            ask_size=d.get("ask_size", 0),
            volume=d.get("volume", 0),
            unrealized=d.get("unrealized", 0.0),
            realized=d.get("realized", 0.0),
            currency=d.get("currency"),
            total_volume=d.get("total_volume", 0),
            limits=limits,
            start_price=d.get("start_price"),
            trading_fee=d.get("trading_fee"),
            limit_order_rebate=d.get("limit_order_rebate"),
            max_trade_size=d.get("max_trade_size") or d.get("max_trade_size") or d.get("max_trade_size"),
        )

@dataclass
class Order:
    order_id: t.Optional[int]
    period: t.Optional[int]
    tick: t.Optional[int]
    trader_id: t.Optional[str]
    ticker: str
    type: str
    quantity: int
    action: str
    price: t.Optional[float]
    quantity_filled: int = 0
    vwap: t.Optional[float] = None
    status: t.Optional[str] = None

    @staticmethod
    def from_dict(d: dict) -> "Order":
        return Order(
            order_id=d.get("order_id"),
            period=d.get("period"),
            tick=d.get("tick"),
            trader_id=d.get("trader_id"),
            ticker=d.get("ticker"),
            type=d.get("type"),
            quantity=d.get("quantity"),
            action=d.get("action"),
            price=d.get("price"),
            quantity_filled=d.get("quantity_filled", 0),
            vwap=d.get("vwap"),
            status=d.get("status"),
        )

@dataclass
class Tender:
    id: int
    ticker: str
    price: float
    quantity: int
    # other fields as returned

    @staticmethod
    def from_dict(d: dict) -> "Tender":
        return Tender(
            id=d.get("id"),
            ticker=d.get("ticker"),
            price=d.get("price"),
            quantity=d.get("quantity")
        )

# -- Client -------------------------------------------------------------------

class RITClient:
    """
    RIT REST API client.

    Args:
        api_key: API key string (required).
        base_url: Base URL to the API, default http://localhost:9999/v1
        timeout: per-request timeout (seconds)
        max_retries: number of retries for 5xx or 429 responses
        use_header_auth: if True send API key in X-API-Key header, otherwise fallback to ?key= param.
    """
    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:9999/v1",
        timeout: int = 10,
        max_retries: int = 4,
        use_header_auth: bool = True,
        session: requests.Session | None = None,
    ):
        if not api_key:
            raise ValueError("api_key required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.use_header_auth = use_header_auth
        self.session = session or requests.Session()
        # default headers
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "rit-client/1.0.3",
        })
        if self.use_header_auth:
            self.session.headers["X-API-Key"] = self.api_key

    # -- internal helpers ----------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kwargs) -> t.Any:
        url = self._url(path)
        # if header auth isn't used, add key in query param
        params = kwargs.get("params", {}) or {}
        if not self.use_header_auth:
            params["key"] = self.api_key
        kwargs["params"] = params
        kwargs.setdefault("timeout", self.timeout)

        attempt = 0
        while True:
            attempt += 1
            resp = self.session.request(method, url, **kwargs)
            # Successful
            if 200 <= resp.status_code < 300:
                # API promises JSON
                if resp.content:
                    try:
                        return resp.json()
                    except ValueError:
                        return resp.text
                return None
            # Authentication
            if resp.status_code == 401:
                raise RITAuthError("401 Unauthorized: check API key")
            # Not found
            if resp.status_code == 404:
                raise RITNotFound(f"404 Not Found: {url}")
            # Rate limit
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
                wait = None
                if retry_after:
                    try:
                        wait = int(retry_after)
                    except Exception:
                        # try float
                        try:
                            wait = float(retry_after)
                        except Exception:
                            wait = None
                if wait is None:
                    # try to parse body 'wait' field if present
                    try:
                        body = resp.json()
                        wait = int(body.get("wait", 1))
                    except Exception:
                        wait = 1
                if attempt > self.max_retries:
                    raise RITRateLimit(f"429 Rate limited and retries exhausted after {attempt-1} attempts")
                # honor Retry-After header if present
                time.sleep(wait)
                continue
            # Server errors: exponential backoff
            if 500 <= resp.status_code < 600:
                if attempt > self.max_retries:
                    raise RITError(f"Server error {resp.status_code}: {resp.text}")
                backoff = 0.5 * (2 ** (attempt - 1))
                time.sleep(backoff)
                continue
            # Others: return error
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            raise RITError(f"HTTP {resp.status_code}: {err}")

    # -- Simple getters ------------------------------------------------------

    def get_case(self) -> dict:
        """GET /case"""
        return self._request("GET", "/case")

    def get_trader(self) -> dict:
        """GET /trader"""
        return self._request("GET", "/trader")

    def get_limits(self) -> dict:
        """GET /limits"""
        return self._request("GET", "/limits")

    def get_news(self) -> dict:
        """GET /news"""
        return self._request("GET", "/news")

    # -- Assets / Securities -------------------------------------------------

    def get_assets(self) -> dict:
        """GET /assets"""
        return self._request("GET", "/assets")

    def get_assets_history(self) -> dict:
        """GET /assets/history"""
        return self._request("GET", "/assets/history")

    def get_securities(self, ticker: str | None = None) -> t.List[Security]:
        """GET /securities
        Optional query param `ticker`.
        """
        params = {}
        if ticker:
            params["ticker"] = ticker
        data = self._request("GET", "/securities", params=params)
        return [Security.from_dict(item) for item in data]

    def get_order_book(self, ticker: str) -> dict:
        """GET /securities/book?ticker=..."""
        return self._request("GET", "/securities/book", params={"ticker": ticker})

    def get_securities_history(self, ticker: str, period: int | None = None) -> dict:
        """GET /securities/history?ticker=..."""
        params = {"ticker": ticker}
        if period is not None:
            params["period"] = period
        return self._request("GET", "/securities/history", params=params)

    def get_tas(self, ticker: str, limit: int | None = None) -> dict:
        """GET /securities/tas?ticker=..."""
        params = {"ticker": ticker}
        if limit is not None:
            params["limit"] = limit
        return self._request("GET", "/securities/tas", params=params)

    # -- Orders --------------------------------------------------------------

    def get_orders(self) -> t.List[Order]:
        """GET /orders"""
        data = self._request("GET", "/orders")
        return [Order.from_dict(d) for d in data]

    def post_order(self, ticker: str, type: str, quantity: int, action: str, price: float | None = None) -> Order:
        """
        POST /orders
        type: 'LIMIT' or 'MARKET' (as per API)
        action: 'BUY' or 'SELL'
        price: required for LIMIT orders; will be ignored for MARKET orders.
        """
        payload = {
            "ticker": ticker,
            "type": type,
            "quantity": quantity,
            "action": action,
            "price": price
        }
        data = self._request("POST", "/orders", json=payload)
        return Order.from_dict(data)

    def get_order(self, order_id: int) -> Order:
        """GET /orders/{id}"""
        data = self._request("GET", f"/orders/{order_id}")
        return Order.from_dict(data)

    def cancel_order(self, order_id: int) -> dict:
        """DELETE /orders/{id}"""
        return self._request("DELETE", f"/orders/{order_id}")

    # -- Tenders -------------------------------------------------------------

    def get_tenders(self) -> t.List[Tender]:
        """GET /tenders"""
        data = self._request("GET", "/tenders")
        return [Tender.from_dict(d) for d in data]

    def accept_tender(self, tender_id: int) -> dict:
        """POST /tenders/{id} -> Accept the tender"""
        return self._request("POST", f"/tenders/{tender_id}")

    def decline_tender(self, tender_id: int) -> dict:
        """DELETE /tenders/{id} -> Decline the tender"""
        return self._request("DELETE", f"/tenders/{tender_id}")

    # -- Leases / Converters -------------------------------------------------

    def get_leases(self) -> dict:
        """GET /leases"""
        return self._request("GET", "/leases")

    def post_lease(self, payload: dict) -> dict:
        """POST /leases"""
        return self._request("POST", "/leases", json=payload)

    def get_lease(self, lease_id: int) -> dict:
        """GET /leases/{id}"""
        return self._request("GET", f"/leases/{lease_id}")

    def use_lease(self, lease_id: int, payload: dict) -> dict:
        """POST /leases/{id}"""
        return self._request("POST", f"/leases/{lease_id}", json=payload)

    def delete_lease(self, lease_id: int) -> dict:
        """DELETE /leases/{id}"""
        return self._request("DELETE", f"/leases/{lease_id}")

    # -- Commands -----------------------------------------------------------

    def bulk_cancel(self) -> dict:
        """POST /commands/cancel"""
        return self._request("POST", "/commands/cancel")

# -- Example usage ------------------------------------------------------------

if __name__ == "__main__":
    import os
    API_KEY = os.environ.get("RIT_API_KEY", "IIFLZKL1")
    BASE = os.environ.get("RIT_BASE_URL", "http://localhost:9999/v1")

    client = RITClient(api_key=API_KEY, base_url=BASE)

    print("Case info:")
    try:
        case_info = client.get_case()
        print(case_info)
    except Exception as e:
        print("Error fetching case:", e)

    # list securities (example)
    try:
        secs = client.get_securities()
        print(f"Found {len(secs)} securities. Sample:")
        for s in secs[:5]:
            print(f" - {s.ticker} last={s.last} bid={s.bid} ask={s.ask}")
    except Exception as e:
        print("Error fetching securities:", e)

    # list tenders
    try:
        tenders = client.get_tenders()
        print("Active tenders:", [t.__dict__ for t in tenders])
    except Exception as e:
        print("Error fetching tenders:", e)
