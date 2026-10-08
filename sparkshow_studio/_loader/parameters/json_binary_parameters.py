import struct
from dataclasses import dataclass
from enum import Enum, IntEnum

from sparkshow_studio._loader.parameters import FRAME_PARAMETERS


class MagicNumber(IntEnum):
    """The magic number to identify the version of the schema."""

    v1 = 0xAA55
    """First version of the binary format (outdated)."""
    v2 = 0xAA66
    """Second version of the binary format.

    This version is compatible with both IO-Star v1 and v2.
    This format is more compact than the first one.
    """
    v3 = 0xAA77
    """Third version of the binary format.

    This version is only compatible with IO-Star v2.
    This format allow specifying a scale and a land type.
    """
    v4 = 0xAA88
    """Fourth version of the binary format (In development, DO NOT USE)."""


class LandType(Enum):
    """The type of the land at the end of the show."""

    Land = "Land"
    """The drone land vertically from the last position."""
    RTL = "RTL"
    """The drone will RTL (Return To Land) from the last position."""

    @classmethod
    def from_int(cls, value: int) -> "LandType":
        if value == 0:
            return cls.Land
        if value == 1:
            return cls.RTL
        msg = f"LandType value must be 0 or 1, not {value}"
        raise ValueError(msg)

    def to_int(self) -> int:
        if self == self.Land:
            return 0
        return 1


@dataclass(frozen=True)
class Bound:
    minimal: int
    maximal: int


@dataclass(frozen=True)
class JsonBinaryParameters:
    fmt_header: str = ">HIB"  # Size in bits of the header
    fmt_section_header: str = ">BII"  # Size in bits of the section header
    timecode_format: str = "I"
    frame_format: str = "H"
    coordinate_format: str = "h"
    chrome_format: str = "B"
    fire_channel_format: str = "B"
    fire_duration_format: str = "B"
    angle_format: str = "h"
    dance_size_max: int = 100_000  # Maximal size of the binary send to the drone in octet
    fire_channel_number: int = 3

    def time_format(self, magic_number: MagicNumber) -> str:
        return self.timecode_format if magic_number == MagicNumber.v1 else self.frame_format

    def position_event_format(self, magic_number: MagicNumber) -> str:
        return f">{self.time_format(magic_number)}{self.coordinate_format}{self.coordinate_format}{self.coordinate_format}"

    def color_event_format(self, magic_number: MagicNumber) -> str:
        return f">{self.time_format(magic_number)}{self.chrome_format}{self.chrome_format}{self.chrome_format}{self.chrome_format}"

    def fire_event_format(self, magic_number: MagicNumber) -> str:
        return f">{self.time_format(magic_number)}{self.fire_channel_format}{self.fire_duration_format}"

    def yaw_event_format(self, magic_number: MagicNumber) -> str:
        return f">{self.time_format(magic_number)}{self.angle_format}"

    def config_format(self, magic_number: MagicNumber) -> str:
        """Return the format of the config section."""
        match magic_number:
            case MagicNumber.v1 | MagicNumber.v2:
                return ""
            case MagicNumber.v3:
                return ">BB"
            case MagicNumber.v4:
                return ">BBH"

    @staticmethod
    def _binary_format_size(binary_format: str) -> int:
        return 2 ** (8 * struct.calcsize(f">{binary_format}"))

    def time_value_bound(self, magic_number: MagicNumber) -> Bound:
        return Bound(
            0,
            self._binary_format_size(self.timecode_format) - 1
            if magic_number == MagicNumber.v1
            else self._binary_format_size(self.frame_format) - 1,
        )

    @property
    def coordinate_value_bound(self) -> Bound:
        return Bound(
            -self._binary_format_size(self.coordinate_format) // 2,
            self._binary_format_size(self.coordinate_format) // 2 - 1,
        )

    @property
    def chrome_value_bound(self) -> Bound:
        return Bound(
            0,
            self._binary_format_size(self.chrome_format) - 1,
        )

    @property
    def fire_channel_value_bound(self) -> Bound:
        return Bound(
            0,
            self.fire_channel_number - 1,
        )

    @property
    def fire_duration_value_bound(self) -> Bound:
        return Bound(
            0,
            self._binary_format_size(self.fire_duration_format) - 1,
        )

    @property
    def angle_value_bound(self) -> Bound:
        return Bound(
            -self._binary_format_size(self.angle_format) // 2,
            self._binary_format_size(self.angle_format) // 2 - 1,
        )

    @property
    def show_start_frame(self) -> int:
        return 0

    @staticmethod
    def _second_to_millisecond(second: float) -> int:
        return round(1e3 * second)

    @staticmethod
    def _millisecond_to_second(millisecond: int) -> float:
        return 1e-3 * millisecond

    @staticmethod
    def _centimer_to_meter(centimer: int) -> float:
        return 1e-2 * centimer

    @staticmethod
    def _meter_to_centimeter(meter: float) -> int:
        return round(1e2 * meter)

    @staticmethod
    def _unit_to_octet(unit: float) -> int:
        return round(255 * unit)

    @staticmethod
    def _octet_to_unit(octet: int) -> float:
        return 1 / 255 * octet

    def from_user_frame_to_px4_timecode(self, user_frame: int) -> int:
        return self._second_to_millisecond(
            FRAME_PARAMETERS.from_frame_to_second(user_frame),
        )

    def from_px4_timecode_to_user_frame(self, px4_timecode: int) -> int:
        return FRAME_PARAMETERS.from_second_to_frame(
            self._millisecond_to_second(px4_timecode),
        )

    def from_user_position_to_px4_position(self, user_position: float) -> int:
        return self._meter_to_centimeter(user_position)

    def from_user_xyz_to_px4_xyz(
        self,
        user_xyz: tuple[float, float, float],
    ) -> tuple[int, int, int]:
        return (
            self.from_user_position_to_px4_position(user_xyz[1]),
            self.from_user_position_to_px4_position(user_xyz[0]),
            -self.from_user_position_to_px4_position(user_xyz[2]),
        )

    def from_px4_position_to_user_position(self, px4_position: int) -> float:
        return self._centimer_to_meter(px4_position)

    def from_px4_xyz_to_user_xyz(
        self,
        px4_xyz: tuple[int, int, int],
    ) -> tuple[float, float, float]:
        return (
            self.from_px4_position_to_user_position(px4_xyz[1]),
            self.from_px4_position_to_user_position(px4_xyz[0]),
            -self.from_px4_position_to_user_position(px4_xyz[2]),
        )

    def from_user_rgbw_to_px4_rgbw(
        self,
        user_rgbw: tuple[float, float, float, float],
    ) -> tuple[int, int, int, int]:
        return (
            self._unit_to_octet(user_rgbw[0]),
            self._unit_to_octet(user_rgbw[1]),
            self._unit_to_octet(user_rgbw[2]),
            self._unit_to_octet(user_rgbw[3]),
        )

    def from_px4_rgbw_to_user_rgbw(
        self,
        px4_rgbw: tuple[int, int, int, int],
    ) -> tuple[float, float, float, float]:
        return (
            self._octet_to_unit(px4_rgbw[0]),
            self._octet_to_unit(px4_rgbw[1]),
            self._octet_to_unit(px4_rgbw[2]),
            self._octet_to_unit(px4_rgbw[3]),
        )


JSON_BINARY_PARAMETERS = JsonBinaryParameters()
