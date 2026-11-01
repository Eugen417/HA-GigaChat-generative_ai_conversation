"""AI Task integration for Sber GigaChat AI."""

from io import BytesIO
from json import JSONDecodeError
import logging
from pathlib import Path
import re
import subprocess
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
from .entity import (
    GigaChatBaseLLMEntity,
    _estimate_gigachat_cost_rub,
    _format_structured_output_instruction,
)

_LOGGER = logging.getLogger(__name__)
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def _normalize_image_bytes(
    raw_bytes: bytes, mime_type: str, filename: str
) -> tuple[bytes, str, str]:
    """Normalize image bytes to JPEG/PNG supported by both Sber Studio and Cloud.ru."""
    mime_clean = (mime_type or "image/jpeg").lower().strip()
    if mime_clean == "image/jpg":
        mime_clean = "image/jpeg"
    fname_clean = filename or "image.jpg"

    if mime_clean in ("image/jpeg", "image/png", "image/tiff", "image/bmp"):
        if not fname_clean.lower().endswith(
            (".jpg", ".jpeg", ".png", ".tiff", ".bmp")
        ):
            ext = ".png" if "png" in mime_clean else ".jpg"
            fname_clean = f"{fname_clean}{ext}"
        return raw_bytes, mime_clean, fname_clean

    try:
        from PIL import Image

        with Image.open(BytesIO(raw_bytes)) as img:
            rgb = img.convert("RGB")
            out = BytesIO()
            rgb.save(out, format="JPEG", quality=92)
            base_name = Path(fname_clean).stem or "image"
            return out.getvalue(), "image/jpeg", f"{base_name}.jpg"
    except Exception:  # noqa: BLE001
        return raw_bytes, "image/jpeg", f"{Path(fname_clean).stem or 'image'}.jpg"


