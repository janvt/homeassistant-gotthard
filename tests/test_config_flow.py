"""Setting up the Gotthard and renewing its API key."""

from http import HTTPStatus

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.gotthard.const import (
    CONF_API_KEY,
    CONF_COUNTERS,
    CONF_COUNTERS_API_KEY,
    CONF_RESTRICTIONS,
    DOMAIN,
)
from custom_components.gotthard.datex import URL

from .conftest import API_KEY


async def test_user(hass, feed):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: API_KEY}
    assert result["title"] == "Gotthard Tunnel Traffic"
    assert feed.mock_calls[0][3]["Authorization"] == f"Bearer {API_KEY}"


async def test_user_invalid_key(hass, aioclient_mock):
    aioclient_mock.post(URL, status=HTTPStatus.UNAUTHORIZED)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_cannot_connect(hass, aioclient_mock):
    aioclient_mock.post(URL, status=HTTPStatus.BAD_GATEWAY)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_only_one_gotthard(hass, entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass, entry, feed):
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {CONF_API_KEY: "new-key"}


# ── the traffic counters, opt in in the options ─────────────────────────────
async def test_counters_off_by_default(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = {str(key): key for key in result["data_schema"].schema}
    assert schema[CONF_COUNTERS].default() is False


async def test_turning_counters_on_needs_their_key(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_COUNTERS: True}
    )
    assert result["errors"] == {CONF_COUNTERS_API_KEY: "counters_key_required"}


async def test_turning_counters_on(hass, entry, feed, counters):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_COUNTERS: True, CONF_COUNTERS_API_KEY: " counters-key "},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_RESTRICTIONS: False,
        CONF_COUNTERS: True,
        CONF_COUNTERS_API_KEY: "counters-key",
    }


async def test_counters_key_refused(hass, entry, aioclient_mock):
    from custom_components.gotthard.counters import URL as COUNTERS_URL

    aioclient_mock.post(COUNTERS_URL, status=HTTPStatus.FORBIDDEN)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_COUNTERS: True, CONF_COUNTERS_API_KEY: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_turning_counters_off_keeps_the_key(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_COUNTERS: False, CONF_COUNTERS_API_KEY: "kept"}
    )
    assert entry.options == {
        CONF_RESTRICTIONS: False,
        CONF_COUNTERS: False,
        CONF_COUNTERS_API_KEY: "kept",
    }


async def test_restrictions_off_by_default(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = {str(key): key for key in result["data_schema"].schema}
    assert schema[CONF_RESTRICTIONS].default() is False
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_RESTRICTIONS: True, CONF_COUNTERS: False}
    )
    assert entry.options[CONF_RESTRICTIONS] is True
