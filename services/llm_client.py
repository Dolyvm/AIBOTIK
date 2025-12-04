"""Клиент для OpenRouter API."""

import asyncio
import logging
from typing import List, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class OpenRouterClient:
    """Асинхронный клиент для OpenRouter API."""

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        api_key: str,
        model: str,

        default_params: Optional[Dict] = None
    ):
        self.api_key = api_key
        self.model = model
        self.fallback_models = [
            "nousresearch/hermes-3-llama-3.1-405b:free",  
        ]
        self.default_params = default_params or {
            "temperature": 0.80,
            "top_p": 0.9,
            "max_tokens": 250,
            "repetition_penalty": 1.15,
            "stop": ["{{user}}:", "{{char}}:", "<USER>:", "<BOT>:"]
        }
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получает или создаёт aiohttp сессию."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/your-repo",
                    "X-Title": "Maya Telegram Bot"
                }
            )
        return self._session

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Генерирует ответ от модели.

        Args:
            messages: История сообщений [{"role": "user/assistant", "content": "..."}]
            system_prompt: Системный промпт
            **kwargs: Дополнительные параметры генерации

        Returns:
            Текст ответа модели

        Raises:
            Exception: При ошибке API
        """
        session = await self._get_session()

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        params = {**self.default_params, **kwargs}

        payload = {
            "model": self.model,
            "messages": full_messages,
            **params
        }

        logger.info(f"🤖 Sending request to OpenRouter:")
        logger.info(f"  Model: {self.model}")
        logger.info(f"  Messages count: {len(full_messages)}")
        logger.info(f"  Max tokens: {params.get('max_tokens', 'default')}")
        logger.info(f"  Temperature: {params.get('temperature', 'default')}")
        logger.debug(f"  Full payload: {payload}")

        max_retries = 5
        models_to_try = [self.model] + self.fallback_models

        for model_idx, current_model in enumerate(models_to_try):
            payload["model"] = current_model

            for attempt in range(max_retries):
                try:
                    async with session.post(
                        f"{self.BASE_URL}/chat/completions",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            choice = data["choices"][0]
                            generated_text = choice["message"]["content"]
                            finish_reason = choice.get("finish_reason", "unknown")

                            if model_idx > 0:
                                logger.warning(f"⚠️ Using fallback model: {current_model}")

                            logger.info(f"✅ Received response: {len(generated_text)} chars")
                            logger.info(f"  Finish reason: {finish_reason}")

                            if finish_reason == "length":
                                logger.warning(f"⚠️ Response was cut off due to max_tokens limit!")
                            elif finish_reason == "stop":
                                logger.info(f"  Generation stopped by stop sequence")

                            logger.debug(f"\n{'='*80}\nGENERATED RESPONSE:\n{'='*80}\n{generated_text}\n{'='*80}")
                            return generated_text

                        elif response.status == 429:
                            error_text = await response.text()
                            logger.warning(f"⚠️ Rate limit (429) from {current_model} (attempt {attempt + 1}/{max_retries})")
                            logger.debug(f"Error details: {error_text}")

                            if attempt == max_retries - 1:
                                logger.warning(f"Max retries reached for {current_model}, trying fallback...")
                                break

                            wait_time = 2 + 1
                            logger.info(f"Waiting {wait_time}s before retry...")
                            await asyncio.sleep(wait_time)
                            continue

                        else:
                            error_text = await response.text()
                            logger.error(f"OpenRouter API error: {response.status} - {error_text}")
                            raise Exception(f"OpenRouter API error: {response.status} - {error_text}")

                except aiohttp.ClientError as e:
                    logger.error(f"Network error: {e}")
                    if attempt == max_retries - 1:
                        raise Exception(f"Ошибка сети при обращении к OpenRouter: {e}")
                    await asyncio.sleep(2 ** (attempt + 1))

        raise Exception(
            f"⚠️ Все модели недоступны из-за rate limiting. "
        )

    async def close(self):
        """Закрывает сессию."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("OpenRouter client session closed")
