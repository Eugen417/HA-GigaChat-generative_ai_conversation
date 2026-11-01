"""Base entity for the Sber GigaChat AI integration."""

import asyncio
import base64
from collections.abc import Callable
import logging
import time
from typing import Any
import uuid

import aiohttp
import probatio

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, llm
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.json import json_dumps
from homeassistant.util.json import json_loads

from .const import (
    CLOUD_RU_BASE_URL,
    CONF_AUTH_KEY,
    CONF_CHAT_MODEL,
    CONF_CLOUD_RU_API_KEY,
    CONF_IMAGE_MODEL,
    CONF_MAX_TOKENS,
    CONF_RECOMMENDED,
    CONF_SCOPE,
    CONF_SPEECH_AUTH_KEY,
    CONF_SPEECH_SCOPE,
    CONF_STT_MODEL,
    CONF_TEMPERATURE,
    CONF_TTS_VOICE,
    CONF_VERIFY_SSL,
    DEFAULT_CHAT_MODEL,
    DEFAULT_SBER_STUDIO_CHAT_MODEL,
    DEFAULT_SCOPE,
    DEFAULT_SPEECH_SCOPE,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    GIGACHAT_BASE_URL,
    OAUTH_URL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_TEMPERATURE,
)

_LOGGER = logging.getLogger(__name__)
MAX_TOOL_ITERATIONS = 10

_SMART_HOME_SYSTEM_ADDON = (
    "\n\nПРАВИЛА УПРАВЛЕНИЯ УМНЫМ ДОМОМ HOME ASSISTANT:\n"
    "1. В статическом списке устройств указаны только названия и комнаты, но НЕТ их текущих показаний!\n"
    "2. При ЛЮБОМ вопросе о температуре, влажности, CO2, статусе датчиков, света или устройств "
    "ОБЯЗАТЕЛЬНО сначала вызови функцию GetLiveContext (или homeassistant__GetLiveContext) без аргументов, "
    "получи текущие показания и ответь пользователю конкретным числом (например: «Температура в спальне составляет 22,1 °C»). "
    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО отвечать просто названием датчика (например, «Спальня Температура») и запрещено вызывать GetDateTime вместо GetLiveContext!\n"
    "3. Для включения, выключения или изменения яркости/температуры устройств обязательно вызывай функции HassTurnOn, HassTurnOff, HassLightSet, HassClimateSetTemperature.\n"
    "4. Никогда не вызывай одну и ту же функцию дважды подряд с одинаковыми аргументами."
)


def _clean_auth_key(raw_key: str) -> str:
    """Strip Basic or Bearer prefix if user included it."""
    key = raw_key.strip()
    for prefix in ("Basic ", "basic ", "Bearer ", "bearer "):
        if key.startswith(prefix):
            key = key[len(prefix) :].strip()
    return key


def _is_sber_studio_base64_key(key: str) -> bool:
    """Return True if key is Base64-encoded 'client_id:client_secret' from Sber Studio."""
    if not key:
        return False
    try:
        padded = key + "=" * (-len(key) % 4)
        decoded = base64.b64decode(padded, validate=False).decode("utf-8")
        parts = decoded.split(":")
        return len(parts) == 2 and len(parts[0]) >= 16 and len(parts[1]) >= 16
    except Exception:  # noqa: BLE001
        return False


_VALID_GIGACHAT_TYPES = {"string", "number", "integer", "boolean", "array", "object"}


