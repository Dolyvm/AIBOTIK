"""Platega payment API client."""
from typing import Any

import httpx

from shared.config import PLATEGA_BASE_URL, PLATEGA_MERCHANT_ID, PLATEGA_SECRET


class PlategaConfigurationError(RuntimeError):
    pass


class PlategaAPIError(RuntimeError):
    pass


class PlategaClient:
    def __init__(
        self,
        merchant_id: str | None = None,
        secret: str | None = None,
        base_url: str | None = None,
    ):
        self.merchant_id = merchant_id or PLATEGA_MERCHANT_ID
        self.secret = secret or PLATEGA_SECRET
        self.base_url = (base_url or PLATEGA_BASE_URL).rstrip("/") + "/"

        if not self.merchant_id or not self.secret:
            raise PlategaConfigurationError("Platega credentials are not configured")

    def _headers(self) -> dict[str, str]:
        return {
            "X-MerchantId": self.merchant_id,
            "X-Secret": self.secret,
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path.lstrip('/')}"

    async def create_payment_link(
        self,
        *,
        amount_rub: int,
        description: str,
        return_url: str,
        failed_url: str,
        payload: str,
    ) -> dict[str, Any]:
        body = {
            "paymentDetails": {
                "amount": amount_rub,
                "currency": "RUB",
            },
            "description": description,
            "return": return_url,
            "failedUrl": failed_url,
            "payload": payload,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._url("/v2/transaction/process"),
                headers=self._headers(),
                json=body,
            )

        if response.status_code >= 400:
            raise PlategaAPIError(f"Platega create transaction failed: {response.status_code}")

        data = response.json()
        payment_url = data.get("url") or data.get("redirect")
        transaction_id = data.get("transactionId")
        if not payment_url or not transaction_id:
            raise PlategaAPIError("Platega create transaction response is incomplete")
        return data

    async def get_transaction(self, transaction_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                self._url(f"/transaction/{transaction_id}"),
                headers=self._headers(),
            )

        if response.status_code >= 400:
            raise PlategaAPIError(f"Platega transaction lookup failed: {response.status_code}")
        return response.json()
