import os
import time
import httpx
from typing import Optional

class CBPAuthManager:
    def __init__(self):
        self.client_id = os.getenv("CBP_ACE_CLIENT_ID")
        self.client_secret = os.getenv("CBP_ACE_CLIENT_SECRET")
        self.token_url = os.getenv("CBP_ACE_TOKEN_URL")
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def get_valid_token(self) -> str:
        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()
            data = response.json()
            
            self._access_token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in
            return self._access_token

cbp_auth = CBPAuthManager()