from dataclasses import dataclass
from typing import Any

from sparkshow_studio._loader.parameters.json_binary_parameters import JSON_BINARY_PARAMETERS, MagicNumber

from .events import Event, Events
from .events_order import EventsType


@dataclass(frozen=True)
class ColorEvent(Event):
    frame: int  # time frame associate to the "fps_px4" parameter
    r: int  # red color
    g: int  # green color
    b: int  # blue color
    w: int  # white color
    interpolate: bool = False  # if the event is interpolated

    @property
    def rgbw(self) -> tuple[int, int, int, int]:
        return (self.r, self.g, self.b, self.w)

    def get_data(self, magic_number: MagicNumber) -> list[Any]:
        if magic_number == MagicNumber.v1:
            time = JSON_BINARY_PARAMETERS.from_user_frame_to_px4_timecode(self.frame)
            w = self.w
        else:
            time = self.frame
            # The white color is stored in the 7 least significant bits of the byte
            # and the interpolation flag is stored in the most significant bit
            w = (self.w >> 1) | (self.interpolate << 7)
        return [
            time,
            self.r,
            self.g,
            self.b,
            w,
        ]


class ColorEvents(Events[ColorEvent]):
    def __init__(self, magic_number: MagicNumber) -> None:
        self.id_ = EventsType.color
        self.format_ = JSON_BINARY_PARAMETERS.color_event_format(magic_number)
        self.magic_number = magic_number
        # Had to pass with the init because python mutable defaults are the source of all evil
        # https://florimond.dev/en/posts/2018/08/python-mutable-defaults-are-the-source-of-all-evil/
        self._events = []

    def add_timecode_rgbw(
        self,
        frame: int,
        rgbw: tuple[int, int, int, int],
        *,
        interpolate: bool = False,
    ) -> None:
        self._events.append(
            ColorEvent(
                frame=frame,
                r=rgbw[0],
                g=rgbw[1],
                b=rgbw[2],
                w=rgbw[3],
                interpolate=False if self.magic_number == MagicNumber.v1 else interpolate,
            ),
        )

    def add_data(self, data: list[Any]) -> None:
        if self.magic_number == MagicNumber.v1:
            frame = JSON_BINARY_PARAMETERS.from_px4_timecode_to_user_frame(data[0])
            w = data[4]
            # The interpolation flag is set to False because it is not stored in the old format
            interpolate = False
        else:
            frame = data[0]
            # The white color is stored in the 7 least significant bits of the byte
            w = (data[4] & 0b01111111) << 1
            # and the interpolation flag is stored in the most significant bit
            interpolate = bool(data[4] >> 7)

        self._events.append(
            ColorEvent(
                frame=frame,
                r=data[1],
                g=data[2],
                b=data[3],
                w=w,
                interpolate=interpolate,
            ),
        )
