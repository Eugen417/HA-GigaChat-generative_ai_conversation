# Changelog

Все значимые изменения проекта документируются в этом файле.

## [1.2.5] - 2026-11-04

### Исправлено
- **Исправлена ошибка `404: {"status":404,"message":"No such model"}` при ручном выборе модели в настройках**:
  - Для модели **`GigaChat-3-Ultra`** добавлена поддержка нового базового адреса **`https://api.giga.chat/v1/chat/completions`** (согласно официальной документации Сбера) с автоматическим переключением между шлюзами `api.giga.chat` и `gigachat.devices.sberbank.ru`.
  - Архивные модели 1-го поколения (`GigaChat-Pro`, `GigaChat-Max`), отключённые в API Сбера, убраны из выпадающего списка и автоматически перенаправляются на `GigaChat-2-Pro` / `GigaChat-2-Max`.
  - Добавлен автоматический фоллбэк на доступные модели (`GigaChat-2-Max` / `GigaChat-2-Pro` / `GigaChat-2`) при снятой галочке «Рекомендуемые настройки модели», если выбранная модель недоступна для текущего тарифа.
- **Исправлено управление светом и устройствами на модели `GigaChat-2-Pro`**:
  - Убрана принудительная блокировка инструментов (`force_no_tools`) после вызова `GetLiveContext`, которая мешала `GigaChat-2-Pro` вторым шагом вызывать `HassTurnOn` / `HassTurnOff` / `HassLightSet`.

## [1.2.4] - 2026-11-03

### Обновлено
- Актуализированы тарифы моделей **Sber Studio** для физических лиц (вступившие в силу с 1 сентября 2026 года):
  - `GigaChat-2` / `GigaChat` (Lite): **0.065 ₽ / 1K** (пакет 20 млн токенов за 1 300 ₽ + **250 млн токенов в Freemium**);
  - `GigaChat-2-Pro` / `GigaChat-Pro` (Pro): **0.50 ₽ / 1K** (пакет 3 млн токенов за 1 500 ₽ + **40 млн токенов в Freemium**);
  - `GigaChat-2-Max` / `GigaChat-Max` (Max): **0.65 ₽ / 1K** (пакет 3 млн токенов за 1 950 ₽ + **25 млн токенов в Freemium**);
  - `GigaChat-3-Ultra` (Ultra): **0.00 ₽ / 1K** (**50 млн токенов в Freemium**).
- В `README.md` и `API_KEY_GUIDE.md` добавлена сводная таблица тарифов и разъяснение о том, что диагностические сенсоры **`Затраты (RUB)`** показывают ориентировочный расчётный показатель без учёта бесплатных квот Freemium (365 млн токенов), стартовых бонусов Cloud.ru и кэширования промптов.

## [1.2.3] - 2026-11-01

### Исправлено
- Исправлен экспорт функции `_format_structured_output_instruction` из `entity.py` в `ai_task.py`, вызывавший `ImportError` при загрузке платформы `ai_task`.

## [1.2.2] - 2026-11-01

### Добавлено и исправлено
- **Мультимодальная обработка вложений в `GigaChat AI Task` (по архитектуре Google Gemini)**:
  - Все вложения (`attachments`) в `ai_task.generate_data` обрабатываются выбранной мультимодальной моделью через **GigaChat Files API (`POST /api/v1/files` + `attachments`)** или VLM Cloud.ru с полной поддержкой структурированного JSON-ответа (`task.structure`).
  - Поддерживаются изображения (`JPEG`, `PNG`, `WebP`, `GIF`, `BMP`, `TIFF`), документы (`PDF`, `DOCX`, `DOC`, `TXT`, `CSV`, `JSON`), аудиофайлы (`OGG`, `MP3`, `WAV`, `M4A`, `FLAC`) и видеоролики с камер (`MP4`, `MOV`, `WebM`, `MKV`).
  - Специализированная модель `deepseek-ai/DeepSeek-OCR-2` добавлена в список моделей настроек `AI Task` для выделенных OCR-служб и исключена из автоматического списка Vision-моделей для камер.

## [1.2.1] - 2026-11-01

### Обновлено
- Добавлена кнопка быстрой установки репозитория в HACS (`My Home Assistant`), расширена документация по гибридному режиму ключей (`Cloud.ru` + `Sber Studio`) и добавлены скриншоты всех 5 служб, диагностики и настроек `Assist` / `AI Task`.
- Обновлён `manifest.json` для полной совместимости с проверками **Hassfest** и **HACS Validation**.

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

