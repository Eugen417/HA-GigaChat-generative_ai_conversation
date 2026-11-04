"""Constants for the Sber GigaChat AI integration."""

from typing import Any

from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT, Platform
from homeassistant.helpers import llm

DOMAIN = "gigachat_generative_ai_conversation"

CONF_CLOUD_RU_API_KEY = "cloud_ru_api_key"
CONF_AUTH_KEY = "auth_key"
CONF_SCOPE = "scope"
CONF_SPEECH_AUTH_KEY = "speech_auth_key"
CONF_SPEECH_SCOPE = "speech_scope"
CONF_VERIFY_SSL = "verify_ssl"

CONF_RECOMMENDED = "recommended"
CONF_CHAT_MODEL = "chat_model"
CONF_IMAGE_MODEL = "image_model"
CONF_TEMPERATURE = "temperature"
CONF_MAX_TOKENS = "max_tokens"

CONF_TTS_VOICE = "tts_voice"

CONF_STT_MODEL = "stt_model"
CONF_STT_LANGUAGE = "stt_language"

DEFAULT_TITLE = "Sber GigaChat AI"
DEFAULT_CONVERSATION_NAME = "GigaChat Conversation"
DEFAULT_STT_NAME = "SaluteSpeech STT"
DEFAULT_TTS_NAME = "SaluteSpeech TTS"
DEFAULT_AI_TASK_NAME = "GigaChat AI Task"
DEFAULT_AI_TASK_IMAGE_NAME = "GigaChat AI Task image"

DEFAULT_SCOPE = "GIGACHAT_API_PERS"
DEFAULT_SPEECH_SCOPE = "SALUTE_SPEECH_PERS"
DEFAULT_VERIFY_SSL = False

GIGACHAT_SCOPES = [
    "GIGACHAT_API_PERS",
    "GIGACHAT_API_B2B",
    "GIGACHAT_API_CORP",
]

GIGACHAT_SCOPE_LABELS: dict[str, str] = {
    "GIGACHAT_API_PERS": "GIGACHAT_API_PERS (Физические лица)",
    "GIGACHAT_API_B2B": "GIGACHAT_API_B2B (ИП и юрлица — платные пакеты)",
    "GIGACHAT_API_CORP": "GIGACHAT_API_CORP (ИП и юрлица — pay-as-you-go)",
}

SALUTE_SPEECH_SCOPES = [
    "SALUTE_SPEECH_PERS",
    "SALUTE_SPEECH_CORP",
    "SALUTE_SPEECH_B2B",
]

SALUTE_SPEECH_SCOPE_LABELS: dict[str, str] = {
    "SALUTE_SPEECH_PERS": "SALUTE_SPEECH_PERS (Физические лица)",
    "SALUTE_SPEECH_CORP": "SALUTE_SPEECH_CORP (Корпоративный)",
    "SALUTE_SPEECH_B2B": "SALUTE_SPEECH_B2B (Пакетный B2B)",
}

DEFAULT_PROMPT = (
    "Ты голосовой помощник для умного дома Home Assistant.\n"
    "Отвечай просто, кратко и по делу обычным текстом на русском языке.\n"
    "ВАЖНО: В системном промпте перечислены только названия устройств без их текущих значений. "
    "При ЛЮБОМ вопросе о температуре, влажности, состоянии датчиков или устройств "
    "ОБЯЗАТЕЛЬНО сначала вызови инструмент GetLiveContext (или homeassistant__GetLiveContext) "
    "и назови точное значение из ответа инструмента. Никогда не отвечай просто названием датчика!\n"
    "Для включения и выключения устройств обязательно вызывай инструменты HassTurnOn / HassTurnOff."
)

