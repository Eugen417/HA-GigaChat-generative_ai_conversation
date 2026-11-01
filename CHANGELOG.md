# Changelog

Все значимые изменения проекта документируются в этом файле.

## [1.2.0] - 2026-10-31

### Добавлено
- Гибридная поддержка двух платформ Сбера: **Cloud.ru Evolution Foundation Models** (`https://foundation-models.api.cloud.ru/v1`) и **Sber Studio** (`https://gigachat.devices.sberbank.ru/api/v1`) с возможностью обновления ключей через меню **«Настроить» (`reconfigure`)**.
- Архитектура из 5 дочерних служб (`ConfigSubentry`) и `ChatLog` по образцу официальных интеграций `Google Gemini`, `Ollama` и `HA-Yandex-generative_ai_conversation`:
  - **`GigaChat Conversation`** — диалоговый агент на базе **GigaChat 2 Pro / Max / Lite** и **GigaChat 3 Pro / Ultra / 3.5 Reasoning** с полноценным управлением умным домом (Native Function Calling, нормализация JSON Schema `anyOf`/`oneOf`, поддержка `functions_state_id` и защита от повторных вызовов инструментов).
  - **`GigaASR / SaluteSpeech STT`** — гибридное распознавание речи с автоматическим фоллбэком: Cloud.ru (`GigaChat/GigaASR`, `openai/whisper-large-v3`), мультимодальный **Sber Studio GigaChat Audio STT** (`/api/v1/files` + `GigaChat-2-Pro`) и прямой SaluteSpeech API (`smartspeech.sber.ru`).
  - **`SaluteSpeech TTS`** — синтез речи через **Cloud.ru Realtime WebSocket API** (`wss://foundation-models.api.cloud.ru/v1/realtime?model=GigaChat/SaluteSpeech`, голос `Bab-Freespeech`) и классический SaluteSpeech API (`smartspeech.sber.ru`).
  - **`GigaChat AI Task`** (`ai_task_data`) — генерация текста, структурированных JSON-данных и **мультимодальный анализ изображений и камер (`SUPPORT_ATTACHMENTS`)** через GigaChat Vision (`/api/v1/files` + `attachments`) и Vision-модели Cloud.ru (`Qwen3.6`, `Kimi-K2.6`).
  - **`GigaChat AI Task image`** (`ai_task_image`) — генерация изображений через встроенную нейросеть **Kandinsky 3.1** (`text2image` внутри GigaChat API).
- Автоматическое получение и кэширование OAuth 2.0 токенов Sber NGW (`https://ngw.devices.sberbank.ru:9443/api/v2/oauth`) с опцией отключения проверки сертификата НУЦ Минцифры (`verify_ssl=False` по умолчанию) для работы в контейнере Home Assistant «из коробки».
- Платформа диагностических сенсоров **`sensor.py`** для каждой службы: счётчики потраченных токенов, сгенерированных изображений, озвученных символов, запросов STT и расчётных затрат в рублях (`RUB`) с сохранением состояния (`RestoreSensor`).
- Поддержка диагностики (`diagnostics.py`) со скрытием секретных ключей.
- Полная локализация интерфейса настроек на русский и английский языки.

