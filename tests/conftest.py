"""Shared fixtures."""

from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gotthard.const import CONF_API_KEY, DOMAIN, NAME
from custom_components.gotthard.datex import URL

FIXTURES = Path(__file__).parent / "fixtures"
API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/gotthard."""


@pytest.fixture
def situations():
    return (FIXTURES / "situations.xml").read_bytes()


@pytest.fixture
def feed(aioclient_mock, situations):
    """The feed, answering with the fixture."""
    aioclient_mock.post(URL, content=situations)
    return aioclient_mock


@pytest.fixture
def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=DOMAIN, data={CONF_API_KEY: API_KEY}
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def counters(aioclient_mock):
    """The counters, answering with a real minute."""
    from custom_components.gotthard.counters import URL as COUNTERS_URL

    aioclient_mock.post(COUNTERS_URL, content=(FIXTURES / "measured.xml").read_bytes())
    return aioclient_mock
