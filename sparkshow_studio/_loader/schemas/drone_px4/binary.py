import struct

from pydantic import BaseModel

from sparkshow_studio._loader.parameters.json_binary_parameters import JSON_BINARY_PARAMETERS, LandType, MagicNumber

from .events.events_order import EventsType


class Header(BaseModel):
    magic_number: MagicNumber  # Magic number with no purpose for the moment
    dance_size: int  # Dance size in bytes
    number_non_empty_events: int  # number of the events which contain at least one drone

    def bytes_data(self) -> bytes:
        return struct.pack(
            JSON_BINARY_PARAMETERS.fmt_header,
            self.magic_number,
            self.dance_size,
            self.number_non_empty_events,
        )

    @classmethod
    def from_bytes_data(cls, byte_array: bytearray) -> "Header":
        (
            magic_number,
            dance_size,
            number_non_empty_events,
        ) = struct.unpack(JSON_BINARY_PARAMETERS.fmt_header, byte_array)
        return cls(
            magic_number=MagicNumber(magic_number),
            dance_size=dance_size,
            number_non_empty_events=number_non_empty_events,
        )


class Config(BaseModel):
    scale: int
    land_type: LandType
    index: int | None

    def bytes_data(self, magic_number: MagicNumber) -> bytes:
        match magic_number:
            case MagicNumber.v1 | MagicNumber.v2:
                return b""
            case MagicNumber.v3:
                return struct.pack(
                    JSON_BINARY_PARAMETERS.config_format(magic_number),
                    self.scale,
                    self.land_type.to_int(),
                )
            case MagicNumber.v4:
                return struct.pack(
                    JSON_BINARY_PARAMETERS.config_format(magic_number),
                    self.scale,
                    self.land_type.to_int(),
                    self.index,
                )

    @classmethod
    def from_bytes_data(cls, byte_array: bytearray, magic_number: MagicNumber) -> "Config":
        match magic_number:
            case MagicNumber.v1 | MagicNumber.v2:
                scale = 1
                land_type = 0
                index = None
            case MagicNumber.v3:
                scale, land_type = struct.unpack(
                    JSON_BINARY_PARAMETERS.config_format(magic_number), byte_array
                )
                index = None
            case MagicNumber.v4:
                scale, land_type, index = struct.unpack(
                    JSON_BINARY_PARAMETERS.config_format(magic_number), byte_array
                )
        return cls(scale=scale, land_type=LandType.from_int(land_type), index=index)


class SectionHeader(BaseModel):
    event_id: EventsType  # index associate to the type of events
    byte_array_start_index: int  # index which indicates the start of the section in the binary
    byte_array_end_index: int  # index which indicates the end of the section in the binary

    def bytes_data(self) -> bytes:
        return struct.pack(
            JSON_BINARY_PARAMETERS.fmt_section_header,
            self.event_id,
            self.byte_array_start_index,
            self.byte_array_end_index,
        )

    @classmethod
    def from_bytes_data(cls, byte_array: bytearray) -> "SectionHeader":
        (
            event_id,
            byte_array_start_index,
            byte_array_end_index,
        ) = struct.unpack(JSON_BINARY_PARAMETERS.fmt_section_header, byte_array)
        return cls(
            event_id=EventsType(event_id),
            byte_array_start_index=byte_array_start_index,
            byte_array_end_index=byte_array_end_index,
        )
