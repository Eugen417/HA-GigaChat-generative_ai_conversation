"""Text to speech support for Sber GigaChat AI (SaluteSpeech TTS)."""

import base64
from collections.abc import Mapping
import json
import logging
import struct
from typing import Any

import aiohttp

from homeassistant.components.tts import (
    ATTR_VOICE,
    TextToSpeechEntity,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CLOUD_RU_BASE_URL,
    CONF_TTS_MODEL,
    CONF_TTS_VOICE,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
    DOMAIN,
    SALUTE_SPEECH_TTS_URL,
    TTS_VOICES_BY_MODEL,
)
from .entity import GigaChatBaseLLMEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up TTS entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "tts":
            continue
        async_add_entities(
            [SaluteSpeechTTSEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class SaluteSpeechTTSEntity(TextToSpeechEntity, GigaChatBaseLLMEntity):
    """Sber SaluteSpeech text-to-speech entity."""

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the TTS entity."""
        super().__init__(entry, subentry, DEFAULT_TTS_MODEL)
        self._unsupported_cloud_voices: set[str] = set()

    def _active_tts_model(self) -> str:
        """Return the active TTS model ('GigaChat/SaluteSpeech' or 'SaluteSpeech')."""
        configured = self.subentry.data.get(CONF_TTS_MODEL)
        if configured in TTS_VOICES_BY_MODEL:
            return str(configured)
        if self.has_separate_speech_key and not self.cloud_ru_api_key:
            return "SaluteSpeech"
        return DEFAULT_TTS_MODEL

    @property
    def default_language(self) -> str:
        """Return the default language."""
        return "ru-RU"

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages for the selected TTS model."""
        model_voices = TTS_VOICES_BY_MODEL.get(
            self._active_tts_model(), TTS_VOICES_BY_MODEL[DEFAULT_TTS_MODEL]
        )
        return list(model_voices.keys())

    @property
    def supported_options(self) -> list[str]:
        """Return list of supported options like voice."""
        return [ATTR_VOICE]

    @property
    def default_options(self) -> Mapping[str, Any]:
        """Return a mapping with the default options for the active TTS model."""
        active_model = self._active_tts_model()
        if active_model == "GigaChat/SaluteSpeech":
            return {ATTR_VOICE: "Bab-Freespeech"}
        saved_voice = str(self.subentry.data.get(CONF_TTS_VOICE) or "Nec_24000")
        if saved_voice == "Bab-Freespeech":
            saved_voice = "Nec_24000"
        return {ATTR_VOICE: saved_voice}

    @callback
    def async_get_supported_voices(self, language: str) -> list[Voice] | None:
        """Return a list of supported voices for the active TTS model and language."""
        model_voices = TTS_VOICES_BY_MODEL.get(
            self._active_tts_model(), TTS_VOICES_BY_MODEL[DEFAULT_TTS_MODEL]
        )
        if not (voices := model_voices.get(language)):
            return None
        return [Voice(voice_id, voice_name) for voice_id, voice_name in voices]

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Load TTS audio from Cloud.ru Realtime or Sber SaluteSpeech REST API."""
        active_model = self._active_tts_model()
        default_voice = (
            "Bab-Freespeech"
            if active_model == "GigaChat/SaluteSpeech"
            else "Nec_24000"
        )
        voice = str(options.get(ATTR_VOICE) or default_voice)

        params = {
            "format": "wav16",
            "voice": voice if voice != "Bab-Freespeech" else "Nec_24000",
        }

        use_cloud_ru = bool(self.cloud_ru_api_key) and (
            active_model == "GigaChat/SaluteSpeech" or not self.has_separate_speech_key
        )

        # Cloud.ru Evolution Foundation Models TTS (`GigaChat/SaluteSpeech` via /v1/realtime WS)
        if use_cloud_ru:
            audio_wav = await self._async_cloud_ru_realtime_tts(message, voice)
            if audio_wav:
                if self.hass is not None:
                    chars = len(message)
                    async_dispatcher_send(
                        self.hass,
                        f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                        {
                            "chars": chars,
                            "cost_rub": chars * 0.41 / 1000.0,
                            "model": "GigaChat/SaluteSpeech (Bab-Freespeech)",
                        },
                    )
                return ("wav", audio_wav)
            if not self.has_separate_speech_key:
                return (None, None)

        if not self.has_separate_speech_key:
            _LOGGER.error(
                "TTS requires either a Cloud.ru API Key or a Sber Studio SaluteSpeech Authorization Key"
            )
            return (None, None)

        try:
            token = await self.async_get_access_token(is_speech=True)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/text",
            }
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    SALUTE_SPEECH_TTS_URL,
                    headers=headers,
                    params=params,
                    data=message.encode("utf-8"),
                    ssl=self.verify_ssl,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp,
            ):
                if resp.status == 200:
                    audio = await resp.read()
                    if self.hass is not None:
                        chars = len(message)
                        async_dispatcher_send(
                            self.hass,
                            f"{DOMAIN}_usage_{self.subentry.subentry_id}",
                            {
                                "chars": chars,
                                "cost_rub": chars * 1.20 / 1000.0,
                                "model": voice,
                            },
                        )
                    return ("wav", audio)

                text = await resp.text()
                _LOGGER.error(
                    "SaluteSpeech TTS failed (%s): %s %s", voice, resp.status, text
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("SaluteSpeech TTS exception: %s", err)

        return (None, None)

    async def _async_cloud_ru_realtime_tts(
        self, message: str, voice: str
    ) -> bytes | None:
        """Synthesize speech using Cloud.ru /v1/realtime WebSocket (`GigaChat/SaluteSpeech`)."""
        ws_url = "wss://foundation-models.api.cloud.ru/v1/realtime?model=GigaChat/SaluteSpeech"
        headers = {
            "Authorization": f"Bearer {self.cloud_ru_api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        sample_rate = 24000
        # Map classic SaluteSpeech voice codes (e.g. Bys_24000) to Cloud.ru gigatts format (Bys-Freespeech)
        prefix = voice.split("_")[0].split("-")[0] if voice else "Bab"
        freespeech_voice = (
            voice if "Freespeech" in voice else f"{prefix}-Freespeech"
        )
        candidates: list[str | None] = []
        if (
            freespeech_voice != "Bab-Freespeech"
            and freespeech_voice not in self._unsupported_cloud_voices
        ):
            candidates.append(freespeech_voice)
        candidates.append(None)

        for voice_candidate in candidates:
            audio_chunks: list[bytes] = []
            had_voice_error = False
            try:
                async with (
                    aiohttp.ClientSession() as session,
                    session.ws_connect(
                        ws_url,
                        headers=headers,
                        timeout=25.0,
                    ) as ws,
                ):
                    if voice_candidate:
                        await ws.send_json(
                            {
                                "type": "session.update",
                                "session": {
                                    "voice": voice_candidate,
                                    "output_audio_format": "pcm16",
                                    "modalities": ["audio", "text"],
                                    "gigatts": {
                                        "voice": voice_candidate,
                                        "lang": "auto",
                                        "content_type": "text",
                                    },
                                },
                            }
                        )

                    await ws.send_json(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "text", "text": message}],
                            },
                        }
                    )

                    resp_cfg: dict[str, Any] = {
                        "modalities": ["audio", "text"],
                        "instructions": message,
                    }
                    if voice_candidate:
                        resp_cfg["voice"] = voice_candidate

                    await ws.send_json(
                        {
                            "type": "response.create",
                            "response": resp_cfg,
                        }
                    )

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            audio_chunks.append(msg.data)
                        elif msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            ev_type = data.get("type", "")
                            if ev_type == "session.created":
                                _LOGGER.debug(
                                    "Cloud.ru Realtime session.created: %s", data
                                )
                            elif ev_type in (
                                "response.audio.delta",
                                "response.output_audio.delta",
                                "audio.delta",
                            ):
                                if b64 := data.get("delta") or data.get("audio"):
                                    audio_chunks.append(base64.b64decode(b64))
                            elif ev_type in (
                                "response.audio.done",
                                "response.output_audio.done",
                                "response.done",
                                "error",
                            ):
                                if ev_type == "error":
                                    err_obj = data.get("error", {})
                                    if err_obj.get("param") == "audio.output.voice":
                                        had_voice_error = True
                                        if voice_candidate:
                                            self._unsupported_cloud_voices.add(
                                                voice_candidate
                                            )
                                            _LOGGER.info(
                                                "Cloud.ru SaluteSpeech Preview does not support voice '%s' (%s); "
                                                "falling back to default voice 'Bab-Freespeech'",
                                                voice_candidate,
                                                err_obj.get("message", ""),
                                            )
                                    else:
                                        _LOGGER.warning(
                                            "Cloud.ru Realtime TTS error event: %s",
                                            data,
                                        )
                                break
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Cloud.ru Realtime TTS WebSocket failed: %s", err)
                return None

            if audio_chunks:
                raw_audio = b"".join(audio_chunks)
                if raw_audio.startswith(b"RIFF"):
                    return raw_audio
                data_size = len(raw_audio)
                wav_header = struct.pack(
                    "<4sI4s4sIHHIIHH4sI",
                    b"RIFF",
                    36 + data_size,
                    b"WAVE",
                    b"fmt ",
                    16,
                    1,
                    1,
                    sample_rate,
                    sample_rate * 2,
                    2,
                    16,
                    b"data",
                    data_size,
                )
                return wav_header + raw_audio

            if not had_voice_error:
                break

        return None
