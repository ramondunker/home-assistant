"""Support for HomeKit Controller Televisions."""
import logging

from aiohomekit.model.characteristics import (
    CharacteristicsTypes,
    CurrentMediaStateValues,
    RemoteKeyValues,
    TargetMediaStateValues,
)
from aiohomekit.model.services import ServicesTypes
from aiohomekit.utils import clamp_enum_to_char

from homeassistant.components.media_player import DEVICE_CLASS_TV, MediaPlayerDevice
from homeassistant.components.media_player.const import (
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_STOP,
)
from homeassistant.const import (
    STATE_IDLE,
    STATE_OK,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_PROBLEM,
)
from homeassistant.core import callback

from . import KNOWN_DEVICES, HomeKitEntity

_LOGGER = logging.getLogger(__name__)


HK_TO_HA_STATE = {
    CurrentMediaStateValues.PLAYING: STATE_PLAYING,
    CurrentMediaStateValues.PAUSED: STATE_PAUSED,
    CurrentMediaStateValues.STOPPED: STATE_IDLE,
}


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Homekit television."""
    hkid = config_entry.data["AccessoryPairingID"]
    conn = hass.data[KNOWN_DEVICES][hkid]

    @callback
    def async_add_service(aid, service):
        if service["stype"] != "television":
            return False
        info = {"aid": aid, "iid": service["iid"]}
        async_add_entities([HomeKitTelevision(conn, info)], True)
        return True

    conn.add_listener(async_add_service)


class HomeKitTelevision(HomeKitEntity, MediaPlayerDevice):
    """Representation of a HomeKit Controller Television."""

    def __init__(self, accessory, discovery_info):
        """Initialise the TV."""
        self._state = None
        self._features = 0
        self._supported_target_media_state = set()
        self._supported_remote_key = set()
        super().__init__(accessory, discovery_info)

    def get_characteristic_types(self):
        """Define the homekit characteristics the entity cares about."""
        return [
            CharacteristicsTypes.ACTIVE,
            CharacteristicsTypes.CURRENT_MEDIA_STATE,
            CharacteristicsTypes.TARGET_MEDIA_STATE,
            CharacteristicsTypes.REMOTE_KEY,
            CharacteristicsTypes.ACTIVE_IDENTIFIER,
            # Characterics that are on the linked INPUT_SOURCE services
            CharacteristicsTypes.CONFIGURED_NAME,
            CharacteristicsTypes.IDENTIFIER,
        ]

    def _setup_active_identifier(self, char):
        self._features |= SUPPORT_SELECT_SOURCE

    def _setup_target_media_state(self, char):
        self._supported_target_media_state = clamp_enum_to_char(
            TargetMediaStateValues, char
        )

        if TargetMediaStateValues.PAUSE in self._supported_target_media_state:
            self._features |= SUPPORT_PAUSE

        if TargetMediaStateValues.PLAY in self._supported_target_media_state:
            self._features |= SUPPORT_PLAY

        if TargetMediaStateValues.STOP in self._supported_target_media_state:
            self._features |= SUPPORT_STOP

    def _setup_remote_key(self, char):
        self._supported_remote_key = clamp_enum_to_char(RemoteKeyValues, char)
        if RemoteKeyValues.PLAY_PAUSE in self._supported_remote_key:
            self._features |= SUPPORT_PAUSE | SUPPORT_PLAY

    @property
    def device_class(self):
        """Define the device class for a HomeKit enabled TV."""
        return DEVICE_CLASS_TV

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return self._features

    @property
    def source_list(self):
        """List of all input sources for this television."""
        sources = []

        this_accessory = self._accessory.entity_map.aid(self._aid)
        this_tv = this_accessory.services.iid(self._iid)

        input_sources = this_accessory.services.filter(
            service_type=ServicesTypes.INPUT_SOURCE, parent_service=this_tv,
        )

        for input_source in input_sources:
            char = input_source[CharacteristicsTypes.CONFIGURED_NAME]
            sources.append(char.value)
        return sources

    @property
    def source(self):
        """Name of the current input source."""
        active_identifier = self.service.value(CharacteristicsTypes.ACTIVE_IDENTIFIER)
        if not active_identifier:
            return None

        this_accessory = self._accessory.entity_map.aid(self._aid)
        this_tv = this_accessory.services.iid(self._iid)

        input_source = this_accessory.services.first(
            service_type=ServicesTypes.INPUT_SOURCE,
            characteristics={CharacteristicsTypes.IDENTIFIER: active_identifier},
            parent_service=this_tv,
        )
        char = input_source[CharacteristicsTypes.CONFIGURED_NAME]
        return char.value

    @property
    def state(self):
        """State of the tv."""
        active = self.service.value(CharacteristicsTypes.ACTIVE)
        if not active:
            return STATE_PROBLEM

        homekit_state = self.service.value(CharacteristicsTypes.CURRENT_MEDIA_STATE)
        if homekit_state is not None:
            return HK_TO_HA_STATE.get(homekit_state, STATE_OK)

        return STATE_OK

    async def async_media_play(self):
        """Send play command."""
        if self.state == STATE_PLAYING:
            _LOGGER.debug("Cannot play while already playing")
            return

        if TargetMediaStateValues.PLAY in self._supported_target_media_state:
            await self.async_put_characteristics(
                {CharacteristicsTypes.TARGET_MEDIA_STATE: TargetMediaStateValues.PLAY}
            )
        elif RemoteKeyValues.PLAY_PAUSE in self._supported_remote_key:
            await self.async_put_characteristics(
                {CharacteristicsTypes.REMOTE_KEY: RemoteKeyValues.PLAY_PAUSE}
            )

    async def async_media_pause(self):
        """Send pause command."""
        if self.state == STATE_PAUSED:
            _LOGGER.debug("Cannot pause while already paused")
            return

        if TargetMediaStateValues.PAUSE in self._supported_target_media_state:
            await self.async_put_characteristics(
                {CharacteristicsTypes.TARGET_MEDIA_STATE: TargetMediaStateValues.PAUSE}
            )
        elif RemoteKeyValues.PLAY_PAUSE in self._supported_remote_key:
            await self.async_put_characteristics(
                {CharacteristicsTypes.REMOTE_KEY: RemoteKeyValues.PLAY_PAUSE}
            )

    async def async_media_stop(self):
        """Send stop command."""
        if self.state == STATE_IDLE:
            _LOGGER.debug("Cannot stop when already idle")
            return

        if TargetMediaStateValues.STOP in self._supported_target_media_state:
            await self.async_put_characteristics(
                {CharacteristicsTypes.TARGET_MEDIA_STATE: TargetMediaStateValues.STOP}
            )

    async def async_select_source(self, source):
        """Switch to a different media source."""
        this_accessory = self._accessory.entity_map.aid(self._aid)
        this_tv = this_accessory.services.iid(self._iid)

        input_source = this_accessory.services.first(
            service_type=ServicesTypes.INPUT_SOURCE,
            characteristics={CharacteristicsTypes.CONFIGURED_NAME: source},
            parent_service=this_tv,
        )

        if not input_source:
            raise ValueError(f"Could not find source {source}")

        identifier = input_source[CharacteristicsTypes.IDENTIFIER]

        await self.async_put_characteristics(
            {CharacteristicsTypes.ACTIVE_IDENTIFIER: identifier.value}
        )
