# Changelog

Все значимые изменения проекта документируются в этом файле.

## [1.2.11] - 2026-11-04

### Оптимизация стоимости и скорости (Рекомендуемые модели по умолчанию)
- **`GigaChat AI Task image` (`DEFAULT_IMAGE_MODEL`) переведена по умолчанию на `GigaChat-2` (Lite)**:
  - Генерация изображений всегда выполняется встроенной моделью **Kandinsky 3.1 (`text2image`)** с одинаковым качеством, но вызов через `GigaChat-2` (Lite) использует бесплатный пакет **250 000 000 токенов Freemium** (и тариф **0.065 ₽ / 1K** — в **7.7 раза дешевле**, чем `GigaChat-2-Pro`).
- **Распознавание речи `GigaChat Audio STT` (`stt.py`) оптимизировано под `GigaChat-2` (Lite)**:
  - При расшифровке голосовых команд через Sber Studio теперь первой используется быстрая модель **`GigaChat-2` (Lite)** (250M бесплатных токенов, `0.065 ₽ / 1K`) с автоматическим фоллбэком на `GigaChat-2-Pro`, что экономит квоту `Pro` (40M токенов) для управления умным домом и анализа камер.

## [1.2.10] - 2026-11-04

### Исправлено и улучшено
- **Мгновенный возврат к рекомендуемой модели при включении тумблера «Рекомендуемые настройки модели» (`config_flow.py`, `__init__.py`, `const.py`, `sensor.py`, `entity.py`)**:
  - При включении переключателя `Рекомендуемые настройки модели` настройки теперь сохраняются с первого нажатия кнопки «Отправить» (без повторного открытия формы) и сбрасывают выбранную вручную модель на рекомендуемую (`get_recommended_model`) с учётом реально введённых API-ключей.
  - Добавлена принудительная синхронизация поля `model` в `device_registry` при каждой перезагрузке интеграции, чтобы подпись модели на карточках служб (`GigaChat Conversation`, `GigaChat AI Task` и др.) сразу обновлялась при переключении между ручным и рекомендуемым режимами.
- **Живая синхронизация каталога моделей Cloud.ru (`GET /v1/models` — `listModels`)**:
  - При открытии настроек служб автоматически опрашивается `GET https://foundation-models.api.cloud.ru/v1/models` и синхронизируются внутренние модели `Cloud.ru` (`MiniMaxAI/MiniMax-M3`, `openai/gpt-oss-120b`, `Qwen/Qwen3-Coder-Next` и др.) и их актуальные цены.

## [1.2.9] - 2026-11-04

### Добавлено и исправлено
- **Добавлены все 9 официальных голосов `GigaChat/SaluteSpeech` в Cloud.ru и обновлён протокол WebSocket `/v1/realtime` (`tts.py`, `const.py`)**:
  - Подключены все 9 голосов модели `GigaChat/SaluteSpeech` (`Bab-Freespeech`, `Bab-Energetic`, `Bab-Debate`, `Mer-Operator`, `Kaz-Lifelike`, `Tsb-Freespeech`, `Tsb-Hesitating`, `Gli-Freespeech`, `Gli-Operator`) с передачей голоса через `response.audio.output.voice` и текста через `response.input` (`input_text`).
- **Скрытие моделей и голосов для неактивированных ключей (`config_flow.py`, `tts.py`)**:
  - Если не заполнен архивный ключ SaluteSpeech (Поле 3), в настройках `TTS` и `STT` не отображаются модели и голоса `smartspeech.sber.ru` (`SaluteSpeech Classic`, `general`, `callcenter`).
  - В настройках `Conversation` и `AI Task` отображаются только модели тех платформ (`[Cloud.ru]` и/или `[Sber Studio]`), для которых реально введены ключи.

## [1.2.8] - 2026-11-04

### Изменено и исправлено
- **Архитектура `SaluteSpeech TTS` приведена к стандарту Google Gemini (`tts_model` -> динамический список голосов)**:
  - В настройках ⚙️ службы `SaluteSpeech TTS` теперь выбирается **Модель синтеза речи (`tts_model`)**:
    - `GigaChat/SaluteSpeech` — Realtime Preview в Cloud.ru (24 кГц, голос `Bab-Freespeech`);
    - `SaluteSpeech` — классическая модель в Sber Studio (`smartspeech.sber.ru`, 24 / 8 кГц).
  - В настройках Голосового помощника (**Assist -> Преобразование текста в речь -> Голос**) список голосов (`async_get_supported_voices`) теперь динамически формируется строго под выбранную модель `tts_model`:
    - для `GigaChat/SaluteSpeech` отображается её единственный реальный голос **`Варвара / Bab-Freespeech (24 кГц)`**;
    - для `SaluteSpeech` отображаются все классические голоса (**Наталья, Борис, Марфа, Тарас, Александра, Сергей, Kira**).

## [1.2.7] - 2026-11-04

### Исправлено
- **Исправлено переключение голосов в `SaluteSpeech TTS` (`tts.py`, `const.py`, `config_flow.py`)**:
  - Убрана заглушка в `_async_cloud_ru_realtime_tts`, из-за которой выбранные голоса (`Наталья`, `Борис`, `Марфа`, `Тарас`, `Александра`, `Сергей`) игнорировались и заменялись на `Bab-Freespeech`.
  - Добавлено автоматическое преобразование кодов голосов в формат движка `gigatts` (`Nec-Freespeech`, `Bys-Freespeech`, `May-Freespeech`, `Tur-Freespeech`, `Ost-Freespeech`, `Pon-Freespeech`, `Kin-Freespeech`) с передачей в `session.voice` и `session.gigatts.voice`.
  - При работе через Cloud.ru `/v1/realtime` (24 кГц) из выпадающего списка Голосовых ассистентов автоматически скрываются 8-килогерцовые голоса (`*_8000`), предназначенные только для архивного REST API `smartspeech.sber.ru`.
  - Синхронизирован список голосов в окне настроек службы `SaluteSpeech TTS` (`config_flow.py`).

## [1.2.6] - 2026-11-04

### Исправлено и проверено
- Проверены все модели каталогов **Cloud.ru Foundation Models** и **Sber Studio** (`GigaChat/GigaChat-3-Pro`, `ai-sage/GigaChat3.5-432B-A28B-Reasoning`, `ai-sage/GigaChat3-10B-A1.8B`, `Qwen/Qwen3.6-35B-A3B`, `Qwen/Qwen3.5-397B-A17B`, `moonshotai/Kimi-K2.6`, `deepseek-ai/DeepSeek-OCR-2`, `deepseek-ai/DeepSeek-V4-Pro`, `zai-org/GLM-5.1`, `MiniMaxAI/MiniMax-M3`, `GigaChat-3-Ultra`, `GigaChat-2-Max`, `GigaChat-2-Pro`, `GigaChat-2`):
  - Добавлено свойство `self.model` в `GigaChatBaseLLMEntity` для корректного определения выбранной модели в `GigaChat AI Task` при анализе вложений и камер.
  - Расширен автоматический фоллбэк с любой модели `[Cloud.ru]` на `Sber Studio` при наличии обоих ключей.
  - Уточнены коэффициенты расчёта стоимости (`_estimate_gigachat_cost_rub`) для всех моделей Cloud.ru.

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