def _normalize_gigachat_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize JSON Schema for GigaChat strict functions validator."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    # 1. Resolve anyOf / oneOf / allOf into a single concrete type
    for union_key in ("anyOf", "oneOf", "allOf"):
        variants = schema.pop(union_key, None)
        if isinstance(variants, list) and variants:
            chosen: dict[str, Any] | None = None
            for pref_type in ("array", "string", "number", "integer", "boolean", "object"):
                for v in variants:
                    if isinstance(v, dict) and v.get("type") == pref_type:
                        chosen = v
                        break
                if chosen is not None:
                    break
            if chosen is None:
                for v in variants:
                    if isinstance(v, dict) and v.get("type") != "null":
                        chosen = v
                        break
            if isinstance(chosen, dict):
                for k, val in chosen.items():
                    if k not in schema or k == "type":
                        schema[k] = val

    # 2. If type is a list (e.g. ["string", "array"] or ["string", "null"]), pick one string
    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        if "array" in raw_type:
            schema["type"] = "array"
        else:
            non_null = [t for t in raw_type if isinstance(t, str) and t in _VALID_GIGACHAT_TYPES]
            schema["type"] = non_null[0] if non_null else "string"

    # 3. Ensure type is always a valid single string
    if schema.get("type") not in _VALID_GIGACHAT_TYPES:
        if "properties" in schema and isinstance(schema["properties"], dict):
            schema["type"] = "object"
        elif "items" in schema:
            schema["type"] = "array"
        else:
            schema["type"] = "string"

    # 4. Normalize object properties and required list
    if schema["type"] == "object":
        raw_props = schema.get("properties")
        if isinstance(raw_props, dict):
            clean_props: dict[str, Any] = {}
            for prop_name, prop_val in raw_props.items():
                if isinstance(prop_val, dict):
                    clean_props[prop_name] = _normalize_gigachat_json_schema(dict(prop_val))
                else:
                    clean_props[prop_name] = {"type": "string"}
            schema["properties"] = clean_props
            if isinstance(schema.get("required"), list):
                schema["required"] = [
                    r for r in schema["required"] if isinstance(r, str) and r in clean_props
                ]
            else:
                schema.pop("required", None)
        else:
            schema["properties"] = {}
            schema.pop("required", None)

    # 5. Normalize array items
    if schema["type"] == "array":
        raw_items = schema.get("items")
        if isinstance(raw_items, dict):
            schema["items"] = _normalize_gigachat_json_schema(dict(raw_items))
        elif isinstance(raw_items, list) and raw_items and isinstance(raw_items[0], dict):
            schema["items"] = _normalize_gigachat_json_schema(dict(raw_items[0]))
        else:
            schema["items"] = {"type": "string"}

    # 6. Strip all unsupported OpenAPI/JSON-Schema keys so GigaChat never returns 422
    allowed_keys = {"type", "description", "properties", "required", "items", "enum"}
    for k in list(schema.keys()):
        if k not in allowed_keys:
            schema.pop(k, None)

    return schema


def _format_tool(
    tool: llm.Tool,
    custom_serializer: Callable[[Any], Any] | None,
    include_examples: bool = False,
) -> dict[str, Any]:
    """Format tool specification for GigaChat API (`functions` array)."""
    schema: dict[str, Any] = {"type": "object", "properties": {}}
    if probatio is not None:
        try:
            schema = probatio.to_openapi(
                tool.parameters, custom_serializer=custom_serializer
            )
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            if "type" not in schema or not isinstance(schema["type"], str):
                schema["type"] = "object"
            schema = _normalize_gigachat_json_schema(schema)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Failed to convert tool schema for %s: %s", tool.name, err)
            schema = {"type": "object", "properties": {}}

    desc = tool.description or f"Вызов инструмента {tool.name}"
    examples: list[dict[str, Any]] | None = None
    if "GetLiveContext" in tool.name:
        desc = (
            "ОБЯЗАТЕЛЬНО вызывай эту функцию без аргументов для получения текущих "
            "показаний всех датчиков (температура, влажность, CO2) и актуального "
            "состояния устройств умного дома в реальном времени. "
            f"{desc}"
        )
        examples = [
            {"request": "Какая температура в спальне?", "params": {}},
            {"request": "Какая температура в зале?", "params": {}},
            {"request": "Включен ли свет на кухне?", "params": {}},
        ]
    elif "HassTurnOn" in tool.name:
        desc = f"Включает устройство, свет, выключатель или сцену в умном доме. {desc}"
    elif "HassTurnOff" in tool.name:
        desc = f"Выключает устройство, свет или выключатель в умном доме. {desc}"
    elif "GetDateTime" in tool.name:
        desc = "Возвращает только текущую дату и время (НЕ используй для датчиков или температуры!)."

    func_spec: dict[str, Any] = {
        "name": tool.name,
        "description": desc,
        "parameters": schema,
    }
    if include_examples and examples:
        func_spec["few_shot_examples"] = examples
    return func_spec


