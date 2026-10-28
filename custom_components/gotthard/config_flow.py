"""Config flow to configure the Gotthard integration."""

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from custom_components.gotthard.const import (
    API_KEY_URL,
    CONF_API_KEY,
    CONF_COUNTERS,
    CONF_COUNTERS_API_KEY,
    CONF_RADIUS,
    CONF_RESTRICTIONS,
    DEFAULT_RADIUS,
    DOMAIN,
    TITLE,
)
from custom_components.gotthard.counters import (
    Counters,
    CountersAuthError,
    CountersError,
)
from custom_components.gotthard.datex import AuthError, Datex, DatexError

_LOGGER = logging.getLogger(__name__)

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


class GotthardFlowHandler(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GotthardOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # There is only one Gotthard.
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors = {}
        if user_input is not None:
            errors = await self._async_check(user_input[CONF_API_KEY])
            if not errors:
                return self.async_create_entry(title=TITLE, data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"api_key_url": API_KEY_URL},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            errors = await self._async_check(user_input[CONF_API_KEY])
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"api_key_url": API_KEY_URL},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """A new key for the traffic messages, before the old one is refused:
        keys expire, and are rotated. The counters' key is in the options."""
        errors = {}
        if user_input is not None:
            errors = await self._async_check(user_input[CONF_API_KEY])
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data_updates=user_input
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"api_key_url": API_KEY_URL},
        )

    async def _async_check(self, api_key: str) -> dict[str, str]:
        """Errors of the form, from trying the key."""
        try:
            await Datex(async_get_clientsession(self.hass), api_key).async_get_status()
        except AuthError:
            return {"base": "invalid_auth"}
        except DatexError as err:
            _LOGGER.warning("Cannot check the API key: %s", err)
            return {"base": "cannot_connect"}
        return {}


class GotthardOptionsFlow(OptionsFlow):
    """Restrictions in the calendars, and the traffic counters (with their own
    key): both off unless turned on here."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}
        options = self.config_entry.options
        if user_input is not None:
            enabled = user_input.get(CONF_COUNTERS, False)
            api_key = (user_input.get(CONF_COUNTERS_API_KEY) or "").strip()
            if enabled and not api_key:
                errors[CONF_COUNTERS_API_KEY] = "counters_key_required"
            elif enabled:
                try:
                    await Counters(
                        async_get_clientsession(self.hass), api_key
                    ).async_get()
                except CountersAuthError:
                    errors["base"] = "invalid_auth"
                except CountersError as err:
                    _LOGGER.warning("Cannot check the counters key: %s", err)
                    errors["base"] = "cannot_connect"
            if not errors:
                # Turned off, the key is kept for turning them on again.
                return self.async_create_entry(
                    data={
                        CONF_RADIUS: user_input.get(CONF_RADIUS, DEFAULT_RADIUS),
                        CONF_RESTRICTIONS: user_input.get(CONF_RESTRICTIONS, False),
                        CONF_COUNTERS: enabled,
                        CONF_COUNTERS_API_KEY: api_key,
                    }
                )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RADIUS, default=options.get(CONF_RADIUS, DEFAULT_RADIUS)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=300,
                        step=5,
                        unit_of_measurement="km",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_RESTRICTIONS, default=options.get(CONF_RESTRICTIONS, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_COUNTERS, default=options.get(CONF_COUNTERS, False)
                ): BooleanSelector(),
                vol.Optional(
                    CONF_COUNTERS_API_KEY,
                    description={"suggested_value": options.get(CONF_COUNTERS_API_KEY)},
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"api_key_url": API_KEY_URL},
        )
