# Скриншоты для документации (README.md и API_KEY_GUIDE.md)

В этой папке (`images/`) находятся иллюстрации и скриншоты для `README.md` и `API_KEY_GUIDE.md`:

### Логотип и интерфейс Home Assistant (`README.md`):
- `logo.png` — фирменный логотип интеграции **Sber GigaChat AI**
- `services_overview.png` — общий вид интеграции **Sber GigaChat AI** в Home Assistant со списком всех 5 дочерних ИИ-служб (`GigaChat AI Task`, `GigaChat AI Task image`, `GigaChat Conversation`, `SaluteSpeech STT`, `SaluteSpeech TTS`) и кнопками добавления служб
- `device_diagnostics.png` — страница службы `GigaChat Conversation` с диагностическими сенсорами потраченных токенов и затрат в рублях (`₽`)
- `conversation_settings.png` — окно настроек диалогового агента `GigaChat Conversation` (системный промпт, управление Home Assistant, выбор модели, температура)
- `assist_pipeline.png` — окно настройки голосового ассистента (**Assist**) с выбранными `GigaChat Conversation`, `SaluteSpeech STT` и `SaluteSpeech TTS`
- `assist_chat.png` — пример диалога с ассистентом в Assist (запрос температуры в спальне с вызовом `GetLiveContext`)
- `ai_suggestions.png` — выбор `GigaChat AI Task` и `GigaChat AI Task image` в разделе «Предложения от ИИ» Home Assistant

### Инструкция по получению ключей (`API_KEY_GUIDE.md`):
- `cloud_ru_catalog.png` — каталог моделей GigaChat 3 и SaluteSpeech в Cloud.ru Evolution Foundation Models
- `cloud_ru_dashboard.png` — главная страница консоли Cloud.ru Evolution
- `cloud_ru_service_account.png` — создание сервисного аккаунта `home-assistant` в Cloud.ru
- `cloud_ru_roles.png` — назначение ролей проекта сервисному аккаунту в Cloud.ru
- `cloud_ru_speech_role.png` — добавление роли `SaluteSpeech -> smartspeech.admin` во вкладке «Другие сервисы»
- `cloud_ru_api_key.png` — созданный API-ключ Foundation Models (`Key Secret`) в Cloud.ru
- `sber_studio_freemium.png` — порядок предоставления доступа к моделям в Sber Studio (`developers.sber.ru/studio`) и Cloud.ru

