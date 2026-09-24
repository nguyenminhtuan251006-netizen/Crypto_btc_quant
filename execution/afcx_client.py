"""Strict exchange transport for strategies 4 and 5 only."""
import requests
import hashlib
import hmac
import time
from urllib.parse import urlencode


class AFCXClient:
    def __init__(self, api_key, api_secret, base_url):
        self.api_secret = api_secret
        self.base_url = base_url
        self.headers = {"X-MBX-APIKEY": api_key}

    def _sign(self, params):
        signed = dict(params, timestamp=int(time.time() * 1000))
        signed["signature"] = hmac.new(self.api_secret.encode(), urlencode(signed).encode(), hashlib.sha256).hexdigest()
        return signed
    def _request(self, method, endpoint, params=None):
        signed = self._sign(params or {})
        kwargs = {"params" if method == "GET" else "data": signed}
        response = requests.request(method, self.base_url + endpoint,
                                    headers=self.headers, timeout=8, **kwargs)
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict) and int(result.get("code", 0)) < 0:
            raise RuntimeError(f"Binance {endpoint}: {result.get('code')} {result.get('msg')}")
        return result

    def get(self, endpoint, params=None):
        return self._request("GET", endpoint, params)

    def post(self, endpoint, params=None):
        return self._request("POST", endpoint, params)

    def delete(self, endpoint, params=None):
        return self._request("DELETE", endpoint, params)

    def init_account_settings(self, symbol="BTCUSDT", leverage=5):
        result = self.post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
        if int(result.get("leverage", 0)) != leverage:
            raise RuntimeError("Exchange leverage not confirmed")
        # Do not silently change margin mode or assume it succeeded.
        positions = self.get("/fapi/v2/positionRisk", {"symbol": symbol})
        if not isinstance(positions, list) or not positions:
            raise RuntimeError("Position configuration unavailable")
        if any(p.get("positionSide") != "BOTH" for p in positions):
            raise RuntimeError("AFCX requires one-way position mode")
        if any(str(p.get("marginType", "")).lower() != "isolated" for p in positions):
            self.post("/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})

    def place_market_order(self, symbol, side, qty, reduce_only=False, client_order_id=None):
        params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty,
                  "newOrderRespType": "RESULT"}
        if reduce_only:
            params["reduceOnly"] = "true"
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return self.post("/fapi/v1/order", params)
