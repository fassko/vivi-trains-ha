"""Unit tests for Vivi Trains config flow compatibility."""

from __future__ import annotations

import unittest
import sys
import types

from test_coordinator import _install_homeassistant_stubs


_install_homeassistant_stubs()

if "voluptuous" not in sys.modules:
    voluptuous = types.ModuleType("voluptuous")
    voluptuous.Schema = lambda schema: schema
    voluptuous.Required = lambda key, **kwargs: key
    voluptuous.Optional = lambda key, **kwargs: key
    voluptuous.In = lambda options: options
    voluptuous.All = lambda *validators: validators
    voluptuous.Coerce = lambda target_type: target_type
    voluptuous.Range = lambda **kwargs: kwargs
    sys.modules["voluptuous"] = voluptuous

from custom_components.vivi_trains.config_flow import (  # noqa: E402
    ViviTrainsConfigFlow,
)
from custom_components.vivi_trains.const import (  # noqa: E402
    CONF_DEPARTURES_COUNT,
)


class _ConfigEntry:
    data = {CONF_DEPARTURES_COUNT: 5}
    options = {}


class OptionsFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_options_flow_does_not_assign_read_only_config_entry(self) -> None:
        flow = ViviTrainsConfigFlow.async_get_options_flow(_ConfigEntry())
        flow._config_entry = _ConfigEntry()

        result = await flow.async_step_init()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "init")

    async def test_options_flow_normalizes_submitted_count(self) -> None:
        flow = ViviTrainsConfigFlow.async_get_options_flow(_ConfigEntry())
        flow._config_entry = _ConfigEntry()

        result = await flow.async_step_init({CONF_DEPARTURES_COUNT: "10"})

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"][CONF_DEPARTURES_COUNT], 10)


if __name__ == "__main__":
    unittest.main()
