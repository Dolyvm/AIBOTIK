import httpx
import logging
from typing import Optional

from shared.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_TOP_P,
    LLM_REPETITION_PENALTY,
)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMClient:
    MAX_RETRIES = 5
    RETRY_DELAY = 2.0

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or OPENROUTER_API_KEY
        self.model = model or LLM_MODEL
        self.base_url = OPENROUTER_BASE_URL
        
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY не установлен!")

    async def generate(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 300,
        temperature: float = None,
    ) -> str:
        temperature = temperature if temperature is not None else LLM_TEMPERATURE
        
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        payload = {
            "model": self.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": LLM_TOP_P,
            "repetition_penalty": LLM_REPETITION_PENALTY,
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        last_error = None
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.debug(f"LLM запрос (попытка {attempt}/{self.MAX_RETRIES}): model={self.model}")
                
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.post(
                        self.base_url,
                        json=payload,
                        headers=headers,
                    )
                
                if response.status_code == 429:
                    logger.warning(f"Rate limit (429), попытка {attempt}/{self.MAX_RETRIES}")
                    if attempt < self.MAX_RETRIES:
                        import asyncio
                        await asyncio.sleep(self.RETRY_DELAY * attempt)  
                        continue
                    raise LLMRateLimitError("Превышен лимит запросов к API")
                
                if response.status_code >= 500:
                    logger.warning(f"Серверная ошибка ({response.status_code}), попытка {attempt}/{self.MAX_RETRIES}")
                    if attempt < self.MAX_RETRIES:
                        import asyncio
                        await asyncio.sleep(self.RETRY_DELAY)
                        continue
                    response.raise_for_status()
                
                if response.status_code >= 400:
                    error_text = response.text[:500]
                    logger.error(f"Ошибка API ({response.status_code}): {error_text}")
                    raise LLMError(f"Ошибка API: {response.status_code}")
                
                data = response.json()

                if "choices" not in data or len(data["choices"]) == 0:
                    logger.error(f"Неожиданный формат ответа: {data}")
                    raise LLMError("Неожиданный формат ответа от API")
                
                content = data["choices"][0].get("message", {}).get("content", "")
                
                if not content:
                    logger.warning("Пустой ответ от LLM")
                    return ""
                
                logger.debug(f"LLM ответ получен: {len(content)} символов")
                return content
                
            except httpx.TimeoutException as e:
                logger.warning(f"Таймаут запроса, попытка {attempt}/{self.MAX_RETRIES}: {e}")
                last_error = LLMTimeoutError(f"Таймаут запроса: {e}")
                if attempt < self.MAX_RETRIES:
                    import asyncio
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
                    
            except httpx.RequestError as e:
                logger.error(f"Ошибка сети: {e}")
                last_error = LLMError(f"Ошибка сети: {e}")
                if attempt < self.MAX_RETRIES:
                    import asyncio
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
                    
            except (KeyError, IndexError, TypeError) as e:
                logger.error(f"Ошибка парсинга ответа: {e}")
                raise LLMError(f"Ошибка парсинга ответа: {e}")
        
        if last_error:
            raise last_error
        raise LLMError("Не удалось получить ответ от LLM")