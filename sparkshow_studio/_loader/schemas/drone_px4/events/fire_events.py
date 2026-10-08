from dataclasses import dataclass
from typing import Any

from sparkshow_studio._loader.parameters.json_binary_parameters import JSON_BINARY_PARAMETERS, MagicNumber

from .events import Event, Events
from .events_order import EventsType


@dataclass(frozen=True)
class FireEvent(Event):
    frame: int  # time frame associate to the "fps_px4" parameter
    channel: int  # channel of the fire event
    duration: int  # duration of the fire event in milliseconds

    @property
    def channel_duration(self) -> tuple[int, int]:
        return (self.channel, self.duration)

    def get_data(self, magic_number: MagicNumber) -> list[Any]:
        return [
            (
                JSON_BINARY_PARAMETERS.from_user_frame_to_px4_timecode(self.frame)
                if magic_number == MagicNumber.v1
                else self.frame
            ),
            self.channel,
            self.duration,
        ]


class FireEvents(Events[FireEvent]):
    def __init__(self, magic_number: MagicNumber) -> None:
        self.format_ = JSON_BINARY_PARAMETERS.fire_event_format(magic_number)
        self.id_ = EventsType.fire
        self.magic_number = magic_number
        # Had to pass with the init because python mutable defaults are the source of all evil
        # https://florimond.dev/en/posts/2018/08/python-mutable-defaults-are-the-source-of-all-evil/
        self._events = []

    def add_timecode_channel_duration(
        self,
        frame: int,
        channel: int,
        duration: int,
    ) -> None:
        self._events.append(FireEvent(frame=frame, channel=channel, duration=duration))

    def add_data(self, data: list[Any]) -> None:
        self._events.append(
            FireEvent(
                frame=(
                    JSON_BINARY_PARAMETERS.from_px4_timecode_to_user_frame(data[0])
                    if self.magic_number == MagicNumber.v1
                    else data[0]
                ),
                channel=data[1],
                duration=data[2],
            ),
        )