DEFAULT_CHAT_MODEL = "GigaChat-2-Pro"
DEFAULT_SBER_STUDIO_CHAT_MODEL = "GigaChat-2-Pro"
DEFAULT_IMAGE_MODEL = "GigaChat-2-Pro"
DEFAULT_VISION_MODEL = "Qwen/Qwen3.6-35B-A3B"
DEFAULT_SBER_VISION_MODEL = "GigaChat-2-Pro"
DEFAULT_STT_MODEL = "GigaChat/GigaASR"
DEFAULT_STT_LANGUAGE = "ru-RU"
DEFAULT_TTS_VOICE = "Nec_24000"

RECOMMENDED_TEMPERATURE = 0.3
RECOMMENDED_MAX_TOKENS = 2000

CHAT_MODELS = [
    "GigaChat-2-Pro",
    "GigaChat-3-Ultra",
    "GigaChat-2-Max",
    "GigaChat-2",
    "GigaChat",
    "GigaChat/GigaChat-3-Pro",
    "ai-sage/GigaChat3.5-432B-A28B-Reasoning",
    "ai-sage/GigaChat3-10B-A1.8B",
    "Qwen/Qwen3.6-35B-A3B",
    "Qwen/Qwen3.5-397B-A17B",
    "moonshotai/Kimi-K2.6",
    "deepseek-ai/DeepSeek-OCR-2",
    "deepseek-ai/DeepSeek-V4-Pro",
    "zai-org/GLM-5.1",
]

CHAT_MODEL_LABELS: dict[str, str] = {
    "GigaChat/GigaChat-3-Pro": "GigaChat 3 Pro [Cloud.ru] (73 / 176 ₽ за 1M — рекомендуется для УД)",
    "ai-sage/GigaChat3.5-432B-A28B-Reasoning": "GigaChat 3.5 432B Reasoning [Cloud.ru] (96 / 288 ₽ за 1M — флагман)",
    "ai-sage/GigaChat3-10B-A1.8B": "GigaChat 3 10B [Cloud.ru] (12.2 ₽ за 1M — сверхбыстрая и дешёвая)",
    "Qwen/Qwen3.6-35B-A3B": "Qwen 3.6 35B Vision [Cloud.ru] (220 / 329 ₽ за 1M — Vision и УД)",
    "Qwen/Qwen3.5-397B-A17B": "Qwen 3.5 397B Vision [Cloud.ru] (анализ камер и УД)",
    "moonshotai/Kimi-K2.6": "Kimi K2.6 Vision [Cloud.ru] (анализ камер и УД)",
    "deepseek-ai/DeepSeek-OCR-2": "DeepSeek OCR 2 [Cloud.ru] (55 / 61 ₽ за 1M — OCR документов, чеков и счётчиков)",
    "deepseek-ai/DeepSeek-V4-Pro": "DeepSeek V4 Pro [Cloud.ru] (Function Calling + Reasoning)",
    "zai-org/GLM-5.1": "GLM 5.1 [Cloud.ru] (198 / 829 ₽ за 1M)",
    "GigaChat-3-Ultra": "GigaChat 3 Ultra [Sber Studio] (Freemium 50M — модель для УД)",
    "GigaChat-2-Pro": "GigaChat 2 Pro [Sber Studio] (0.50 ₽ / 1K, Freemium 40M — УД и Vision)",
    "GigaChat-2-Max": "GigaChat 2 Max [Sber Studio] (0.65 ₽ / 1K, Freemium 25M — макс. точность и Vision)",
    "GigaChat-2": "GigaChat 2 Lite [Sber Studio] (0.065 ₽ / 1K, Freemium 250M)",
    "GigaChat": "GigaChat Lite [Sber Studio] (0.065 ₽ / 1K, Freemium 250M)",
}

IMAGE_MODELS = [
    "GigaChat-2-Pro",
    "GigaChat-2-Max",
    "GigaChat-2",
    "GigaChat",
]

IMAGE_MODEL_LABELS: dict[str, str] = {
    "GigaChat-2-Pro": "Kandinsky 3.1 через GigaChat 2 Pro [Sber Studio]",
    "GigaChat-2-Max": "Kandinsky 3.1 через GigaChat 2 Max [Sber Studio]",
    "GigaChat-2": "Kandinsky 3.1 через GigaChat 2 Lite [Sber Studio]",
    "GigaChat": "Kandinsky 3.1 через GigaChat Lite [Sber Studio]",
}

