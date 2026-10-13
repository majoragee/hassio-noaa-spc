"""Config flow for NOAA SPC."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LOCATION, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
)

from .api.products import in_conus
from .const import (
    ALL_GROUPS,
    CONF_ALERT_INTERVAL,
    CONF_ENTRY_TYPE,
    CONF_GROUPS,
    CONF_MODE,
    CONF_MOVE_THRESHOLD_KM,
    CONF_OUTLOOK_INTERVAL,
    CONF_TRACKED_ENTITY,
    DEFAULT_ALERT_INTERVAL,
    DEFAULT_MOVE_THRESHOLD_KM,
    DEFAULT_OUTLOOK_INTERVAL,
    DOMAIN,
    ENTRY_TYPE_HUB,
    ENTRY_TYPE_LOCATION,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    MODE_FIXED,
    MODE_TRACKED,
    TRACKABLE_DOMAINS,
)


class SpcConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NOAA SPC."""

    VERSION = 1

    def __init__(self) -> None:
        self._pending: tuple[str, dict[str, Any]] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow for the entry type."""
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return HubOptionsFlow()
        return LocationOptionsFlow()

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Create the single hub entry."""
        await self.async_set_unique_id(HUB_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=HUB_TITLE, data={CONF_ENTRY_TYPE: ENTRY_TYPE_HUB}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose between a fixed and a tracked location."""
        return self.async_show_menu(
            step_id="user", menu_options=[MODE_FIXED, MODE_TRACKED]
        )

    async def async_step_fixed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a fixed location."""
        if user_input is not None:
            location = user_input[CONF_LOCATION]
            lat = float(location[CONF_LATITUDE])
            lon = float(location[CONF_LONGITUDE])
            await self.async_set_unique_id(f"fixed_{lat:.3f}_{lon:.3f}")
            self._abort_if_unique_id_configured()
            self._pending = (
                user_input[CONF_NAME],
                {
                    CONF_ENTRY_TYPE: ENTRY_TYPE_LOCATION,
                    CONF_MODE: MODE_FIXED,
                    CONF_LATITUDE: lat,
                    CONF_LONGITUDE: lon,
                },
            )
            if not in_conus(lat, lon):
                return await self.async_step_outside()
            return self._create_pending()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=self.hass.config.location_name): str,
                vol.Required(
                    CONF_LOCATION,
                    default={
                        CONF_LATITUDE: self.hass.config.latitude,
                        CONF_LONGITUDE: self.hass.config.longitude,
                    },
                ): LocationSelector(LocationSelectorConfig(radius=False)),
            }
        )
        return self.async_show_form(step_id="fixed", data_schema=schema)

    async def async_step_outside(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Warn that the location is outside SPC coverage."""
        if user_input is not None:
            return self._create_pending()
        return self.async_show_form(step_id="outside", data_schema=vol.Schema({}))

    async def async_step_tracked(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a tracked location."""
        if user_input is not None:
            entity_id = user_input[CONF_TRACKED_ENTITY]
            await self.async_set_unique_id(f"tracked_{entity_id}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_ENTRY_TYPE: ENTRY_TYPE_LOCATION,
                    CONF_MODE: MODE_TRACKED,
                    CONF_TRACKED_ENTITY: entity_id,
                },
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_TRACKED_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain=TRACKABLE_DOMAINS)
                ),
            }
        )
        return self.async_show_form(step_id="tracked", data_schema=schema)

    def _create_pending(self) -> ConfigFlowResult:
        assert self._pending is not None
        title, data = self._pending
        return self.async_create_entry(title=title, data=data)


def _minutes(minimum: int, maximum: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )


class HubOptionsFlow(OptionsFlow):
    """Options for the hub entry (polling intervals)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start the hub options step."""
        return await self.async_step_hub()

    async def async_step_hub(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit polling intervals."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_OUTLOOK_INTERVAL,
                    default=options.get(
                        CONF_OUTLOOK_INTERVAL, DEFAULT_OUTLOOK_INTERVAL
                    ),
                ): _minutes(2, 60),
                vol.Required(
                    CONF_ALERT_INTERVAL,
                    default=options.get(CONF_ALERT_INTERVAL, DEFAULT_ALERT_INTERVAL),
                ): _minutes(1, 30),
            }
        )
        return self.async_show_form(step_id="hub", data_schema=schema)


class LocationOptionsFlow(OptionsFlow):
    """Options for a location entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start the location options step."""
        return await self.async_step_location()

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit location, tracking and enabled groups."""
        conf = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            if CONF_LOCATION in data:
                location = data.pop(CONF_LOCATION)
                data[CONF_LATITUDE] = float(location[CONF_LATITUDE])
                data[CONF_LONGITUDE] = float(location[CONF_LONGITUDE])
            merged = {**conf, **data}
            if merged[CONF_MODE] == MODE_TRACKED:
                unique_id = f"tracked_{merged[CONF_TRACKED_ENTITY]}"
            else:
                unique_id = (
                    f"fixed_{merged[CONF_LATITUDE]:.3f}_{merged[CONF_LONGITUDE]:.3f}"
                )
            if any(
                other.unique_id == unique_id
                for other in self.hass.config_entries.async_entries(DOMAIN)
                if other.entry_id != self.config_entry.entry_id
            ):
                errors["base"] = "already_configured"
            else:
                # Update both together so only one reload is triggered.
                self.hass.config_entries.async_update_entry(
                    self.config_entry, unique_id=unique_id, options=data
                )
                return self.async_create_entry(data=data)

        fields: dict[Any, Any] = {}
        if conf[CONF_MODE] == MODE_FIXED:
            fields[
                vol.Required(
                    CONF_LOCATION,
                    default={
                        CONF_LATITUDE: conf[CONF_LATITUDE],
                        CONF_LONGITUDE: conf[CONF_LONGITUDE],
                    },
                )
            ] = LocationSelector(LocationSelectorConfig(radius=False))
        else:
            fields[
                vol.Required(CONF_TRACKED_ENTITY, default=conf[CONF_TRACKED_ENTITY])
            ] = EntitySelector(EntitySelectorConfig(domain=TRACKABLE_DOMAINS))
            fields[
                vol.Required(
                    CONF_MOVE_THRESHOLD_KM,
                    default=conf.get(CONF_MOVE_THRESHOLD_KM, DEFAULT_MOVE_THRESHOLD_KM),
                )
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=0.1,
                    max=50,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="km",
                )
            )
        fields[vol.Required(CONF_GROUPS, default=conf.get(CONF_GROUPS, ALL_GROUPS))] = (
            SelectSelector(
                SelectSelectorConfig(
                    options=ALL_GROUPS, multiple=True, translation_key="groups"
                )
            )
        )
        return self.async_show_form(
            step_id="location", data_schema=vol.Schema(fields), errors=errors
        )
