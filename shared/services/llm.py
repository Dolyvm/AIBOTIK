import asyncio
import json
import httpx
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, ClassVar

from shared.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    LLM_MODEL,
    LLM_ACTIVE_MODEL_PROMPT_KEY,
    LLM_MODEL_CHOICES,
    LLM_TEMPERATURE,
    LLM_TOP_P,
    LLM_REPETITION_PENALTY,
)

logger = logging.getLogger(__name__)


DEEPSEEK_MODEL_PREFIX = "deepseek/"
IGNORED_DEEPSEEK_OPENROUTER_PROVIDER_SLUGS = ("alibaba",)


def _uses_deepseek_model(model: str) -> bool:
    return model.lower().startswith(DEEPSEEK_MODEL_PREFIX)


def _with_ignored_providers(provider: dict | None) -> dict:
    provider_config = dict(provider or {})
    raw_ignore = provider_config.get("ignore")
    if isinstance(raw_ignore, list):
        ignored_providers = raw_ignore.copy()
    elif isinstance(raw_ignore, (tuple, set)):
        ignored_providers = list(raw_ignore)
    elif raw_ignore:
        ignored_providers = [str(raw_ignore)]
    else:
        ignored_providers = []

    for provider_slug in IGNORED_DEEPSEEK_OPENROUTER_PROVIDER_SLUGS:
        if provider_slug not in ignored_providers:
            ignored_providers.append(provider_slug)

    provider_config["ignore"] = ignored_providers
    return provider_config


class LLMError(Exception):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMProviderStreamError(LLMError):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "provider_stream_error",
        provider_message: str = "",
        code: Any = None,
        model: Optional[str] = None,
        response_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.provider_message = provider_message
        self.code = code
        self.model = model
        self.response_id = response_id
        self.metadata = metadata or {}


class LLMProviderContentFilterError(LLMProviderStreamError):
    pass


@dataclass(slots=True)
class LLMResponse:
    content: str
    finish_reason: Optional[str] = None
    native_finish_reason: Optional[str] = None
    usage: dict[str, Any] = field(default_factory=dict)
    model: Optional[str] = None
    id: Optional[str] = None

    @property
    def completion_tokens(self) -> int:
        value = self.usage.get("completion_tokens", 0)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return 0


@dataclass(slots=True)
class LLMStreamEvent:
    content: str = ""
    finish_reason: Optional[str] = None
    native_finish_reason: Optional[str] = None
    usage: dict[str, Any] = field(default_factory=dict)
    model: Optional[str] = None
    id: Optional[str] = None


