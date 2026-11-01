"""Config flow for Sber GigaChat AI integration."""

from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_LLM_HASS_API, CONF_NAME, CONF_PROMPT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import llm
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CHAT_MODEL_LABELS,
    CHAT_MODELS,
    CONF_AUTH_KEY,
    CONF_CHAT_MODEL,
    CONF_CLOUD_RU_API_KEY,
    CONF_IMAGE_MODEL,
    CONF_MAX_TOKENS,
    CONF_RECOMMENDED,
    CONF_SCOPE,
    CONF_SPEECH_AUTH_KEY,
    CONF_SPEECH_SCOPE,
    CONF_STT_LANGUAGE,
    CONF_STT_MODEL,
    CONF_TEMPERATURE,
    CONF_TTS_VOICE,
    CONF_VERIFY_SSL,
    DEFAULT_AI_TASK_IMAGE_NAME,
    DEFAULT_AI_TASK_NAME,
    DEFAULT_CHAT_MODEL,
    DEFAULT_CONVERSATION_NAME,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_PROMPT,
    DEFAULT_SBER_STUDIO_CHAT_MODEL,
    DEFAULT_SCOPE,
    DEFAULT_SPEECH_SCOPE,
    DEFAULT_STT_LANGUAGE,
    DEFAULT_STT_MODEL,
    DEFAULT_STT_NAME,
    DEFAULT_TITLE,
    DEFAULT_TTS_NAME,
    DEFAULT_TTS_VOICE,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    GIGACHAT_SCOPE_LABELS,
    GIGACHAT_SCOPES,
    IMAGE_MODEL_LABELS,
    IMAGE_MODELS,
    RECOMMENDED_AI_TASK_IMAGE_OPTIONS,
    RECOMMENDED_AI_TASK_OPTIONS,
    RECOMMENDED_CONVERSATION_OPTIONS,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_STT_OPTIONS,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TTS_OPTIONS,
    SALUTE_SPEECH_SCOPE_LABELS,
    SALUTE_SPEECH_SCOPES,
    STT_LANGUAGES,
    STT_MODELS,
)


class GigaChatAIConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sber GigaChat AI."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            has_cloud_ru = bool(str(user_input.get(CONF_CLOUD_RU_API_KEY, "")).strip())
            has_sber_studio = bool(str(user_input.get(CONF_AUTH_KEY, "")).strip())
            if not has_cloud_ru and not has_sber_studio:
                errors["base"] = "missing_credentials"
            else:
                name = user_input.pop("name", DEFAULT_TITLE)
                default_conv = RECOMMENDED_CONVERSATION_OPTIONS.copy()
                default_task = RECOMMENDED_AI_TASK_OPTIONS.copy()
                if not has_cloud_ru and has_sber_studio:
                    default_conv[CONF_CHAT_MODEL] = DEFAULT_SBER_STUDIO_CHAT_MODEL
                    default_task[CONF_CHAT_MODEL] = DEFAULT_SBER_STUDIO_CHAT_MODEL

                subentries: list[dict[str, Any]] = [
                    {
                        "subentry_type": "conversation",
                        "data": default_conv,
                        "title": DEFAULT_CONVERSATION_NAME,
                        "unique_id": None,
                    },
                    {
                        "subentry_type": "ai_task_data",
                        "data": default_task,
                        "title": DEFAULT_AI_TASK_NAME,
                        "unique_id": None,
                    },
                    {
                        "subentry_type": "ai_task_image",
                        "data": RECOMMENDED_AI_TASK_IMAGE_OPTIONS,
                        "title": DEFAULT_AI_TASK_IMAGE_NAME,
                        "unique_id": None,
                    },
                ]
                if has_cloud_ru or str(user_input.get(CONF_SPEECH_AUTH_KEY, "")).strip():
                    subentries.extend(
                        [
                            {
                                "subentry_type": "tts",
                                "data": RECOMMENDED_TTS_OPTIONS,
                                "title": DEFAULT_TTS_NAME,
                                "unique_id": None,
                            },
                            {
                                "subentry_type": "stt",
                                "data": RECOMMENDED_STT_OPTIONS,
                                "title": DEFAULT_STT_NAME,
                                "unique_id": None,
                            },
                        ]
                    )
                return self.async_create_entry(
                    title=name,
                    data=user_input,
                    subentries=subentries,
                )

        scope_choices = [
            SelectOptionDict(label=GIGACHAT_SCOPE_LABELS.get(s, s), value=s)
            for s in GIGACHAT_SCOPES
        ]
        speech_scope_choices = [
            SelectOptionDict(label=SALUTE_SPEECH_SCOPE_LABELS.get(s, s), value=s)
            for s in SALUTE_SPEECH_SCOPES
        ]

        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=DEFAULT_TITLE): TextSelector(),
                    vol.Optional(CONF_CLOUD_RU_API_KEY, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_AUTH_KEY, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_SCOPE, default=DEFAULT_SCOPE): SelectSelector(
                        SelectSelectorConfig(
                            options=scope_choices,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_SPEECH_AUTH_KEY, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(
                        CONF_SPEECH_SCOPE, default=DEFAULT_SPEECH_SCOPE
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=speech_scope_choices,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL
                    ): BooleanSelector(),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow reconfiguring API keys on the main integration entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            has_cloud_ru = bool(str(user_input.get(CONF_CLOUD_RU_API_KEY, "")).strip())
            has_sber_studio = bool(str(user_input.get(CONF_AUTH_KEY, "")).strip())
            if not has_cloud_ru and not has_sber_studio:
                errors["base"] = "missing_credentials"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=user_input,
                )

        scope_choices = [
            SelectOptionDict(label=GIGACHAT_SCOPE_LABELS.get(s, s), value=s)
            for s in GIGACHAT_SCOPES
        ]
        speech_scope_choices = [
            SelectOptionDict(label=SALUTE_SPEECH_SCOPE_LABELS.get(s, s), value=s)
            for s in SALUTE_SPEECH_SCOPES
        ]
        cur = entry.data

        return self.async_show_form(
            step_id="reconfigure",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CLOUD_RU_API_KEY,
                        default=cur.get(CONF_CLOUD_RU_API_KEY, ""),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    vol.Optional(
                        CONF_AUTH_KEY,
                        default=cur.get(CONF_AUTH_KEY, ""),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    vol.Optional(
                        CONF_SCOPE,
                        default=cur.get(CONF_SCOPE, DEFAULT_SCOPE),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=scope_choices,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_SPEECH_AUTH_KEY,
                        default=cur.get(CONF_SPEECH_AUTH_KEY, ""),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    vol.Optional(
                        CONF_SPEECH_SCOPE,
                        default=cur.get(CONF_SPEECH_SCOPE, DEFAULT_SPEECH_SCOPE),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=speech_scope_choices,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_VERIFY_SSL,
                        default=cur.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                    ): BooleanSelector(),
                }
            ),
        )

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        return {
            "conversation": GigaChatAISubentryFlowHandler,
            "stt": GigaChatAISubentryFlowHandler,
            "tts": GigaChatAISubentryFlowHandler,
            "ai_task_data": GigaChatAISubentryFlowHandler,
            "ai_task_image": GigaChatAISubentryFlowHandler,
        }


class GigaChatAISubentryFlowHandler(ConfigSubentryFlow):
    """Flow for managing Sber GigaChat AI subentries."""

    last_rendered_recommended: bool = True

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return self.source == "user"

    async def async_step_set_options(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Set subentry options."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        if user_input is None:
            if self._is_new:
                if self._subentry_type == "tts":
                    options = RECOMMENDED_TTS_OPTIONS.copy()
                elif self._subentry_type == "stt":
                    options = RECOMMENDED_STT_OPTIONS.copy()
                elif self._subentry_type == "ai_task_data":
                    options = RECOMMENDED_AI_TASK_OPTIONS.copy()
                elif self._subentry_type == "ai_task_image":
                    options = RECOMMENDED_AI_TASK_IMAGE_OPTIONS.copy()
                else:
                    options = RECOMMENDED_CONVERSATION_OPTIONS.copy()
            else:
                options = self._get_reconfigure_subentry().data.copy()

            self.last_rendered_recommended = bool(
                options.get(CONF_RECOMMENDED, True)
            )
        else:
            if (
                CONF_RECOMMENDED in user_input
                and bool(user_input[CONF_RECOMMENDED]) != self.last_rendered_recommended
            ):
                self.last_rendered_recommended = bool(user_input[CONF_RECOMMENDED])
                base_opts = (
                    {}
                    if self._is_new
                    else self._get_reconfigure_subentry().data.copy()
                )
                options = {**base_opts, **user_input}
                schema = _gigachat_config_option_schema(
                    self.hass, self._is_new, self._subentry_type, options
                )
                return self.async_show_form(
                    step_id="set_options",
                    data_schema=vol.Schema(schema),
                )

            if user_input.get(CONF_LLM_HASS_API) is None:
                user_input.pop(CONF_LLM_HASS_API, None)

            if user_input.get(CONF_RECOMMENDED):
                if self._subentry_type in ("conversation", "ai_task_data"):
                    user_input[CONF_CHAT_MODEL] = DEFAULT_CHAT_MODEL
                    user_input[CONF_TEMPERATURE] = RECOMMENDED_TEMPERATURE
                    user_input[CONF_MAX_TOKENS] = RECOMMENDED_MAX_TOKENS
                elif self._subentry_type == "ai_task_image":
                    user_input[CONF_IMAGE_MODEL] = DEFAULT_IMAGE_MODEL

            if self._is_new:
                return self.async_create_entry(
                    title=user_input.pop(CONF_NAME),
                    data=user_input,
                )

            entry = self._get_entry()
            result = self.async_update_and_abort(
                entry,
                self._get_reconfigure_subentry(),
                data=user_input,
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(entry.entry_id)
            )
            return result

        schema = _gigachat_config_option_schema(
            self.hass, self._is_new, self._subentry_type, options
        )
        return self.async_show_form(
            step_id="set_options",
            data_schema=vol.Schema(schema),
        )

    async_step_reconfigure = async_step_set_options
    async_step_user = async_step_set_options


def _gigachat_config_option_schema(
    hass: HomeAssistant,
    is_new: bool,
    subentry_type: str,
    options: Mapping[str, Any],
) -> dict[Any, Any]:
    """Return a schema for Sber GigaChat AI subentry options."""
    if is_new:
        if subentry_type == "tts":
            default_name = DEFAULT_TTS_NAME
        elif subentry_type == "stt":
            default_name = DEFAULT_STT_NAME
        elif subentry_type == "ai_task_data":
            default_name = DEFAULT_AI_TASK_NAME
        elif subentry_type == "ai_task_image":
            default_name = DEFAULT_AI_TASK_IMAGE_NAME
        else:
            default_name = DEFAULT_CONVERSATION_NAME
        schema: dict[Any, Any] = {
            vol.Required(CONF_NAME, default=default_name): str,
        }
    else:
        schema = {}

    chat_model_choices = [
        SelectOptionDict(label=CHAT_MODEL_LABELS.get(m, m), value=m)
        for m in CHAT_MODELS
    ]
    image_model_choices = [
        SelectOptionDict(label=IMAGE_MODEL_LABELS.get(m, m), value=m)
        for m in IMAGE_MODELS
    ]

    if subentry_type == "conversation":
        hass_apis = [
            SelectOptionDict(label=api.name, value=api.id)
            for api in llm.async_get_apis(hass)
        ]
        suggested_apis = options.get(CONF_LLM_HASS_API, [llm.LLM_API_ASSIST])
        if isinstance(suggested_apis, str):
            suggested_apis = [suggested_apis] if suggested_apis != "none" else []
        elif not isinstance(suggested_apis, list):
            suggested_apis = []
        known_apis = {api.id for api in llm.async_get_apis(hass)}
        suggested_apis = [a for a in suggested_apis if a in known_apis]

        schema.update(
            {
                vol.Optional(
                    CONF_PROMPT,
                    description={
                        "suggested_value": options.get(CONF_PROMPT, DEFAULT_PROMPT)
                    },
                    default=options.get(CONF_PROMPT, DEFAULT_PROMPT),
                ): TemplateSelector(),
                vol.Optional(
                    CONF_LLM_HASS_API,
                    description={"suggested_value": suggested_apis},
                    default=suggested_apis,
                ): SelectSelector(
                    SelectSelectorConfig(options=hass_apis, multiple=True)
                ),
                vol.Optional(
                    CONF_RECOMMENDED,
                    default=options.get(CONF_RECOMMENDED, True),
                ): BooleanSelector(),
            }
        )
        if not options.get(CONF_RECOMMENDED, True):
            schema.update(
                {
                    vol.Optional(
                        CONF_CHAT_MODEL,
                        default=options.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=chat_model_choices,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                    vol.Optional(
                        CONF_TEMPERATURE,
                        default=options.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0.0, max=2.0, step=0.05, mode=NumberSelectorMode.SLIDER
                        )
                    ),
                    vol.Optional(
                        CONF_MAX_TOKENS,
                        default=options.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=100, max=8000, step=100, mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            )

    elif subentry_type == "stt":
        stt_model_choices = [SelectOptionDict(label=m, value=m) for m in STT_MODELS]
        stt_lang_choices = [
            SelectOptionDict(label=lang, value=lang) for lang in STT_LANGUAGES
        ]
        schema.update(
            {
                vol.Optional(
                    CONF_STT_MODEL,
                    default=options.get(CONF_STT_MODEL, DEFAULT_STT_MODEL),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=stt_model_choices,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                ),
                vol.Optional(
                    CONF_STT_LANGUAGE,
                    default=options.get(CONF_STT_LANGUAGE, DEFAULT_STT_LANGUAGE),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=stt_lang_choices,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
    elif subentry_type == "tts":
        voice_choices = [
            SelectOptionDict(label="Наталья (Женский, 24 кГц)", value="Nec_24000"),
            SelectOptionDict(label="Борис (Мужской, 24 кГц)", value="Bys_24000"),
            SelectOptionDict(label="Марфа (Женский, 24 кГц)", value="May_24000"),
            SelectOptionDict(label="Тарас (Мужской, 24 кГц)", value="Tur_24000"),
            SelectOptionDict(label="Александра (Женский, 24 кГц)", value="Ost_24000"),
            SelectOptionDict(label="Сергей (Мужской, 24 кГц)", value="Pon_24000"),
            SelectOptionDict(label="Kira (en-US, 24 kHz)", value="Kin_24000"),
            SelectOptionDict(label="Наталья (8 кГц)", value="Nec_8000"),
            SelectOptionDict(label="Борис (8 кГц)", value="Bys_8000"),
            SelectOptionDict(label="Марфа (8 кГц)", value="May_8000"),
            SelectOptionDict(label="Тарас (8 кГц)", value="Tur_8000"),
            SelectOptionDict(label="Александра (8 кГц)", value="Ost_8000"),
            SelectOptionDict(label="Сергей (8 кГц)", value="Pon_8000"),
            SelectOptionDict(label="Kira (en-US, 8 kHz)", value="Kin_8000"),
        ]
        schema.update(
            {
                vol.Optional(
                    CONF_TTS_VOICE,
                    default=options.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=voice_choices, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
            }
        )
    elif subentry_type == "ai_task_data":
        schema.update(
            {
                vol.Optional(
                    CONF_RECOMMENDED,
                    default=options.get(CONF_RECOMMENDED, True),
                ): BooleanSelector(),
            }
        )
        if not options.get(CONF_RECOMMENDED, True):
            schema.update(
                {
                    vol.Optional(
                        CONF_CHAT_MODEL,
                        default=options.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=chat_model_choices,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                    vol.Optional(
                        CONF_TEMPERATURE,
                        default=options.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0.0, max=2.0, step=0.05, mode=NumberSelectorMode.SLIDER
                        )
                    ),
                    vol.Optional(
                        CONF_MAX_TOKENS,
                        default=options.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=100, max=8000, step=100, mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            )
    elif subentry_type == "ai_task_image":
        schema.update(
            {
                vol.Optional(
                    CONF_RECOMMENDED,
                    default=options.get(CONF_RECOMMENDED, True),
                ): BooleanSelector(),
            }
        )
        if not options.get(CONF_RECOMMENDED, True):
            schema.update(
                {
                    vol.Optional(
                        CONF_IMAGE_MODEL,
                        default=options.get(CONF_IMAGE_MODEL, DEFAULT_IMAGE_MODEL),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=image_model_choices,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                }
            )

    return schema




