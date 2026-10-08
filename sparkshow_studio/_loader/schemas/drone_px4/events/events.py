import struct
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any, Generic, TypeVar

from sparkshow_studio._loader.parameters.json_binary_parameters import MagicNumber

from .events_order import EventsType


class Event(ABC):
    frame: int

    @abstractmethod
    def get_data(self, magic_number: MagicNumber) -> list[Any]:
        pass


TEvent = TypeVar("TEvent", bound=Event)


class Events(ABC, Generic[TEvent]):
    format_: str
    id_: EventsType
    magic_number: MagicNumber
    _events: list[TEvent]

    def __repr__(self) -> str:  # pragma: no cover
        return f"{self.__class__.__name__}({self._events})"

    @abstractmethod
    def add_data(self, data: list[Any]) -> None:
        pass

    def __iter__(self) -> Iterator[TEvent]:
        return self._events.__iter__()

    def __getitem__(self, position_event_index: int) -> TEvent:
        return self._events[position_event_index]

    def __len__(self) -> int:
        return len(self._events)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, type(self)) and len(self) == len(other):
            return all(
                self._events[event_index] == other._events[event_index]  # noqa: SLF001
                for event_index in range(len(self._events))
            )
        return False

    @property
    def event_size(self) -> int:
        return struct.calcsize(self.format_)

    @property
    def events_size(self) -> int:
        return len(self._events) * struct.calcsize(self.format_)