def _build_gigachat_messages(
    chat_contents: list[conversation.Content],
    has_tools: bool = False,
    state_ids: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Convert ChatLog.content into GigaChat messages with strict function_call/function pairing."""
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []

    last_user_idx = 0
    for idx, item in enumerate(chat_contents):
        if isinstance(item, conversation.UserContent):
            last_user_idx = idx

    idx = 0
    n = len(chat_contents)
    while idx < n:
        content = chat_contents[idx]
        if isinstance(content, conversation.SystemContent):
            if content.content:
                system_parts.append(content.content)
            idx += 1
            continue

        if isinstance(content, conversation.UserContent):
            messages.append({"role": "user", "content": content.content or " "})
            idx += 1
            continue

        if isinstance(content, conversation.AssistantContent):
            if content.tool_calls:
                tool_results: list[conversation.ToolResultContent] = []
                next_idx = idx + 1
                while next_idx < n and isinstance(
                    chat_contents[next_idx], conversation.ToolResultContent
                ):
                    tool_results.append(chat_contents[next_idx])  # type: ignore[arg-type]
                    next_idx += 1

                results_by_id = {tr.tool_call_id: tr for tr in tool_results}
                used_ids: set[str] = set()

                for tc_idx, tc in enumerate(content.tool_calls):
                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": (content.content or "") if tc_idx == 0 else "",
                        "function_call": {
                            "name": tc.tool_name,
                            "arguments": tc.tool_args or {},
                        },
                    }
                    if state_ids and tc.id in state_ids:
                        assistant_msg["functions_state_id"] = state_ids[tc.id]
                    messages.append(assistant_msg)
                    matched_tr = results_by_id.get(tc.id)
                    if matched_tr is None:
                        for tr in tool_results:
                            if (
                                tr.tool_call_id not in used_ids
                                and tr.tool_name == tc.tool_name
                            ):
                                matched_tr = tr
                                break
                    if matched_tr is not None:
                        used_ids.add(matched_tr.tool_call_id)
                        if (
                            idx < last_user_idx
                            and "GetLiveContext" in matched_tr.tool_name
                        ):
                            res_payload: dict[str, Any] = {"status": "ok"}
                        else:
                            res_payload = {
                                "data": matched_tr.result.data,
                                "error": matched_tr.result.error,
                            }
                    else:
                        res_payload = {"status": "ok"}

                    messages.append(
                        {
                            "role": "function",
                            "name": tc.tool_name,
                            "content": json_dumps(res_payload),
                        }
                    )

                idx = next_idx
                continue

            messages.append(
                {"role": "assistant", "content": content.content or " "}
            )
            idx += 1
            continue

        if isinstance(content, conversation.ToolResultContent):
            if idx < last_user_idx and "GetLiveContext" in content.tool_name:
                res_payload = {"status": "ok"}
            else:
                res_payload = {
                    "data": content.result.data,
                    "error": content.result.error,
                }
            messages.append(
                {
                    "role": "function",
                    "name": content.tool_name,
                    "content": json_dumps(res_payload),
                }
            )
            idx += 1
            continue

        idx += 1

    if has_tools:
        system_parts.append(_SMART_HOME_SYSTEM_ADDON)
    if system_parts:
        messages.insert(
            0,
            {"role": "system", "content": "\n\n".join(system_parts)},
        )

    return messages


def _build_openai_messages(
    chat_contents: list[conversation.Content],
    has_tools: bool = False,
) -> list[dict[str, Any]]:
    """Convert ChatLog.content into OpenAI-compatible messages for Cloud.ru Foundation Models."""
    messages: list[dict[str, Any]] = []
    last_user_idx = 0
    for idx, item in enumerate(chat_contents):
        if isinstance(item, conversation.UserContent):
            last_user_idx = idx

    for idx, content in enumerate(chat_contents):
        if isinstance(content, conversation.SystemContent):
            if content.content:
                sys_text = (
                    f"{content.content}{_SMART_HOME_SYSTEM_ADDON}"
                    if has_tools
                    else content.content
                )
                messages.append({"role": "system", "content": sys_text})
        elif isinstance(content, conversation.UserContent):
            messages.append({"role": "user", "content": content.content or " "})
        elif isinstance(content, conversation.AssistantContent):
            if content.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": content.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.tool_name,
                                    "arguments": json_dumps(tc.tool_args or {}),
                                },
                            }
                            for tc in content.tool_calls
                        ],
                    }
                )
            else:
                messages.append(
                    {"role": "assistant", "content": content.content or " "}
                )
        elif isinstance(content, conversation.ToolResultContent):
            if idx < last_user_idx and "GetLiveContext" in content.tool_name:
                res_payload: dict[str, Any] = {"status": "ok"}
            else:
                res_payload = {
                    "data": content.result.data,
                    "error": content.result.error,
                }
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": content.tool_call_id,
                    "name": content.tool_name,
                    "content": json_dumps(res_payload),
                }
            )
    return messages


def _estimate_gigachat_cost_rub(
    model_name: str,
    total_tokens: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    """Estimate request cost in RUB based on Cloud.ru or Sber Studio pricing."""
    in_tok = input_tokens or total_tokens
    out_tok = output_tokens
    m_lower = model_name.lower()
    if "/" in model_name:
        if "3-10b" in m_lower:
            return (in_tok * 12.2 + out_tok * 12.2) / 1_000_000.0
        if "3-pro" in m_lower:
            return (in_tok * 73.03 + out_tok * 176.39) / 1_000_000.0
        if "3.5-432b" in m_lower:
            return (in_tok * 96.22 + out_tok * 288.60) / 1_000_000.0
        if "2-max" in m_lower:
            return total_tokens * 569.34 / 1_000_000.0
        if "qwen3.6-35b" in m_lower:
            return (in_tok * 219.6 + out_tok * 329.4) / 1_000_000.0
        return total_tokens * 100.0 / 1_000_000.0

    if "max" in m_lower:
        rate_per_1k = 1.95
    elif "pro" in m_lower:
        rate_per_1k = 1.50
    else:
        rate_per_1k = 0.19
    return total_tokens * rate_per_1k / 1000.0


class GigaChatBaseLLMEntity(Entity):
    """Sber GigaChat AI base entity."""

    def __init__(
        self,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        default_model: str = DEFAULT_CHAT_MODEL,
    ) -> None:
        """Initialize the base entity."""
        self.entry = entry
        self._subentry = subentry
        self._subentry_id = subentry.subentry_id
        self._functions_state_ids: dict[str, str] = {}
        self._cloud_ru_exhausted: bool = False

        raw_cloud = _clean_auth_key(str(entry.data.get(CONF_CLOUD_RU_API_KEY, "")))
        raw_auth = _clean_auth_key(str(entry.data.get(CONF_AUTH_KEY, "")))
        raw_speech = _clean_auth_key(str(entry.data.get(CONF_SPEECH_AUTH_KEY, "")))

        self.cloud_ru_api_key = raw_cloud
        self.auth_key = raw_auth
        self.speech_auth_key = ""
        self.has_separate_speech_key = False

        if raw_speech and _is_sber_studio_base64_key(raw_speech):
            self.speech_auth_key = raw_speech
            self.has_separate_speech_key = True

        self.scope = str(entry.data.get(CONF_SCOPE, DEFAULT_SCOPE))
        self.speech_scope = str(
            entry.data.get(CONF_SPEECH_SCOPE, DEFAULT_SPEECH_SCOPE)
        )
        self.verify_ssl = bool(entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))
        self.default_model = default_model
        self._attr_name = subentry.title
        self._attr_unique_id = subentry.subentry_id

        if subentry.data.get(CONF_RECOMMENDED):
            model = default_model
        elif subentry.subentry_type == "ai_task_image":
            model = subentry.data.get(CONF_IMAGE_MODEL) or default_model
        else:
            model = (
                subentry.data.get(CONF_CHAT_MODEL)
                or subentry.data.get(CONF_STT_MODEL)
                or subentry.data.get(CONF_TTS_VOICE)
                or subentry.data.get(CONF_IMAGE_MODEL)
                or default_model
            )
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Sber",
            model=str(model),
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    @property
    def subentry(self) -> ConfigSubentry:
        """Return the latest subentry from the config entry."""
        return self.entry.subentries.get(self._subentry_id, self._subentry)

    async def async_get_access_token(
        self, is_speech: bool = False, force_refresh: bool = False
    ) -> str:
        """Obtain or return cached OAuth 2.0 access token from Sber NGW."""
        key = self.speech_auth_key if is_speech else self.auth_key
        scope = self.speech_scope if is_speech else self.scope
        cache_key = f"{key[:16]}:{scope}"

        token_store: dict[str, dict[str, Any]] = {}
        if self.hass is not None:
            domain_data = self.hass.data.setdefault(DOMAIN, {})
            token_store = domain_data.setdefault("_tokens", {})

        now = time.time()
        if not force_refresh and cache_key in token_store:
            cached = token_store[cache_key]
            if (
                cached.get("access_token")
                and float(cached.get("expires_at", 0)) > now + 60
            ):
                return str(cached["access_token"])

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {key}",
        }
        data = {"scope": scope}

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    OAUTH_URL,
                    headers=headers,
                    data=data,
                    ssl=self.verify_ssl,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp,
            ):
                if resp.status != 200:
                    err_text = await resp.text()
                    _LOGGER.error(
                        "Sber OAuth error (%s) for scope %s: %s",
                        resp.status,
                        scope,
                        err_text,
                    )
                    raise HomeAssistantError(
                        f"Ошибка авторизации Sber OAuth ({resp.status}): {err_text}"
                    )

                res_json = await resp.json()
                access_token = res_json.get("access_token")
                if not access_token:
                    raise HomeAssistantError("Sber OAuth не вернул access_token")

                raw_exp = float(res_json.get("expires_at", 0) or 0)
                if raw_exp > 1e11:
                    expires_at = raw_exp / 1000.0
                elif raw_exp > now:
                    expires_at = raw_exp
                else:
                    expires_at = now + 1740

                token_store[cache_key] = {
                    "access_token": access_token,
                    "expires_at": expires_at,
                }
                return str(access_token)
        except HomeAssistantError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("Error connecting to Sber OAuth: %s", err)
            raise HomeAssistantError(
                f"Ошибка соединения с Sber OAuth: {err}"
            ) from err

    async def _async_handle_cloud_ru_chat_log(
        self,
        chat_log: conversation.ChatLog,
        model_name: str,
        temperature: float,
        max_tokens: int,
        is_recommended: bool,
        tools: list[dict[str, Any]] | None,
        structure_instruction: str | None,
    ) -> None:
        """Handle chat log via Cloud.ru Evolution Foundation Models (OpenAI-compatible)."""
        openai_tools = (
            [{"type": "function", "function": t} for t in tools] if tools else None
        )
        cloud_model = (
            model_name
            if ("/" in model_name and "ocr" not in model_name.lower())
            else "GigaChat/GigaChat-3-Pro"
        )
        candidates = [cloud_model]
        for fb in (
            "GigaChat/GigaChat-3-Pro",
            "ai-sage/GigaChat3-10B-A1.8B",
            "ai-sage/GigaChat3.5-432B-A28B-Reasoning",
        ):
            if fb not in candidates:
                candidates.append(fb)

        headers = {
            "Authorization": f"Bearer {self.cloud_ru_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        called_in_turn: set[str] = set()
        for _iteration in range(MAX_TOOL_ITERATIONS):
            messages = _build_openai_messages(
                chat_log.content, has_tools=bool(openai_tools)
            )
            if structure_instruction and messages:
                messages[-1] = {
                    **messages[-1],
                    "content": f"{messages[-1].get('content', '')}{structure_instruction}",
                }

            res_data: dict[str, Any] | None = None
            last_status = 0
            last_err = ""
            used_model = cloud_model

            try:
                async with aiohttp.ClientSession() as session:
                    for candidate in candidates:
                        payload: dict[str, Any] = {
                            "model": candidate,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "stream": False,
                        }
                        if openai_tools:
                            payload["tools"] = openai_tools
                            payload["tool_choice"] = "auto"

                        async with session.post(
                            f"{CLOUD_RU_BASE_URL}/chat/completions",
                            headers=headers,
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=60),
                        ) as resp:
                            if resp.status == 200:
                                res_data = await resp.json()
                                used_model = candidate
                                break
                            last_status = resp.status
                            last_err = await resp.text()
                            if last_status not in (402, 404, 422):
                                break

                    if res_data is None:
                        raise HomeAssistantError(
                            f"Ошибка API Cloud.ru Foundation Models ({last_status}): {last_err}"
                        )

                    choices = res_data.get("choices", [])
                    if not choices:
                        raise HomeAssistantError(
                            "Пустой ответ от Cloud.ru Foundation Models"
                        )

                    usage = res_data.get("usage", {})
                    in_tokens = int(usage.get("prompt_tokens", 0) or 0)
                    out_tokens = int(usage.get("completion_tokens", 0) or 0)
                    tot_tokens = int(
                        usage.get("total_tokens", 0) or (in_tokens + out_tokens)
                    )
                    cost_rub = _estimate_gigachat_cost_rub(
                        used_model, tot_tokens, in_tokens, out_tokens
                    )
                    if self.hass is not None:
                        async_dispatcher_send(
                            self.hass,
                            f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                            {
                                "tokens": tot_tokens,
                                "input_tokens": in_tokens,
                                "output_tokens": out_tokens,
                                "cost_rub": cost_rub,
                                "model": used_model,
                            },
                        )

                    message = choices[0].get("message", {})
                    tool_calls: list[llm.ToolInput] = []
                    for tc in message.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        raw_args = fn.get("arguments", {})
                        if isinstance(raw_args, str):
                            try:
                                parsed = (
                                    json_loads(raw_args) if raw_args.strip() else {}
                                )
                                t_args = parsed if isinstance(parsed, dict) else {}
                            except Exception:  # noqa: BLE001
                                t_args = {}
                        elif isinstance(raw_args, dict):
                            t_args = raw_args
                        else:
                            t_args = {}
                        if fn_name := fn.get("name"):
                            sig = f"{fn_name}:{json_dumps(t_args)}"
                            if sig in called_in_turn:
                                continue
                            called_in_turn.add(sig)
                            tool_calls.append(
                                llm.ToolInput(
                                    id=tc.get("id"),
                                    tool_name=str(fn_name),
                                    tool_args=t_args,
                                )
                            )

                    assistant_content = conversation.AssistantContent(
                        agent_id=self.entity_id,
                        content=message.get("content") or None,
                        tool_calls=tool_calls or None,
                    )
                    _LOGGER.info(
                        "Cloud.ru LLM [%s] tokens=%s tool_calls=%s text=%s",
                        used_model,
                        tot_tokens,
                        [tc.tool_name for tc in tool_calls],
                        (message.get("content") or "")[:120],
                    )
                    async for _ in chat_log.async_add_assistant_content(
                        assistant_content
                    ):
                        pass

            except HomeAssistantError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise HomeAssistantError(
                    f"Ошибка соединения с Cloud.ru Foundation Models: {err}"
                ) from err

            if not chat_log.unresponded_tool_results:
                break

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
        structure: Any | None = None,
    ) -> None:
        """Generate an answer for the chat log using GigaChat API."""
        options = self.subentry.data
        is_recommended = bool(options.get(CONF_RECOMMENDED, True))
        if is_recommended:
            model_name = (
                DEFAULT_SBER_STUDIO_CHAT_MODEL
                if self.auth_key
                else "GigaChat/GigaChat-3-Pro"
            )
            temperature = float(RECOMMENDED_TEMPERATURE)
            max_tokens = int(RECOMMENDED_MAX_TOKENS)
        else:
            model_name = str(options.get(CONF_CHAT_MODEL, self.default_model))
            temperature = float(options.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE))
            max_tokens = int(options.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS))

        tools: list[dict[str, Any]] | None = None
        use_cloud_ru = bool(
            self.cloud_ru_api_key
            and not self._cloud_ru_exhausted
            and ("/" in model_name or not self.auth_key)
        )
        if chat_log.llm_api:
            tools = [
                _format_tool(
                    tool,
                    chat_log.llm_api.custom_serializer,
                    include_examples=not use_cloud_ru,
                )
                for tool in chat_log.llm_api.tools
                if "GetDateTime" not in tool.name
            ]

        structure_instruction: str | None = None
        if structure is not None and probatio is not None:
            try:
                schema = probatio.to_openapi(
                    structure,
                    custom_serializer=(
                        chat_log.llm_api.custom_serializer
                        if chat_log.llm_api
                        else llm.selector_serializer
                    ),
                )
                norm_schema = _normalize_gigachat_json_schema(schema)
                structure_instruction = (
                    "\n\nВерни ответ СТРОГО в формате валидного JSON без Markdown-блоков "
                    f"согласно этой JSON Schema:\n{json_dumps(norm_schema)}"
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Failed to build structure JSON schema: %s", err)

        if use_cloud_ru:
            try:
                await self._async_handle_cloud_ru_chat_log(
                    chat_log,
                    model_name,
                    temperature,
                    max_tokens,
                    is_recommended,
                    tools,
                    structure_instruction,
                )
                return
            except HomeAssistantError as err:
                if "402" in str(err) or "Not enough money" in str(err):
                    self._cloud_ru_exhausted = True
                    if self.auth_key:
                        _LOGGER.warning(
                            "Cloud.ru balance is 0 RUB (402 Not enough money); "
                            "automatically falling back to Sber Studio Freemium key"
                        )
                        if chat_log.llm_api:
                            tools = [
                                _format_tool(
                                    tool,
                                    chat_log.llm_api.custom_serializer,
                                    include_examples=True,
                                )
                                for tool in chat_log.llm_api.tools
                                if "GetDateTime" not in tool.name
                            ]
                    else:
                        raise HomeAssistantError(
                            "Недостаточно средств на балансе Cloud.ru (402 Not enough money). "
                            "Пополните баланс в консоли Cloud.ru "
                            "или добавьте Ключ авторизации Sber Studio в настройках интеграции."
                        ) from err
                else:
                    raise

        if "/" in model_name:
            model_name = DEFAULT_SBER_STUDIO_CHAT_MODEL

        called_in_turn: set[str] = set()
        force_no_tools = False
        for _iteration in range(MAX_TOOL_ITERATIONS):
            messages = _build_gigachat_messages(
                chat_log.content,
                has_tools=bool(tools),
                state_ids=self._functions_state_ids,
            )
            if structure_instruction and messages:
                messages[-1] = {
                    **messages[-1],
                    "content": f"{messages[-1].get('content', '')}{structure_instruction}",
                }

            token = await self.async_get_access_token(is_speech=False)

            candidate_models = [model_name]
            if is_recommended:
                for fallback in (
                    "GigaChat-2-Pro",
                    "GigaChat-2",
                    "GigaChat",
                ):
                    if fallback not in candidate_models:
                        candidate_models.append(fallback)

            res_data: dict[str, Any] | None = None
            last_status = 0
            last_err = ""
            used_model = model_name

            try:
                async with aiohttp.ClientSession() as session:
                    for candidate in candidate_models:
                        payload: dict[str, Any] = {
                            "model": candidate,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "stream": False,
                        }
                        if tools:
                            payload["functions"] = tools
                            payload["function_call"] = (
                                "none" if force_no_tools else "auto"
                            )

                        for attempt in range(2):
                            headers = {
                                "Authorization": f"Bearer {token}",
                                "Content-Type": "application/json",
                                "Accept": "application/json",
                            }
                            async with session.post(
                                f"{GIGACHAT_BASE_URL}/chat/completions",
                                headers=headers,
                                json=payload,
                                ssl=self.verify_ssl,
                                timeout=aiohttp.ClientTimeout(total=60),
                            ) as resp:
                                if resp.status == 401 and attempt == 0:
                                    token = await self.async_get_access_token(
                                        is_speech=False, force_refresh=True
                                    )
                                    continue

                                if resp.status == 200:
                                    res_data = await resp.json()
                                    used_model = candidate
                                    break

                                last_status = resp.status
                                last_err = await resp.text()
                                break

                        if res_data is not None:
                            break
                        if last_status not in (402, 404, 422):
                            break

                    if res_data is None:
                        _LOGGER.error(
                            "GigaChat API error %s: %s", last_status, last_err
                        )
                        raise HomeAssistantError(
                            f"Ошибка API GigaChat ({last_status}): {last_err}"
                        )

                    choices = res_data.get("choices", [])
                    if not choices:
                        raise HomeAssistantError("Пустой ответ от GigaChat")

                    usage = res_data.get("usage", {})
                    in_tokens = int(usage.get("prompt_tokens", 0) or 0) + int(
                        usage.get("precached_prompt_tokens", 0) or 0
                    )
                    out_tokens = int(usage.get("completion_tokens", 0) or 0)
                    tot_tokens = in_tokens + out_tokens
                    cost_rub = _estimate_gigachat_cost_rub(used_model, tot_tokens)
                    if self.hass is not None:
                        async_dispatcher_send(
                            self.hass,
                            f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                            {
                                "tokens": tot_tokens,
                                "input_tokens": in_tokens,
                                "output_tokens": out_tokens,
                                "cost_rub": cost_rub,
                                "model": used_model,
                            },
                        )

                    message = choices[0].get("message", {})
                    state_id = message.get("functions_state_id")
                    tool_calls: list[llm.ToolInput] = []
                    if not force_no_tools and (
                        func_call := message.get("function_call")
                    ):
                        raw_args = func_call.get("arguments", {})
                        if isinstance(raw_args, str):
                            try:
                                parsed_args = (
                                    json_loads(raw_args) if raw_args.strip() else {}
                                )
                                tool_args = (
                                    parsed_args
                                    if isinstance(parsed_args, dict)
                                    else {}
                                )
                            except Exception:  # noqa: BLE001
                                tool_args = {}
                        elif isinstance(raw_args, dict):
                            tool_args = raw_args
                        else:
                            tool_args = {}

                        if func_name := func_call.get("name"):
                            sig = f"{func_name}:{json_dumps(tool_args)}"
                            if sig in called_in_turn:
                                force_no_tools = True
                                continue
                            called_in_turn.add(sig)
                            ti = llm.ToolInput(
                                tool_name=str(func_name),
                                tool_args=tool_args,
                            )
                            if state_id:
                                self._functions_state_ids[ti.id] = str(state_id)
                            tool_calls.append(ti)
                            if "GetLiveContext" in str(func_name):
                                force_no_tools = True

                    assistant_content = conversation.AssistantContent(
                        agent_id=self.entity_id,
                        content=message.get("content") or None,
                        tool_calls=tool_calls or None,
                    )
                    _LOGGER.info(
                        "GigaChat LLM [%s] tokens=%s tool_calls=%s text=%s",
                        used_model,
                        tot_tokens,
                        [tc.tool_name for tc in tool_calls],
                        (message.get("content") or "")[:120],
                    )
                    async for _ in chat_log.async_add_assistant_content(
                        assistant_content
                    ):
                        pass

            except HomeAssistantError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.error("Error communicating with GigaChat API: %s", err)
                raise HomeAssistantError(
                    f"Ошибка соединения с GigaChat API: {err}"
                ) from err

            if not chat_log.unresponded_tool_results:
                break




