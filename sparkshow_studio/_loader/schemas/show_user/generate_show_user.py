import json
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sparkshow_studio._loader.parameters import FRAME_PARAMETERS, TAKEOFF_PARAMETERS, LandType, MagicNumber
from sparkshow_studio._loader.schemas.matrix import get_matrix

from .show_user import DroneUser, ShowUser

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass()
class ShowUserConfiguration:
    matrix: "NDArray[np.intp]" = field(default_factory=get_matrix)
    step_x: float = 1.5
    step_y: float = 1.5
    angle_takeoff: float = 0.0
    show_duration_absolute_time: float = 30.0
    takeoff_altitude: float = TAKEOFF_PARAMETERS.takeoff_altitude_meter_min
    duration_before_takeoff: float = 0.0
    magic_number: MagicNumber = MagicNumber.v3
    scale: int = 1
    land_type: LandType = LandType.Land

    def __post_init__(self) -> None:
        if self.show_duration_absolute_time <= 0.0:
            msg = f"Show duration must be stricly positive, not {self.show_duration_absolute_time}"
            raise ValueError(msg)
        if (
            self.takeoff_altitude < TAKEOFF_PARAMETERS.takeoff_altitude_meter_min
            or self.takeoff_altitude > TAKEOFF_PARAMETERS.takeoff_altitude_meter_max
        ):
            msg = (
                f"Takeoff altitude must be between {TAKEOFF_PARAMETERS.takeoff_altitude_meter_min} "
                f"and {TAKEOFF_PARAMETERS.takeoff_altitude_meter_max}, not {self.takeoff_altitude}"
            )
            raise ValueError(msg)
        if self.duration_before_takeoff < 0.0:
            msg = f"Duration before takeoff must be positive, not {self.duration_before_takeoff}"
            raise ValueError(msg)

    @property
    def nb_x(self) -> int:
        return self.matrix.shape[1]

    @property
    def nb_y(self) -> int:
        return self.matrix.shape[0]


def rotated_horizontal_coordinates(
    xyz: tuple[float, float, float],
    angle_radian: float,
) -> tuple[float, float, float]:
    x_rotated = xyz[0] * math.cos(angle_radian) - xyz[1] * math.sin(angle_radian)
    y_rotated = xyz[0] * math.sin(angle_radian) + xyz[1] * math.cos(angle_radian)
    return (x_rotated, y_rotated, xyz[2])


def get_valid_position_events_user(
    index_x: int,
    index_y: int,
    show_user_configuration: ShowUserConfiguration,
    drone_user: DroneUser,
) -> None:
    nb_x = show_user_configuration.nb_x
    nb_y = show_user_configuration.nb_y
    step_x = show_user_configuration.step_x
    step_y = show_user_configuration.step_y
    index_bias_x = 0.5 * (nb_x - 1) * step_x
    index_bias_y = 0.5 * (nb_y - 1) * step_y

    drone_user.add_position_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff,
        ),
        xyz=rotated_horizontal_coordinates(
            (
                show_user_configuration.step_x * index_x - index_bias_x,
                show_user_configuration.step_y * index_y - index_bias_y,
                0.0,
            ),
            show_user_configuration.angle_takeoff,
        ),
    )
    drone_user.add_position_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff
            + TAKEOFF_PARAMETERS.takeoff_elevation_duration_second,
        ),
        xyz=rotated_horizontal_coordinates(
            (
                show_user_configuration.step_x * index_x - index_bias_x,
                show_user_configuration.step_y * index_y - index_bias_y,
                TAKEOFF_PARAMETERS.takeoff_altitude_meter_min,
            ),
            show_user_configuration.angle_takeoff,
        ),
    )
    drone_user.add_position_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff
            + TAKEOFF_PARAMETERS.takeoff_duration_second,
        ),
        xyz=rotated_horizontal_coordinates(
            (
                show_user_configuration.step_x * index_x - index_bias_x,
                show_user_configuration.step_y * index_y - index_bias_y,
                show_user_configuration.takeoff_altitude,
            ),
            show_user_configuration.angle_takeoff,
        ),
    )
    drone_user.add_position_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff
            + TAKEOFF_PARAMETERS.takeoff_duration_second
            + show_user_configuration.show_duration_absolute_time,
        ),
        xyz=rotated_horizontal_coordinates(
            (
                show_user_configuration.step_x * index_x - index_bias_x,
                show_user_configuration.step_y * index_y - index_bias_y,
                show_user_configuration.takeoff_altitude,
            ),
            show_user_configuration.angle_takeoff,
        ),
    )


