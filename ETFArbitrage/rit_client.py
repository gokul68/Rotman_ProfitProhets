# rit_client.py
import os
import requests
from typing import Any, Dict, Optional, List
from config import API_KEY, BASE_URL

class RITError(Exception):
    pass

class RITClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key  = api_key or os.environ.get("RIT_API_KEY", API_KEY)
        self.base_url = base_url or os.environ.get("RIT_BASE", BASE_URL)
        if not self.api_key or self.api_key == "YOUR_API_KEY_HERE":
            raise RITError("Missing API key. Set API_KEY in config.py or env var RIT_API_KEY.")

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        headers = kwargs.pop("headers", {})
        headers["X-API-Key"] = self.api_key
        url = f"{self.base_url}{endpoint}"
        resp = requests.request(method, url, headers=headers, **kwargs)
        if resp.status_code != 200:
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            raise RITError(f"HTTP {resp.status_code}: {err}")
        return resp.json() if resp.text else {}

    # ---- Market / static ----
    def get_limits(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/limits")

    def get_securities(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        if ticker:
            return self._request("GET", "/securities", params={"ticker": ticker})
        return self._request("GET", "/securities")

    def get_security_book(self, ticker: str) -> Dict[str, Any]:
        return self._request("GET", "/securities/book", params={"ticker": ticker})

    # ---- Orders ----
    # IMPORTANT: RIT likes params (query/form style). Using JSON can cause 400s.
    def post_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/orders", params=payload)

    def cancel_all(self) -> Dict[str, Any]:
        return self._request("POST", "/commands/cancel")

    # ---- Tenders ----
    def get_tenders(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/tenders")

    def accept_tender(self, tender_id: int) -> Dict[str, Any]:
        return self._request("POST", f"/tenders/{tender_id}")

    def decline_tender(self, tender_id: int) -> Dict[str, Any]:
        return self._request("DELETE", f"/tenders/{tender_id}")

    # ---- Converters / Leases ----
    def get_leases(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/leases")

    def use_converter(self, converter_type: str) -> Dict[str, Any]:
        """
        converter_type: "ETF-Redemption" or "ETF-Creation"
        Different case configs accept different payloads. We'll try a few forms.
        """
        # 1) Try simple POST /leases with type
        try:
            return self._request("POST", "/leases", json={"type": converter_type})
        except RITError:
            pass
        # 2) Try with params (form style)
        try:
            return self._request("POST", "/leases", params={"type": converter_type})
        except RITError:
            pass
        # 3) Try using the lease id (if listed)
        try:
            leases = self.get_leases()
            match = next((l for l in leases if l.get("ticker") == converter_type or l.get("type") == converter_type), None)
            if match:
                return self._request("POST", f"/leases/{match['id']}")
        except Exception:
            pass
        return {"success": False, "error": f"Could not use converter {converter_type}"}
