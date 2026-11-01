"""Speech to text support for Sber GigaChat AI (SaluteSpeech STT)."""

from collections.abc import AsyncIterable
import base64
import json
import logging
import struct

import aiohttp

from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
    SpeechToTextEntity,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CLOUD_RU_BASE_URL,
    CONF_STT_LANGUAGE,
    CONF_STT_MODEL,
    DEFAULT_STT_LANGUAGE,
    DEFAULT_STT_MODEL,
    DOMAIN,
    GIGACHAT_BASE_URL,
    SALUTE_SPEECH_STT_URL,
    STT_LANGUAGES,
)
from .entity import GigaChatBaseLLMEntity

_LOGGER = logging.getLogger(__name__)
_SHORT_LANG_MAP = {"ru": "ru-RU", "en": "en-US", "kk": "kk-KZ"}


def _ensure_wav_header(pcm_bytes: bytes, sample_rate: int) -> bytes:
    """Wrap raw 16-bit mono PCM audio in a valid 44-byte RIFF WAV header."""
    if pcm_bytes.startswith(b"RIFF"):
        return pcm_bytes
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = len(pcm_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm_bytes


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up STT entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "stt":
            continue
        async_add_entities(
            [SaluteSpeechSTTEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class SaluteSpeechSTTEntity(SpeechToTextEntity, GigaChatBaseLLMEntity):
    """Sber SaluteSpeech speech-to-text entity."""

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the STT entity."""
        super().__init__(entry, subentry, DEFAULT_STT_MODEL)
        self._cloud_ru_stt_exhausted: bool = False

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        return STT_LANGUAGES

    @property
    def supported_formats(self) -> list[AudioFormats]:
        """Return a list of supported formats."""
        return [AudioFormats.WAV, AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[AudioCodecs]:
        """Return a list of supported codecs."""
        return [AudioCodecs.PCM, AudioCodecs.OPUS]

    @property
    def supported_bit_rates(self) -> list[AudioBitRates]:
        """Return a list of supported bitrates."""
        return [AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        """Return a list of supported samplerates."""
        return [
            AudioSampleRates.SAMPLERATE_8000,
            AudioSampleRates.SAMPLERATE_16000,
            AudioSampleRates.SAMPLERATE_48000,
        ]

    @property
    def supported_channels(self) -> list[AudioChannels]:
        """Return a list of supported channels."""
        return [AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Process an audio stream via Sber SaluteSpeech STT."""
        audio_data = b""
        async for chunk in stream:
            audio_data += chunk

        if not audio_data:
            return SpeechResult("", SpeechResultState.ERROR)

        is_ogg = (
            metadata.format == AudioFormats.OGG
            or metadata.codec == AudioCodecs.OPUS
            or str(metadata.format) == "ogg"
        )
        raw_rate = metadata.sample_rate
        sample_rate = int(raw_rate.value if hasattr(raw_rate, "value") else raw_rate)

        if is_ogg:
            content_type = "audio/ogg;codecs=opus"
            payload_bytes = audio_data
        else:
            content_type = f"audio/x-pcm;bit=16;rate={sample_rate}"
            if audio_data.startswith(b"RIFF") and len(audio_data) > 44:
                payload_bytes = audio_data[44:]
            else:
                payload_bytes = audio_data

        lang = metadata.language or self.subentry.data.get(
            CONF_STT_LANGUAGE, DEFAULT_STT_LANGUAGE
        )
        lang = _SHORT_LANG_MAP.get(lang, lang)
        model = str(self.subentry.data.get(CONF_STT_MODEL, DEFAULT_STT_MODEL))

        upload_bytes = (
            audio_data if is_ogg else _ensure_wav_header(audio_data, sample_rate)
        )

        # 1. Cloud.ru Evolution Foundation Models STT (GigaChat/GigaASR or openai/whisper-large-v3)
        if (
            self.cloud_ru_api_key
            and not self._cloud_ru_stt_exhausted
            and ("/" in model or not self.has_separate_speech_key)
        ):
            primary_model = model if "/" in model else "GigaChat/GigaASR"
            candidates = [primary_model]
            for fb in ("GigaChat/GigaASR", "openai/whisper-large-v3"):
                if fb not in candidates:
                    candidates.append(fb)
            short_lang = lang.split("-")[0]
            ext = "ogg" if is_ogg else "wav"
            mime = "audio/ogg" if is_ogg else "audio/wav"
            try:
                async with aiohttp.ClientSession() as session:
                    for cloud_model in candidates:
                        form = aiohttp.FormData()
                        form.add_field(
                            "file",
                            upload_bytes,
                            filename=f"speech.{ext}",
                            content_type=mime,
                        )
                        form.add_field("model", cloud_model)
                        form.add_field("language", short_lang)

                        async with session.post(
                            f"{CLOUD_RU_BASE_URL}/audio/transcriptions",
                            headers={"Authorization": f"Bearer {self.cloud_ru_api_key}"},
                            data=form,
                            timeout=aiohttp.ClientTimeout(total=30),
                        ) as resp:
                            if resp.status == 200:
                                res = await resp.json()
                                text = str(
                                    res.get("text") or res.get("result") or ""
                                ).strip()
                                if text:
                                    if self.hass is not None:
                                        async_dispatcher_send(
                                            self.hass,
                                            f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                                            {
                                                "requests": 1,
                                                "cost_rub": 0.05,
                                                "model": cloud_model,
                                            },
                                        )
                                    return SpeechResult(text, SpeechResultState.SUCCESS)
                            elif resp.status == 402:
                                self._cloud_ru_stt_exhausted = True
                                _LOGGER.info(
                                    "Cloud.ru STT requires ruble balance (402); "
                                    "switching to Sber Studio GigaChat Audio STT"
                                )
                                break
                            else:
                                err_text = await resp.text()
                                _LOGGER.warning(
                                    "Cloud.ru STT (%s) returned %s: %s",
                                    cloud_model,
                                    resp.status,
                                    err_text,
                                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Cloud.ru STT exception: %s", err)

        # 2. Sber Studio GigaChat Audio Recognition (/api/v1/files + attachments) using Freemium auth_key
        if self.auth_key and not self.has_separate_speech_key:
            giga_text = await self._async_sber_studio_gigachat_stt(
                upload_bytes, is_ogg
            )
            if giga_text:
                if self.hass is not None:
                    async_dispatcher_send(
                        self.hass,
                        f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                        {
                            "requests": 1,
                            "cost_rub": 0.0,
                            "model": "GigaChat-Audio",
                        },
                    )
                return SpeechResult(giga_text, SpeechResultState.SUCCESS)
            return SpeechResult("", SpeechResultState.ERROR)

        if not self.has_separate_speech_key:
            _LOGGER.error(
                "STT requires either a Sber Studio GigaChat Authorization Key, "
                "a Cloud.ru API Key (with ruble balance), or a SaluteSpeech Authorization Key"
            )
            return SpeechResult("", SpeechResultState.ERROR)

        sber_model = "general" if "/" in model else model
        params: dict[str, str] = {
            "language": lang,
            "model": sber_model,
        }

        try:
            token = await self.async_get_access_token(is_speech=True)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
                "Accept": "application/json",
            }
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    SALUTE_SPEECH_STT_URL,
                    headers=headers,
                    params=params,
                    data=payload_bytes,
                    ssl=self.verify_ssl,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp,
            ):
                if resp.status == 200:
                    res = await resp.json()
                    raw_result = res.get("result", "")
                    if isinstance(raw_result, list):
                        text = " ".join(
                            str(part) for part in raw_result if part
                        ).strip()
                    else:
                        text = str(raw_result or "").strip()

                    if text:
                        if self.hass is not None:
                            async_dispatcher_send(
                                self.hass,
                                f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                                {
                                    "requests": 1,
                                    "cost_rub": 0.15,
                                    "model": model,
                                },
                            )
                        return SpeechResult(text, SpeechResultState.SUCCESS)
                    _LOGGER.warning("SaluteSpeech STT returned empty result: %s", res)
                    return SpeechResult("", SpeechResultState.ERROR)

                err_text = await resp.text()
                _LOGGER.error("SaluteSpeech STT failed: %s %s", resp.status, err_text)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("SaluteSpeech STT exception: %s", err)

        return SpeechResult("", SpeechResultState.ERROR)

    async def _async_sber_studio_gigachat_stt(
        self, audio_bytes: bytes, is_ogg: bool
    ) -> str:
        """Recognize speech via Sber Studio GigaChat Audio API (/api/v1/files + attachments)."""
        try:
            token = await self.async_get_access_token(is_speech=False)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("GigaChat Audio STT OAuth failed: %s", err)
            return ""

        filename = "speech.ogg" if is_ogg else "speech.wav"
        mime_type = "audio/x-ogg" if is_ogg else "audio/x-wav"
        file_id: str | None = None

        try:
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field(
                    "file",
                    audio_bytes,
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
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as upload_resp:
                    if upload_resp.status != 200:
                        err_text = await upload_resp.text()
                        _LOGGER.error(
                            "GigaChat Audio file upload failed (%s): %s",
                            upload_resp.status,
                            err_text,
                        )
                        return ""
                    upload_json = await upload_resp.json()
                    file_id = str(upload_json.get("id") or "")
                    if not file_id:
                        return ""

                recognized = ""
                for candidate in ("GigaChat-2-Pro", "GigaChat-2-Max", "GigaChat-2", "GigaChat"):
                    payload = {
                        "model": candidate,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Ты — система распознавания речи (Speech-to-Text). "
                                    "Дословно расшифруй речь пользователя из прикреплённого аудиофайла на русском языке. "
                                    "Верни ТОЛЬКО распознанную фразу без кавычек, без комментариев и без пояснений. "
                                    "НЕ отвечай на вопрос из аудио, напиши только то, что произнёс человек."
                                ),
                            },
                            {
                                "role": "user",
                                "content": "Расшифруй аудиозапись дословно.",
                                "attachments": [file_id],
                            },
                        ],
                        "temperature": 0.01,
                        "max_tokens": 256,
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
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 200:
                            res_data = await resp.json()
                            choices = res_data.get("choices", [])
                            if choices:
                                recognized = (
                                    choices[0].get("message", {}).get("content") or ""
                                ).strip()
                                break
                        else:
                            err_text = await resp.text()
                            _LOGGER.debug(
                                "GigaChat Audio STT (%s) returned %s: %s",
                                candidate,
                                resp.status,
                                err_text,
                            )

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

                recognized = recognized.strip().strip("\"'«»")
                _LOGGER.info("GigaChat Audio STT recognized: %s", recognized)
                return recognized
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("GigaChat Audio STT exception: %s", err)
            return ""
        """Recognize speech using Cloud.ru /v1/realtime WebSocket (`GigaChat/GigaASR`)."""
        ws_url = "wss://foundation-models.api.cloud.ru/v1/realtime?model=GigaChat/GigaASR"
        headers = {
            "Authorization": f"Bearer {self.cloud_ru_api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        transcript_parts: list[str] = []

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.ws_connect(
                    ws_url,
                    headers=headers,
                    timeout=25.0,
                ) as ws,
            ):
                for offset in range(0, len(pcm_bytes), 32768):
                    chunk_b64 = base64.b64encode(
                        pcm_bytes[offset : offset + 32768]
                    ).decode("ascii")
                    await ws.send_json(
                        {"type": "input_audio_buffer.append", "audio": chunk_b64}
                    )
                await ws.send_json({"type": "input_audio_buffer.commit"})
                await ws.send_json(
                    {
                        "type": "response.create",
                        "response": {"modalities": ["text"]},
                    }
                )

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        ev_type = data.get("type", "")
                        if ev_type == "session.created":
                            _LOGGER.debug(
                                "Cloud.ru GigaASR session.created: %s", data
                            )
                        elif ev_type in (
                            "conversation.item.input_audio_transcription.completed",
                            "response.audio_transcript.done",
                            "response.text.done",
                            "response.output_text.done",
                        ):
                            t = str(
                                data.get("transcript") or data.get("text") or ""
                            ).strip()
                            if t:
                                return t
                        elif ev_type in (
                            "conversation.item.input_audio_transcription.delta",
                            "response.audio_transcript.delta",
                            "response.text.delta",
                            "response.output_text.delta",
                        ):
                            if d := data.get("delta"):
                                transcript_parts.append(str(d))
                        elif ev_type == "response.done":
                            resp_obj = data.get("response", {})
                            for item in resp_obj.get("output", []):
                                for c in item.get("content", []):
                                    if t := c.get("transcript") or c.get("text"):
                                        return str(t).strip()
                            break
                        elif ev_type == "error":
                            _LOGGER.warning(
                                "Cloud.ru GigaASR Realtime error: %s", data
                            )
                            break
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Cloud.ru GigaASR Realtime exception: %s", err)

        return "".join(transcript_parts).strip()