class LLMClient:
    MAX_RETRIES = 5
    RETRY_DELAY = 2.0

    _http_client: ClassVar[Optional[httpx.AsyncClient]] = None

    @classmethod
    def get_http_client(cls) -> httpx.AsyncClient:
        if cls._http_client is None:
            cls._http_client = httpx.AsyncClient(
                timeout=60,
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20
                )
            )
            logger.info("Created httpx client with connection pooling")
        return cls._http_client

    @classmethod
    async def close_http_client(cls) -> None:
        if cls._http_client is not None:
            await cls._http_client.aclose()
            cls._http_client = None
            logger.info("Closed httpx client")

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        override_payload: dict = None,
        provider: dict = None,
        reasoning: dict = None,
        timeout: float = None,
        max_retries: int = None,
    ):
        self.api_key = api_key or OPENROUTER_API_KEY
        self.model = model
        self.base_url = OPENROUTER_BASE_URL
        self.override_payload = override_payload or dict()
        self.provider = provider
        self.reasoning = {"enabled": False} if reasoning is None else reasoning
        self.timeout = timeout
        self.max_retries = max_retries or self.MAX_RETRIES

        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY не установлен!")

    async def _resolve_model(self) -> str:
        if self.model:
            return self.model

        try:
            from shared.services.prompt_service import get_prompt

            active_model = (await get_prompt(LLM_ACTIVE_MODEL_PROMPT_KEY)).strip()
            allowed_models = {choice["model"] for choice in LLM_MODEL_CHOICES.values()}
            if active_model in allowed_models:
                return active_model

            logger.warning("Unsupported active LLM model in DB/cache: %s", active_model)
        except Exception as e:
            logger.warning("Failed to resolve active LLM model from DB/cache: %s", e)

        return LLM_MODEL

    async def _build_payload(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float = None,
        provider: dict = None,
        reasoning: dict = None,
        extra_payload: dict = None,
    ) -> tuple[str, dict]:
        temperature = temperature if temperature is not None else LLM_TEMPERATURE
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        resolved_model = await self._resolve_model()
        payload = {
            "model": resolved_model,
            "messages": full_messages,
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
            "top_p": LLM_TOP_P,
            "repetition_penalty": LLM_REPETITION_PENALTY,
        }

        active_provider = self.provider if provider is None else provider
        if active_provider is not None:
            payload["provider"] = active_provider

        active_reasoning = self.reasoning if reasoning is None else reasoning
        if active_reasoning is not None:
            payload["reasoning"] = active_reasoning

        payload.update(self.override_payload)
        if extra_payload:
            payload.update(extra_payload)

        if _uses_deepseek_model(resolved_model):
            payload["provider"] = _with_ignored_providers(payload.get("provider"))

        return resolved_model, payload

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _request_kwargs(self, payload: dict) -> dict:
        request_kwargs = {
            "json": payload,
            "headers": self._headers(),
        }
        if self.timeout is not None:
            request_kwargs["timeout"] = self.timeout
        return request_kwargs

    async def generate(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 300,
        temperature: float = None,
        provider: dict = None,
        reasoning: dict = None,
        extra_payload: dict = None,
    ) -> LLMResponse:
        resolved_model, payload = await self._build_payload(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            provider=provider,
            reasoning=reasoning,
            extra_payload=extra_payload,
        )

        last_error = None
        
        client = self.get_http_client()

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"LLM запрос (попытка {attempt}/{self.max_retries}): model={resolved_model}")

                request_kwargs = self._request_kwargs(payload)
                response = await client.post(self.base_url, **request_kwargs)

                if response.status_code == 429:
                    logger.warning(f"Rate limit (429), попытка {attempt}/{self.max_retries}")
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.RETRY_DELAY * attempt)  
                        continue
                    raise LLMRateLimitError("Превышен лимит запросов к API")
                
                if response.status_code >= 500:
                    logger.warning(f"Серверная ошибка ({response.status_code}), попытка {attempt}/{self.max_retries}")
                    if attempt < self.max_retries:
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
                
                choice = data["choices"][0]
                if choice.get("error"):
                    logger.error(f"LLM choice error: {choice['error']}")
                    raise LLMError("Ошибка генерации ответа LLM")

                message = choice.get("message") or {}
                content = message.get("content", "") or ""
                llm_response = LLMResponse(
                    content=content,
                    finish_reason=choice.get("finish_reason"),
                    native_finish_reason=choice.get("native_finish_reason"),
                    usage=data.get("usage") or {},
                    model=data.get("model"),
                    id=data.get("id"),
                )
                
                if not content:
                    logger.warning("Пустой ответ от LLM")
                    return llm_response
                
                logger.info(
                    "LLM response: model=%s id=%s finish_reason=%s native_finish_reason=%s "
                    "prompt_tokens=%s completion_tokens=%s total_tokens=%s max_completion_tokens=%s chars=%s",
                    llm_response.model,
                    llm_response.id,
                    llm_response.finish_reason,
                    llm_response.native_finish_reason,
                    llm_response.usage.get("prompt_tokens"),
                    llm_response.usage.get("completion_tokens"),
                    llm_response.usage.get("total_tokens"),
                    max_tokens,
                    len(content),
                )
                if llm_response.finish_reason == "length":
                    logger.warning(
                        "LLM response was truncated by completion limit: id=%s max_completion_tokens=%s",
                        llm_response.id,
                        max_tokens,
                    )
                return llm_response
                
            except httpx.TimeoutException as e:
                logger.warning(f"Таймаут запроса, попытка {attempt}/{self.max_retries}: {e}")
                last_error = LLMTimeoutError(f"Таймаут запроса: {e}")
                if attempt < self.max_retries:
                    import asyncio
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
                    
            except httpx.RequestError as e:
                logger.error(f"Ошибка сети: {e}")
                last_error = LLMError(f"Ошибка сети: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
                    
            except (KeyError, IndexError, TypeError) as e:
                logger.error(f"Ошибка парсинга ответа: {e}")
                raise LLMError(f"Ошибка парсинга ответа: {e}")
        
        if last_error:
            raise last_error
        raise LLMError("Не удалось получить ответ от LLM")

    @staticmethod
    def _provider_error_fields(error_payload: Any) -> tuple[Any, str, dict[str, Any]]:
        if isinstance(error_payload, dict):
            code = error_payload.get("code")
            message = str(error_payload.get("message") or error_payload)
            metadata = error_payload.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            return code, message, metadata
        return None, str(error_payload), {}

    @staticmethod
    def _is_content_filter_error(message: str, metadata: dict[str, Any]) -> bool:
        haystack = f"{message} {metadata}".lower()
        content_filter_markers = (
            "inappropriate content",
            "content policy",
            "content filter",
            "safety",
            "moderation",
            "filtered",
        )
        return any(marker in haystack for marker in content_filter_markers)

    def _build_provider_stream_error(
        self,
        error_payload: Any,
        *,
        model: Optional[str],
        response_id: Optional[str],
    ) -> LLMProviderStreamError:
        code, message, metadata = self._provider_error_fields(error_payload)
        kwargs = {
            "provider_message": message,
            "code": code,
            "model": model,
            "response_id": response_id,
            "metadata": metadata,
        }
        if self._is_content_filter_error(message, metadata):
            return LLMProviderContentFilterError(
                "Ошибка генерации ответа LLM",
                kind="provider_content_filter",
                **kwargs,
            )
        return LLMProviderStreamError("Ошибка генерации ответа LLM", **kwargs)

    async def stream_generate(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 300,
        temperature: float = None,
        provider: dict = None,
        reasoning: dict = None,
        extra_payload: dict = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        resolved_model, payload = await self._build_payload(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            provider=provider,
            reasoning=reasoning,
            extra_payload=extra_payload,
        )
        payload["stream"] = True

        client = self.get_http_client()
        last_error = None
        yielded_content = False
        provider_stream_error_retried = False
        current_model = resolved_model
        current_id = None

        for attempt in range(1, self.max_retries + 1):
            try:
                stream_completed = False
                logger.debug(
                    "LLM stream request (attempt %s/%s): model=%s",
                    attempt,
                    self.max_retries,
                    resolved_model,
                )
                request_kwargs = self._request_kwargs(payload)

                async with client.stream("POST", self.base_url, **request_kwargs) as response:
                    if response.status_code == 429:
                        logger.warning("Rate limit (429), stream attempt %s/%s", attempt, self.max_retries)
                        if attempt < self.max_retries:
                            await response.aread()
                            await asyncio.sleep(self.RETRY_DELAY * attempt)
                            continue
                        raise LLMRateLimitError("Превышен лимит запросов к API")

                    if response.status_code >= 500:
                        logger.warning(
                            "Server error (%s), stream attempt %s/%s",
                            response.status_code,
                            attempt,
                            self.max_retries,
                        )
                        if attempt < self.max_retries:
                            await response.aread()
                            await asyncio.sleep(self.RETRY_DELAY)
                            continue
                        response.raise_for_status()

                    if response.status_code >= 400:
                        error_text = (await response.aread()).decode("utf-8", errors="replace")[:500]
                        logger.error("Stream API error (%s): %s", response.status_code, error_text)
                        raise LLMError(f"Ошибка API: {response.status_code}")

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue

                        raw_data = line[5:].strip()
                        if raw_data == "[DONE]":
                            stream_completed = True
                            break

                        try:
                            data = json.loads(raw_data)
                        except json.JSONDecodeError:
                            logger.warning("Malformed LLM stream chunk: %r", raw_data[:300])
                            continue

                        current_model = data.get("model") or current_model
                        current_id = data.get("id") or current_id

                        if data.get("error"):
                            error = self._build_provider_stream_error(
                                data["error"],
                                model=current_model,
                                response_id=current_id,
                            )
                            logger.error(
                                "LLM stream %s: model=%s id=%s code=%s upstream_message=%s metadata=%s",
                                error.kind,
                                error.model,
                                error.response_id,
                                error.code,
                                error.provider_message,
                                error.metadata,
                            )
                            raise error

                        choices = data.get("choices") or []
                        if not choices:
                            continue

                        choice = choices[0]
                        if choice.get("error"):
                            error = self._build_provider_stream_error(
                                choice["error"],
                                model=current_model,
                                response_id=current_id,
                            )
                            logger.error(
                                "LLM stream choice %s: model=%s id=%s code=%s upstream_message=%s metadata=%s",
                                error.kind,
                                error.model,
                                error.response_id,
                                error.code,
                                error.provider_message,
                                error.metadata,
                            )
                            raise error

                        delta = choice.get("delta") or {}
                        content = delta.get("content") or ""
                        event = LLMStreamEvent(
                            content=content,
                            finish_reason=choice.get("finish_reason"),
                            native_finish_reason=choice.get("native_finish_reason"),
                            usage=data.get("usage") or {},
                            model=data.get("model"),
                            id=data.get("id"),
                        )
                        if event.finish_reason:
                            stream_completed = True
                        if event.content or event.finish_reason or event.usage:
                            if event.content:
                                yielded_content = True
                            yield event
                    if not stream_completed:
                        last_error = LLMError("Поток ответа оборвался")
                        logger.warning(
                            "LLM stream ended without terminal event, attempt %s/%s",
                            attempt,
                            self.max_retries,
                        )
                        if yielded_content:
                            raise last_error
                        if attempt < self.max_retries:
                            await asyncio.sleep(self.RETRY_DELAY)
                            continue
                        raise last_error
                    return

            except LLMProviderStreamError as e:
                last_error = e
                if not yielded_content and not provider_stream_error_retried and attempt < self.max_retries:
                    provider_stream_error_retried = True
                    logger.warning(
                        "Retrying LLM stream after %s before content: model=%s id=%s attempt=%s/%s",
                        e.kind,
                        e.model,
                        e.response_id,
                        attempt,
                        self.max_retries,
                    )
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
                raise
            except httpx.TimeoutException as e:
                logger.warning("Stream timeout, attempt %s/%s: %s", attempt, self.max_retries, e)
                last_error = LLMTimeoutError(f"Таймаут запроса: {e}")
                if yielded_content:
                    raise last_error
                if attempt < self.max_retries:
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
            except httpx.RequestError as e:
                logger.error("Stream network error: %s", e)
                last_error = LLMError(f"Ошибка сети: {e}")
                if yielded_content:
                    raise last_error
                if attempt < self.max_retries:
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
            except (KeyError, IndexError, TypeError) as e:
                logger.error("Stream parsing error: %s", e)
                raise LLMError(f"Ошибка парсинга ответа: {e}")

        if last_error:
            raise last_error
        raise LLMError("Не удалось получить потоковый ответ от LLM")