def _extract_video_frame_sync(video_path: Path) -> bytes:
    """Extract a representative JPEG frame from a video attachment using ffmpeg or PyAV."""
    for seek_sec in ("00:00:01", "00:00:00"):
        try:
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    seek_sec,
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-f",
                    "image2",
                    "-vcodec",
                    "mjpeg",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=20,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout
        except Exception:  # noqa: BLE001
            pass

    try:
        import av
        from PIL import Image

        with av.open(str(video_path)) as container:
            for frame in container.decode(video=0):
                pil_img: Image.Image = frame.to_image()
                out = BytesIO()
                pil_img.convert("RGB").save(out, format="JPEG", quality=90)
                return out.getvalue()
    except Exception as err:  # noqa: BLE001
        raise HomeAssistantError(
            f"Не удалось извлечь кадр из видеофайла {video_path.name}: {err}"
        ) from err

    raise HomeAssistantError(
        f"Видеофайл {video_path.name} не содержит доступных видеокадров"
    )


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
            text = await self._async_analyze_attachments(
                last_msg, chat_log, task.structure
            )
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
        structure: Any | None = None,
    ) -> str:
        """Analyze multimodal attachments (images, video, audio, documents) like Google Gemini."""
        prompt_text = (
            user_message.content
            or "Опиши на русском языке содержимое вложения."
        )
        if structure is not None:
            prompt_text = f"{prompt_text}{_format_structured_output_instruction(structure)}"
        attachments = list(user_message.attachments or [])
        if not attachments:
            raise HomeAssistantError("Вложения не найдены")

        first_att = attachments[0]
        first_mime = str(first_att.mime_type or "").lower().strip()
        first_name = (first_att.path.name or "").lower()

        if first_mime.startswith("audio/") or first_name.endswith(
            (".ogg", ".oga", ".mp3", ".wav", ".m4a", ".flac", ".aac", ".opus")
        ):
            return await self._async_analyze_audio_attachment(
                first_att, prompt_text, chat_log
            )

        if (
            first_mime.startswith("text/")
            or first_mime
            in (
                "application/pdf",
                "application/json",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/epub+zip",
            )
            or first_name.endswith(
                (
                    ".pdf",
                    ".txt",
                    ".csv",
                    ".json",
                    ".yaml",
                    ".yml",
                    ".log",
                    ".md",
                    ".doc",
                    ".docx",
                    ".epub",
                )
            )
        ):
            return await self._async_analyze_document_attachment(
                first_att, prompt_text, chat_log
            )

        prepared_images: list[tuple[bytes, str, str]] = []
        for att in attachments:
            mime = str(att.mime_type or "image/jpeg").lower().strip()
            fname = att.path.name or "attachment.jpg"
            if mime.startswith("video/") or fname.lower().endswith(
                (".mp4", ".mov", ".webm", ".mkv", ".avi")
            ):
                frame_bytes = await self.hass.async_add_executor_job(
                    _extract_video_frame_sync, att.path
                )
                prepared_images.append(
                    (frame_bytes, "image/jpeg", f"{Path(fname).stem or 'video'}_frame.jpg")
                )
            elif mime.startswith("image/") or fname.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff")
            ):
                raw_bytes = await self.hass.async_add_executor_job(att.path.read_bytes)
                norm_item = await self.hass.async_add_executor_job(
                    _normalize_image_bytes, raw_bytes, mime, fname
                )
                prepared_images.append(norm_item)
            else:
                raise HomeAssistantError(
                    f"Неподдерживаемый тип вложения: {mime} ({fname})"
                )

        if self.cloud_ru_api_key and "ocr" in self.model.lower():
            return await self._async_ocr_with_deepseek(
                prepared_images, prompt_text, chat_log
            )

        prefer_sber = bool(self.auth_key) and (
            "/" not in self.model or not self.cloud_ru_api_key
        )

        if prefer_sber:
            try:
                return await self._async_analyze_images_sber(
                    prepared_images, prompt_text, chat_log
                )
            except Exception as sber_err:  # noqa: BLE001
                if not self.cloud_ru_api_key:
                    if isinstance(sber_err, HomeAssistantError):
                        raise
                    raise HomeAssistantError(
                        f"Ошибка анализа изображения в GigaChat: {sber_err}"
                    ) from sber_err
                _LOGGER.warning(
                    "Sber Studio Vision failed (%s), falling back to Cloud.ru VLM",
                    sber_err,
                )

        if self.cloud_ru_api_key:
            try:
                return await self._async_analyze_images_cloud_ru(
                    prepared_images, prompt_text, chat_log
                )
            except Exception as cloud_err:  # noqa: BLE001
                if not self.auth_key or prefer_sber:
                    if isinstance(cloud_err, HomeAssistantError):
                        raise
                    raise HomeAssistantError(
                        f"Ошибка Vision-анализа в Cloud.ru: {cloud_err}"
                    ) from cloud_err
                _LOGGER.warning(
                    "Cloud.ru VLM failed (%s), falling back to Sber Studio GigaChat Vision",
                    cloud_err,
                )

        return await self._async_analyze_images_sber(
            prepared_images, prompt_text, chat_log
        )

    async def _async_analyze_images_cloud_ru(
        self,
        prepared_images: list[tuple[bytes, str, str]],
        prompt_text: str,
        chat_log: conversation.ChatLog,
    ) -> str:
        """Analyze normalized image attachments via Cloud.ru Evolution Foundation Models VLM."""
        import base64

        content_parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": prompt_text,
            }
        ]
        for img_bytes, mime_type, _fname in prepared_images:
            b64_img = base64.b64encode(img_bytes).decode("utf-8")
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64_img}"},
                }
            )

        cloud_vision_candidates: list[str] = []
        if "/" in self.model and any(
            k in self.model.lower() for k in ("qwen", "kimi", "minimax")
        ):
            cloud_vision_candidates.append(self.model)
        for candidate_model in (
            DEFAULT_VISION_MODEL,
            "Qwen/Qwen3.6-35B-A3B",
            "Qwen/Qwen3.5-397B-A17B",
            "moonshotai/Kimi-K2.6",
            "MiniMaxAI/MiniMax-M3",
        ):
            if candidate_model not in cloud_vision_candidates:
                cloud_vision_candidates.append(candidate_model)

        last_status = 0
        last_err = ""
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
                            if not reply_text:
                                continue
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
                    last_status = resp.status
                    last_err = await resp.text()

        raise HomeAssistantError(
            f"Не удалось выполнить Vision-анализ через Cloud.ru ({last_status}): {last_err}"
        )

    async def _async_analyze_images_sber(
        self,
        prepared_images: list[tuple[bytes, str, str]],
        prompt_text: str,
        chat_log: conversation.ChatLog,
    ) -> str:
        """Analyze normalized image attachments via Sber Studio GigaChat Vision (/files + attachments)."""
        token = await self.async_get_access_token(is_speech=False)
        uploaded_file_ids: list[str] = []

        try:
            async with aiohttp.ClientSession() as session:
                for img_bytes, mime_type, filename in prepared_images:
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

                vision_candidates: list[str] = []
                if "/" not in self.model and "ultra" not in self.model.lower():
                    vision_candidates.append(self.model)
                for candidate_model in (
                    DEFAULT_SBER_VISION_MODEL,
                    "GigaChat-2-Pro",
                    "GigaChat-2-Max",
                    "GigaChat-2",
                    "GigaChat-Pro",
                    "GigaChat-Max",
                    "GigaChat",
                ):
                    if candidate_model not in vision_candidates:
                        vision_candidates.append(candidate_model)

                res_data = None
                used_model = DEFAULT_SBER_VISION_MODEL
                last_status = 0
                last_err = ""

                for candidate in vision_candidates:
                    payload = {
                        "model": candidate,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt_text,
                                "attachments": uploaded_file_ids[:1],
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

    async def _async_ocr_with_deepseek(
        self,
        prepared_images: list[tuple[bytes, str, str]],
        prompt_text: str,
        chat_log: conversation.ChatLog,
    ) -> str:
        """Extract text via DeepSeek-OCR-2 on Cloud.ru and answer user's prompt."""
        import base64

        content_parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": "Extract and transcribe all visible text from the image accurately.",
            }
        ]
        for img_bytes, mime_type, _fname in prepared_images:
            b64_img = base64.b64encode(img_bytes).decode("utf-8")
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64_img}"},
                }
            )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CLOUD_RU_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.cloud_ru_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "model": "deepseek-ai/DeepSeek-OCR-2",
                    "messages": [{"role": "user", "content": content_parts}],
                    "stream": False,
                },
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise HomeAssistantError(
                        f"Ошибка DeepSeek-OCR-2 ({resp.status}): {err_text}"
                    )
                res_data = await resp.json()

        choices = res_data.get("choices", [])
        raw_ocr = (
            (choices[0].get("message", {}).get("content") or "").strip()
            if choices
            else ""
        )
        if not raw_ocr or "\\text={" in raw_ocr or "Imagen de un" in raw_ocr:
            raise HomeAssistantError(
                "На изображении не обнаружено читаемого текста для OCR"
            )

        usage = res_data.get("usage", {})
        in_tok = int(usage.get("prompt_tokens", 0) or 0)
        out_tok = int(usage.get("completion_tokens", 0) or 0)
        tot_tok = int(usage.get("total_tokens", 0) or (in_tok + out_tok))
        if self.hass is not None and tot_tok:
            async_dispatcher_send(
                self.hass,
                f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                {
                    "tokens": tot_tok,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "cost_rub": (in_tok * 54.9 + out_tok * 61.0) / 1_000_000.0,
                    "model": "deepseek-ai/DeepSeek-OCR-2",
                },
            )

        try:
            async with aiohttp.ClientSession() as session:
                for llm_model in (
                    "GigaChat/GigaChat-3-Pro",
                    "ai-sage/GigaChat3-10B-A1.8B",
                ):
                    async with session.post(
                        f"{CLOUD_RU_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.cloud_ru_api_key}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json={
                            "model": llm_model,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "Ты помощник Home Assistant. Тебе передан распознанный OCR-текст с изображения. Выполни инструкцию пользователя на русском языке четко и по делу.",
                                },
                                {
                                    "role": "user",
                                    "content": f"Инструкция: {prompt_text}\n\nРаспознанный текст с изображения:\n{raw_ocr}",
                                },
                            ],
                            "stream": False,
                        },
                        timeout=aiohttp.ClientTimeout(total=45),
                    ) as llm_resp:
                        if llm_resp.status == 200:
                            llm_json = await llm_resp.json()
                            llm_choices = llm_json.get("choices", [])
                            if llm_choices:
                                formatted = (
                                    llm_choices[0].get("message", {}).get("content")
                                    or ""
                                ).strip()
                                if formatted:
                                    raw_ocr = formatted
                                    break
        except Exception:  # noqa: BLE001
            pass

        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(
                agent_id=self.entity_id,
                content=raw_ocr,
            )
        )
        return raw_ocr

    async def _async_analyze_audio_attachment(
        self,
        attachment: Any,
        prompt_text: str,
        chat_log: conversation.ChatLog,
    ) -> str:
        """Analyze an audio file attachment via Sber Studio GigaChat Audio or Cloud.ru STT + LLM."""
        audio_bytes = await self.hass.async_add_executor_job(attachment.path.read_bytes)
        mime_type = str(attachment.mime_type or "audio/ogg").lower().strip()
        filename = attachment.path.name or "audio.ogg"

        if self.auth_key:
            try:
                return await self._async_analyze_binary_file_sber(
                    audio_bytes, mime_type, filename, prompt_text, chat_log
                )
            except Exception as err:  # noqa: BLE001
                if not self.cloud_ru_api_key:
                    raise HomeAssistantError(
                        f"Ошибка анализа аудиофайла в GigaChat: {err}"
                    ) from err

        if self.cloud_ru_api_key:
            async with aiohttp.ClientSession() as session:
                for stt_model in ("GigaChat/GigaASR", "openai/whisper-large-v3"):
                    form = aiohttp.FormData()
                    form.add_field(
                        "file",
                        audio_bytes,
                        filename=filename,
                        content_type=mime_type,
                    )
                    form.add_field("model", stt_model)
                    form.add_field("language", "ru")
                    async with session.post(
                        f"{CLOUD_RU_BASE_URL}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self.cloud_ru_api_key}"},
                        data=form,
                        timeout=aiohttp.ClientTimeout(total=45),
                    ) as resp:
                        if resp.status == 200:
                            res_json = await resp.json()
                            transcript = (res_json.get("text") or "").strip()
                            if transcript:
                                reply = f"Расшифровка аудио: {transcript}"
                                chat_log.async_add_assistant_content_without_tools(
                                    conversation.AssistantContent(
                                        agent_id=self.entity_id,
                                        content=reply,
                                    )
                                )
                                return reply

        raise HomeAssistantError("Не удалось обработать аудиовложение")

    async def _async_analyze_document_attachment(
        self,
        attachment: Any,
        prompt_text: str,
        chat_log: conversation.ChatLog,
    ) -> str:
        """Analyze a document (.pdf, .docx, .txt, .csv, .json, .log) attachment."""
        raw_bytes = await self.hass.async_add_executor_job(attachment.path.read_bytes)
        mime_type = str(attachment.mime_type or "text/plain").lower().strip()
        filename = attachment.path.name or "document.txt"

        if mime_type.startswith("text/") or filename.lower().endswith(
            (".txt", ".csv", ".json", ".yaml", ".yml", ".log", ".md")
        ):
            doc_text = raw_bytes.decode("utf-8", errors="replace")[:50000]
            if self.auth_key:
                return await self._async_analyze_binary_file_sber(
                    doc_text.encode("utf-8"),
                    "text/plain",
                    filename if filename.lower().endswith(".txt") else f"{filename}.txt",
                    prompt_text,
                    chat_log,
                )

        if self.auth_key:
            return await self._async_analyze_binary_file_sber(
                raw_bytes, mime_type, filename, prompt_text, chat_log
            )

        raise HomeAssistantError(
            f"Для анализа документа {filename} требуется ключ Sber Studio (GigaChat Files API)"
        )

    async def _async_analyze_binary_file_sber(
        self,
        file_bytes: bytes,
        mime_type: str,
        filename: str,
        prompt_text: str,
        chat_log: conversation.ChatLog,
    ) -> str:
        """Upload binary file (audio/PDF/DOCX/TXT) to Sber Studio /files and analyze with GigaChat."""
        token = await self.async_get_access_token(is_speech=False)
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field(
                "file",
                file_bytes,
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
                        f"Ошибка загрузки файла в GigaChat ({upload_resp.status}): {err_text}"
                    )
                upload_json = await upload_resp.json()
                file_id = str(upload_json.get("id") or "")
                if not file_id:
                    raise HomeAssistantError(
                        "GigaChat Files API не вернул идентификатор файла (id)"
                    )

            try:
                res_data = None
                for candidate in (
                    "GigaChat-2-Pro",
                    "GigaChat-2-Max",
                    "GigaChat-2",
                    "GigaChat",
                ):
                    async with session.post(
                        f"{GIGACHAT_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json={
                            "model": candidate,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": prompt_text,
                                    "attachments": [file_id],
                                }
                            ],
                            "stream": False,
                        },
                        ssl=self.verify_ssl,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        if resp.status == 200:
                            res_data = await resp.json()
                            break
                if res_data is None:
                    raise HomeAssistantError(
                        "Не удалось проанализировать вложение в GigaChat"
                    )
                choices = res_data.get("choices", [])
                reply = (
                    (choices[0].get("message", {}).get("content") or "").strip()
                    if choices
                    else ""
                )
                chat_log.async_add_assistant_content_without_tools(
                    conversation.AssistantContent(
                        agent_id=self.entity_id,
                        content=reply,
                    )
                )
                return reply
            finally:
                try:
                    async with session.post(
                        f"{GIGACHAT_BASE_URL}/files/{file_id}/delete",
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



