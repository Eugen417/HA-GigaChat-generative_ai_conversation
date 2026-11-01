"""AI Task integration for Sber GigaChat AI."""

from json import JSONDecodeError
import logging
import re
from typing import Any, override

import aiohttp

from homeassistant.components import ai_task, conversation
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.json import json_loads

from .const import (
    CLOUD_RU_BASE_URL,
    CONF_IMAGE_MODEL,
    CONF_RECOMMENDED,
    DEFAULT_CHAT_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_SBER_VISION_MODEL,
    DEFAULT_VISION_MODEL,
    DOMAIN,
    GIGACHAT_BASE_URL,
)
from .entity import GigaChatBaseLLMEntity, _estimate_gigachat_cost_rub

_LOGGER = logging.getLogger(__name__)
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type not in ("ai_task_data", "ai_task_image"):
            continue
        async_add_entities(
            [GigaChatAITaskEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class GigaChatAITaskEntity(ai_task.AITaskEntity, GigaChatBaseLLMEntity):
    """Sber GigaChat AI Task entity."""

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the entity."""
        default_model = (
            DEFAULT_IMAGE_MODEL
            if subentry.subentry_type == "ai_task_image"
            else DEFAULT_CHAT_MODEL
        )
        super().__init__(entry, subentry, default_model)
        if subentry.subentry_type == "ai_task_image":
            self._attr_supported_features = ai_task.AITaskEntityFeature.GENERATE_IMAGE
        else:
            self._attr_supported_features = (
                ai_task.AITaskEntityFeature.GENERATE_DATA
                | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
            )

    @override
    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Handle a generate data task (including multimodal image/camera analysis)."""
        last_msg = chat_log.content[-1] if chat_log.content else None
        if (
            isinstance(last_msg, conversation.UserContent)
            and getattr(last_msg, "attachments", None)
        ):
            text = await self._async_analyze_attachments(last_msg, chat_log)
        else:
            await self._async_handle_chat_log(chat_log, task.structure)
            if not chat_log.content or not isinstance(
                chat_log.content[-1], conversation.AssistantContent
            ):
                raise HomeAssistantError("Не удалось получить ответ от GigaChat AI")
            text = (chat_log.content[-1].content or "").strip()

        if not task.structure:
            return ai_task.GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data=text,
            )

        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            data = json_loads(text)
        except JSONDecodeError as err:
            _LOGGER.error("Failed to parse JSON response: %s. Response: %s", err, text)
            raise HomeAssistantError(
                "Не удалось разобрать структурированный JSON-ответ от GigaChat"
            ) from err

        return ai_task.GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=data,
        )

    async def _async_analyze_attachments(
        self,
        user_message: conversation.UserContent,
        chat_log: conversation.ChatLog,
    ) -> str:
        """Analyze image/camera attachments using Cloud.ru Vision or Sber Studio GigaChat Vision."""
        if self.cloud_ru_api_key:
            import base64

            content_parts: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": user_message.content
                    or "Опиши на русском языке, что изображено на снимке.",
                }
            ]
            for attachment in user_message.attachments or []:
                mime_type = str(attachment.mime_type or "image/jpeg")
                if not mime_type.startswith("image/"):
                    raise HomeAssistantError(
                        f"Поддерживаются только изображения (получен {mime_type})"
                    )
                img_bytes = await self.hass.async_add_executor_job(
                    attachment.path.read_bytes
                )
                b64_img = base64.b64encode(img_bytes).decode("utf-8")
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_img}"},
                    }
                )

            cloud_vision_candidates = [
                DEFAULT_VISION_MODEL,
                "Qwen/Qwen3.5-397B-A17B",
                "moonshotai/Kimi-K2.6",
                "deepseek-ai/DeepSeek-OCR-2",
            ]
            async with aiohttp.ClientSession() as session:
                for candidate in cloud_vision_candidates:
                    payload = {
                        "model": candidate,
                        "messages": [{"role": "user", "content": content_parts}],
                        "stream": False,
                    }
                    async with session.post(
                        f"{CLOUD_RU_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.cloud_ru_api_key}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        if resp.status == 200:
                            res_data = await resp.json()
                            choices = res_data.get("choices", [])
                            if choices:
                                reply_text = (
                                    choices[0].get("message", {}).get("content") or ""
                                ).strip()
                                usage = res_data.get("usage", {})
                                in_tok = int(usage.get("prompt_tokens", 0) or 0)
                                out_tok = int(usage.get("completion_tokens", 0) or 0)
                                tot_tok = int(
                                    usage.get("total_tokens", 0) or (in_tok + out_tok)
                                )
                                if self.hass is not None and tot_tok:
                                    async_dispatcher_send(
                                        self.hass,
                                        f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                                        {
                                            "tokens": tot_tok,
                                            "input_tokens": in_tok,
                                            "output_tokens": out_tok,
                                            "cost_rub": _estimate_gigachat_cost_rub(
                                                candidate, tot_tok, in_tok, out_tok
                                            ),
                                            "model": candidate,
                                        },
                                    )
                                chat_log.async_add_assistant_content_without_tools(
                                    conversation.AssistantContent(
                                        agent_id=self.entity_id,
                                        content=reply_text,
                                    )
                                )
                                return reply_text
            if not self.auth_key:
                raise HomeAssistantError(
                    "Не удалось выполнить Vision-анализ изображения через Cloud.ru Foundation Models"
                )

        token = await self.async_get_access_token(is_speech=False)
        uploaded_file_ids: list[str] = []

        try:
            async with aiohttp.ClientSession() as session:
                for attachment in user_message.attachments or []:
                    mime_type = str(attachment.mime_type or "image/jpeg")
                    if not mime_type.startswith("image/"):
                        raise HomeAssistantError(
                            f"Поддерживаются только изображения (получен {mime_type})"
                        )
                    img_bytes = await self.hass.async_add_executor_job(
                        attachment.path.read_bytes
                    )
                    filename = attachment.path.name or "camera.jpg"

                    form = aiohttp.FormData()
                    form.add_field(
                        "file",
                        img_bytes,
                        filename=filename,
                        content_type=mime_type,
                    )
                    form.add_field("purpose", "general")

                    async with session.post(
                        f"{GIGACHAT_BASE_URL}/files",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/json",
                        },
                        data=form,
                        ssl=self.verify_ssl,
                        timeout=aiohttp.ClientTimeout(total=45),
                    ) as upload_resp:
                        if upload_resp.status != 200:
                            err_text = await upload_resp.text()
                            raise HomeAssistantError(
                                f"Ошибка загрузки изображения в GigaChat ({upload_resp.status}): {err_text}"
                            )
                        upload_json = await upload_resp.json()
                        file_id = upload_json.get("id")
                        if not file_id:
                            raise HomeAssistantError(
                                "GigaChat Files API не вернул идентификатор файла (id)"
                            )
                        uploaded_file_ids.append(str(file_id))

                vision_candidates = [
                    DEFAULT_SBER_VISION_MODEL,
                    "GigaChat-2-Max",
                    "GigaChat-Pro",
                    "GigaChat-Max",
                    "GigaChat-2",
                    "GigaChat",
                ]

                res_data = None
                used_model = DEFAULT_VISION_MODEL
                last_status = 0
                last_err = ""

                for candidate in vision_candidates:
                    payload = {
                        "model": candidate,
                        "messages": [
                            {
                                "role": "user",
                                "content": user_message.content
                                or "Опиши на русском языке, что изображено на снимке.",
                                "attachments": uploaded_file_ids,
                            }
                        ],
                        "stream": False,
                    }
                    async with session.post(
                        f"{GIGACHAT_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json=payload,
                        ssl=self.verify_ssl,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        if resp.status == 200:
                            res_data = await resp.json()
                            used_model = candidate
                            break
                        last_status = resp.status
                        last_err = await resp.text()

                for fid in uploaded_file_ids:
                    try:
                        async with session.post(
                            f"{GIGACHAT_BASE_URL}/files/{fid}/delete",
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Accept": "application/json",
                            },
                            ssl=self.verify_ssl,
                            timeout=aiohttp.ClientTimeout(total=10),
                        ):
                            pass
                    except Exception:  # noqa: BLE001
                        pass

                if res_data is None:
                    raise HomeAssistantError(
                        f"Ошибка GigaChat Vision ({last_status}): {last_err}"
                    )

                choices = res_data.get("choices", [])
                if not choices:
                    raise HomeAssistantError("Пустой ответ от GigaChat Vision")
                reply_text = (
                    choices[0].get("message", {}).get("content") or ""
                ).strip()

                usage = res_data.get("usage", {})
                in_tokens = int(usage.get("prompt_tokens", 0) or 0)
                out_tokens = int(usage.get("completion_tokens", 0) or 0)
                tot_tokens = int(
                    usage.get("total_tokens", 0) or (in_tokens + out_tokens)
                )
                if self.hass is not None and tot_tokens:
                    async_dispatcher_send(
                        self.hass,
                        f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                        {
                            "tokens": tot_tokens,
                            "input_tokens": in_tokens,
                            "output_tokens": out_tokens,
                            "cost_rub": _estimate_gigachat_cost_rub(
                                used_model, tot_tokens
                            ),
                            "model": used_model,
                        },
                    )

                chat_log.async_add_assistant_content_without_tools(
                    conversation.AssistantContent(
                        agent_id=self.entity_id,
                        content=reply_text,
                    )
                )
                return reply_text
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(
                f"Ошибка анализа изображения в GigaChat: {err}"
            ) from err

    @override
    async def _async_generate_image(
        self,
        task: ai_task.GenImageTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenImageTaskResult:
        """Handle a generate image task via GigaChat built-in Kandinsky (`text2image`)."""
        user_message = chat_log.content[-1]
        assert isinstance(user_message, conversation.UserContent)

        prompt = user_message.content.strip()
        if self.subentry.data.get(CONF_RECOMMENDED):
            image_model = DEFAULT_IMAGE_MODEL
        else:
            image_model = str(
                self.subentry.data.get(CONF_IMAGE_MODEL, DEFAULT_IMAGE_MODEL)
            ).strip()
        if not image_model:
            image_model = DEFAULT_IMAGE_MODEL

        token = await self.async_get_access_token(is_speech=False)
        candidates = [image_model]
        for fallback in ("GigaChat-2-Pro", "GigaChat-2", "GigaChat"):
            if fallback not in candidates:
                candidates.append(fallback)

        try:
            async with aiohttp.ClientSession() as session:
                res_data = None
                used_model = image_model
                last_status = 0
                last_err = ""

                for candidate in candidates:
                    payload = {
                        "model": candidate,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Ты — нейросеть-художник. Сгенерируй изображение "
                                    "по запросу пользователя с помощью встроенной функции text2image."
                                ),
                            },
                            {
                                "role": "user",
                                "content": f"Нарисуй: {prompt}",
                            },
                        ],
                        "function_call": "auto",
                    }
                    async with session.post(
                        f"{GIGACHAT_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json=payload,
                        ssl=self.verify_ssl,
                        timeout=aiohttp.ClientTimeout(total=120),
                    ) as resp:
                        if resp.status == 200:
                            res_data = await resp.json()
                            used_model = candidate
                            break
                        last_status = resp.status
                        last_err = await resp.text()

                if res_data is None:
                    raise HomeAssistantError(
                        f"Ошибка генерации изображения GigaChat ({last_status}): {last_err}"
                    )

                choices = res_data.get("choices", [])
                content = (
                    choices[0].get("message", {}).get("content", "")
                    if choices
                    else ""
                )
                match = _IMG_SRC_RE.search(content)
                if not match:
                    raise HomeAssistantError(
                        f"GigaChat не вернул тег <img src='...'> с идентификатором файла. Ответ: {content}"
                    )

                file_id = match.group(1)

                async with session.get(
                    f"{GIGACHAT_BASE_URL}/files/{file_id}/content",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/jpg",
                    },
                    ssl=self.verify_ssl,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as file_resp:
                    if file_resp.status != 200:
                        err_text = await file_resp.text()
                        raise HomeAssistantError(
                            f"Ошибка скачивания изображения из GigaChat ({file_resp.status}): {err_text}"
                        )
                    image_data = await file_resp.read()

                mime_type = (
                    "image/jpeg"
                    if image_data.startswith(b"\xff\xd8")
                    else "image/png"
                )

                usage = res_data.get("usage", {})
                tot_tokens = int(usage.get("total_tokens", 0) or 0)
                cost_rub = (
                    _estimate_gigachat_cost_rub(used_model, tot_tokens)
                    if tot_tokens
                    else 2.0
                )

                if self.hass is not None:
                    async_dispatcher_send(
                        self.hass,
                        f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                        {
                            "images": 1,
                            "cost_rub": cost_rub,
                            "model": used_model,
                        },
                    )

                chat_log.async_add_assistant_content_without_tools(
                    conversation.AssistantContent(
                        agent_id=self.entity_id,
                        content="Изображение сгенерировано.",
                    )
                )

                return ai_task.GenImageTaskResult(
                    image_data=image_data,
                    conversation_id=chat_log.conversation_id,
                    mime_type=mime_type,
                    model=used_model,
                )

        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"Ошибка генерации изображения: {err}") from err



