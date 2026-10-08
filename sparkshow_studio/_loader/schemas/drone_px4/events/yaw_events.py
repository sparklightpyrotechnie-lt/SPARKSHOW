from dataclasses import dataclass
from typing import Any

from sparkshow_studio._loader.parameters.json_binary_parameters import JSON_BINARY_PARAMETERS, MagicNumber

from .events import Event, Events
from .events_order import EventsType


@dataclass(frozen=True)
class YawEvent(Event):
    frame: int  # time frame associate to the "fps_px4" parameter
    angle: int  # angle of the yaw event in degrees

    def get_data(self, magic_number: MagicNumber) -> list[Any]:
        return [
            (
                JSON_BINARY_PARAMETERS.from_user_frame_to_px4_timecode(self.frame)
                if magic_number == MagicNumber.v1
                else self.frame
            ),
            self.angle,
        ]


class YawEvents(Events[YawEvent]):
    def __init__(self, magic_number: MagicNumber) -> None:
        self.format_ = JSON_BINARY_PARAMETERS.yaw_event_format(magic_number)
        self.id_ = EventsType.yaw
        self.magic_number = magic_number
        # Had to pass with the init because python mutable defaults are the source of all evil
        # https://florimond.dev/en/posts/2018/08/python-mutable-defaults-are-the-source-of-all-evil/
        self._events = []

    def add_timecode_angle(
        self,
        frame: int,
        angle: int,
    ) -> None:
        self._events.append(YawEvent(frame=frame, angle=angle))

    def add_data(self, data: list[Any]) -> None:
        self._events.append(
            YawEvent(
                frame=(
                    JSON_BINARY_PARAMETERS.from_px4_timecode_to_user_frame(data[0])
                    if self.magic_number == MagicNumber.v1
                    else data[0]
                ),
                angle=data[1],
            ),
        )
