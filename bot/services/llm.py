import httpx
from typing import Optional


class LLMClient:
    """OpenRouter API client for LLM generation"""

    def __init__(self, api_key: str, model: str = "mistralai/mistral-small-creative"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    async def generate(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 300,
        temperature: float = 0.8
    ) -> str:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        payload = {
            "model": self.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
            "repetition_penalty": 1.15
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self.base_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