def get_valid_color_events_user(
    show_user_configuration: ShowUserConfiguration,
    drone_user: DroneUser,
) -> None:
    drone_user.add_color_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff,
        ),
        rgbw=(1.0, 0.0, 0.0, 0.0),
    )
    drone_user.add_color_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff
            + TAKEOFF_PARAMETERS.takeoff_duration_second,
        ),
        rgbw=(0.0, 1.0, 0.0, 0.0),
    )
    drone_user.add_color_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff
            + TAKEOFF_PARAMETERS.takeoff_duration_second
            + show_user_configuration.show_duration_absolute_time,
        ),
        rgbw=(0.0, 0.0, 1.0, 0.0),
    )


def get_valid_fire_events(
    show_user_configuration: ShowUserConfiguration,
    drone_user: DroneUser,
) -> None:
    drone_user.add_fire_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff,
        ),
        channel=0,
        duration=0,
    )
    drone_user.add_fire_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff
            + TAKEOFF_PARAMETERS.takeoff_duration_second,
        ),
        channel=1,
        duration=0,
    )
    drone_user.add_fire_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff
            + TAKEOFF_PARAMETERS.takeoff_duration_second
            + show_user_configuration.show_duration_absolute_time,
        ),
        channel=0,
        duration=0,
    )


def get_valid_yaw_events(
    show_user_configuration: ShowUserConfiguration,
    drone_user: DroneUser,
) -> None:
    drone_user.add_yaw_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff,
        ),
        angle=0,
    )
    drone_user.add_yaw_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff
            + TAKEOFF_PARAMETERS.takeoff_duration_second,
        ),
        angle=90,
    )
    drone_user.add_yaw_event(
        frame=FRAME_PARAMETERS.from_second_to_frame(
            show_user_configuration.duration_before_takeoff
            + TAKEOFF_PARAMETERS.takeoff_duration_second
            + show_user_configuration.show_duration_absolute_time,
        ),
        angle=0,
    )


def get_valid_show_user(show_user_configuration: ShowUserConfiguration) -> ShowUser:
    matrix = show_user_configuration.matrix
    show_user = ShowUser.create(
        nb_drones=matrix.sum(),
        angle_takeoff=show_user_configuration.angle_takeoff,
        step_x=show_user_configuration.step_x,
        step_y=show_user_configuration.step_y,
    )
    show_user.magic_number = show_user_configuration.magic_number
    show_user.scale = show_user_configuration.scale
    show_user.land_type = show_user_configuration.land_type
    drone_index = 0
    for index_y, column in enumerate(show_user_configuration.matrix):
        for index_x, nb_drones_per_family in enumerate(column):
            for _ in range(nb_drones_per_family):
                drone_user = show_user[drone_index]
                get_valid_position_events_user(
                    index_x,
                    index_y,
                    show_user_configuration,
                    drone_user,
                )
                get_valid_color_events_user(show_user_configuration, drone_user)
                get_valid_fire_events(show_user_configuration, drone_user)
                get_valid_yaw_events(show_user_configuration, drone_user)
                drone_index += 1
    return show_user


def get_valid_platform_takeoff(json_path: str) -> ShowUser:
    with open(json_path) as file:  # noqa: PTH123
        data = json.load(file)

    drones_user: list[DroneUser] = []
    for drone_user_dict in data["drones"]:
        drone_user = DroneUser(
            index=drone_user_dict["index"],
            position_events=[],
            color_events=[],
            fire_events=[],
            yaw_events=[],
        )
        for position_event_dict in drone_user_dict["position_events"]:
            drone_user.add_position_event(position_event_dict["frame"], position_event_dict["xyz"])
        for color_event_dict in drone_user_dict["color_events"]:
            drone_user.add_color_event(color_event_dict["frame"], color_event_dict["rgbw"])
        if drone_user_dict["fire_events"]:
            raise NotImplementedError
        if drone_user_dict["yaw_events"]:
            raise NotImplementedError
        drones_user.append(drone_user)
    return ShowUser(
        drones_user=drones_user,
        angle_takeoff=data["other_parameters"]["angle_takeoff"],
        angle_show=data["other_parameters"]["angle_show"],
        step_x=data["other_parameters"]["step_x"],
        step_y=data["other_parameters"]["step_y"],
        scale=data["other_parameters"]["scale"],
        land_type=LandType.RTL
        if data["other_parameters"]["land_type"] == "LandType.RTL"
        else LandType.Land,
        rtl_start_frame=data["other_parameters"]["rtl_start_frame"],
        takeoff_end_frame=data["other_parameters"]["takeoff_end_frame"],
    )