STT_MODELS = [
    "GigaChat/GigaASR",
    "openai/whisper-large-v3",
    "general",
    "callcenter",
]

STT_LANGUAGES = [
    "ru-RU",
    "en-US",
    "kk-KZ",
]

TTS_VOICES: dict[str, list[tuple[str, str]]] = {
    "ru-RU": [
        ("Bab-Freespeech", "SaluteSpeech Cloud.ru (Bab-Freespeech, 24 кГц)"),
        ("Nec_24000", "Наталья (Женский, 24 кГц)"),
        ("Bys_24000", "Борис (Мужской, 24 кГц)"),
        ("May_24000", "Марфа (Женский, 24 кГц)"),
        ("Tur_24000", "Тарас (Мужской, 24 кГц)"),
        ("Ost_24000", "Александра (Женский, 24 кГц)"),
        ("Pon_24000", "Сергей (Мужской, 24 кГц)"),
        ("Nec_8000", "Наталья (8 кГц)"),
        ("Bys_8000", "Борис (8 кГц)"),
        ("May_8000", "Марфа (8 кГц)"),
        ("Tur_8000", "Тарас (8 кГц)"),
        ("Ost_8000", "Александра (8 кГц)"),
        ("Pon_8000", "Сергей (8 кГц)"),
    ],
    "en-US": [
        ("Kin_24000", "Kira (Female, 24 kHz)"),
        ("Kin_8000", "Kira (Female, 8 kHz)"),
    ],
}

TTS_LANGUAGES = list(TTS_VOICES.keys())

RECOMMENDED_CONVERSATION_OPTIONS: dict[str, Any] = {
    CONF_RECOMMENDED: True,
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: DEFAULT_PROMPT,
    CONF_CHAT_MODEL: DEFAULT_CHAT_MODEL,
    CONF_TEMPERATURE: RECOMMENDED_TEMPERATURE,
    CONF_MAX_TOKENS: RECOMMENDED_MAX_TOKENS,
}

RECOMMENDED_STT_OPTIONS: dict[str, Any] = {
    CONF_STT_MODEL: DEFAULT_STT_MODEL,
    CONF_STT_LANGUAGE: DEFAULT_STT_LANGUAGE,
}

RECOMMENDED_TTS_OPTIONS: dict[str, Any] = {
    CONF_TTS_VOICE: DEFAULT_TTS_VOICE,
}

RECOMMENDED_AI_TASK_OPTIONS: dict[str, Any] = {
    CONF_RECOMMENDED: True,
    CONF_CHAT_MODEL: DEFAULT_CHAT_MODEL,
    CONF_TEMPERATURE: RECOMMENDED_TEMPERATURE,
    CONF_MAX_TOKENS: RECOMMENDED_MAX_TOKENS,
}

RECOMMENDED_AI_TASK_IMAGE_OPTIONS: dict[str, Any] = {
    CONF_RECOMMENDED: True,
    CONF_IMAGE_MODEL: DEFAULT_IMAGE_MODEL,
}

CLOUD_RU_BASE_URL = "https://foundation-models.api.cloud.ru/v1"
OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_BASE_URL = "https://gigachat.devices.sberbank.ru/api/v1"
GIGACHAT_ULTRA_BASE_URL = "https://api.giga.chat/v1"
SALUTE_SPEECH_TTS_URL = "https://smartspeech.sber.ru/rest/v1/text:synthesize"
SALUTE_SPEECH_STT_URL = "https://smartspeech.sber.ru/rest/v1/speech:recognize"

PLATFORMS = [
    Platform.CONVERSATION,
    Platform.STT,
    Platform.TTS,
    Platform.AI_TASK,
    Platform.SENSOR,
]
