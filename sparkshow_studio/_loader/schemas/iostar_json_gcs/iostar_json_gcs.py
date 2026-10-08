"""IO Star JSON GCS schema.

This schema should be used for converting to and from the Show User schema.
"""

from typing import TYPE_CHECKING, Any

import numpy as np
from pydantic import BaseModel, Field, ValidationInfo, model_validator
from tqdm import tqdm

from sparkshow_studio._loader.parameters import FRAME_PARAMETERS, IostarPhysicParameters
from sparkshow_studio._loader.parameters.json_binary_parameters import JSON_BINARY_PARAMETERS, LandType
from sparkshow_studio._loader.schemas.drone_px4 import DronePx4
from sparkshow_studio._loader.schemas.metadata import Metadata
from sparkshow_studio._loader.schemas.show_user.convex_hull import calculate_convex_hull

if TYPE_CHECKING:
    from sparkshow_studio._loader.schemas.show_user import ShowUser


class Dance(BaseModel):
    dance: list[int]
    """List of integer symbolising the list of octet."""


class Family(BaseModel):
    drones: list[Dance]
    """List of the drone composing a family."""
    x: int
    """X relative position (NED) of the family in centimeter."""
    y: int
    """Y relative position (NED) of the family in centimeter."""
    z: int
    """Z relative position (NED) of the family in centimeter."""

    @classmethod
    def from_drone_px4(
        cls,
        autopilot_format_family: list[DronePx4],
    ) -> "Family":
        x, y, z = (
            sum(
                drone_px4_family.position_events[0].xyz[i]
                for drone_px4_family in autopilot_format_family
            )
            // len(autopilot_format_family)
            for i in range(3)
        )
        return Family(
            drones=[
                Dance(dance=DronePx4.to_binary(drone_px4_family))
                for drone_px4_family in autopilot_format_family
            ],
            x=x,
            y=y,
            z=z,
        )


class Show(BaseModel):
    families: list[Family]
    """List of the families composing the show."""
    nb_x: int
    """Number of families on the y-axis during the takeoff."""
    nb_y: int
    """Number of families on the x-axis during the takeoff."""
    step_x: int
    """Distance separating the families during the takeoff in centimeter (x axis)."""
    step_y: int
    """Distance separating the families during the takeoff in centimeter (y axis)."""
    angle_takeoff: int = 0
    """Angle of the takeoff grid."""
    angle_show: int | None = None
    """Angle of the show."""
    duration: int
    """Duration of the show in millisecond."""
    hull: list[tuple[int, int]]
    """List of the relative coordinate (XY in NED and centimeter) symbolysing a convex hull of a show."""
    altitude_range: tuple[int, int]
    """Relative coordinate ( z_min and z_max in NED and centimeter) symbolising the range of the z-axis."""
    scale: int = Field(1, ge=1, le=4)
    """Position scale of the show."""
    land_type: LandType = LandType.Land
    """Type of landing at the end of the show."""
    takeoff_end_frame: int | None = None
    """Frame at which the takeoff ends for platform takeoffs."""
    rtl_start_frame: int | None = None
    """Frame at which the automatic RTL starts."""

    # Custom validator to handle backward compatibility
    @model_validator(mode="before")  # noqa: PGH003  # type: ignore
    def split_name(cls: Any, __value: Any, __info: ValidationInfo) -> Any:  # noqa: N805, ANN401
        if "step" in __value:
            __value["step_x"] = __value["step"]
            __value["step_y"] = __value["step"]
            del __value["step"]
        return __value


class IostarJsonGcs(BaseModel):
    show: Show
    """Data of the show."""
    physic_parameters: IostarPhysicParameters | None = None
    """Physic parameters of the show."""
    metadata: Metadata = Metadata()
    """Metadata of the show."""

    @property
    def nb_drones_per_family(self) -> int:
        """Return the number of drones per family."""
        return max(len(family.drones) for family in self.show.families)

    @classmethod
    def from_show_user(cls, show_user: "ShowUser") -> "IostarJsonGcs":
        """Convert from the ShowUser schema to the IostarJsonGcs schema."""
        step_x = JSON_BINARY_PARAMETERS.from_user_position_to_px4_position(show_user.step_x)
        step_y = JSON_BINARY_PARAMETERS.from_user_position_to_px4_position(show_user.step_y)
        angle_takeoff = -round(np.rad2deg(show_user.angle_takeoff))
        angle_show = (
            -round(np.rad2deg(show_user.angle_show)) if show_user.angle_show is not None else None
        )
        duration = from_user_duration_to_px4_duration(show_user.duration)
        hull = from_user_hull_to_px4_hull(show_user.convex_hull)
        altitude_range = from_user_altitude_range_to_px4_altitude_range(show_user.altitude_range)
        autopilot_format = DronePx4.from_show_user_in_matrix(show_user)
        return IostarJsonGcs(
            show=Show(
                families=[
                    Family.from_drone_px4(family_drones_px4)
                    for row in tqdm(
                        autopilot_format,
                        desc="Converting show user to iostar json gcs",
                        unit="row",
                    )
                    for family_drones_px4 in row
                    if len(family_drones_px4)
                ],
                duration=duration,
                hull=hull,
                altitude_range=altitude_range,
                step_x=step_x,
                step_y=step_y,
                nb_x=show_user.nb_x,
                nb_y=show_user.nb_y,
                angle_takeoff=angle_takeoff,
                angle_show=angle_show,
                scale=show_user.scale,
                land_type=show_user.land_type,
                takeoff_end_frame=show_user.takeoff_end_frame,
                rtl_start_frame=show_user.rtl_start_frame,
            ),
            physic_parameters=show_user.physic_parameters,
            metadata=show_user.metadata,
        )


def from_user_altitude_range_to_px4_altitude_range(
    altitude_range: tuple[float, float],
) -> tuple[int, int]:
    user_minimal_coordinate, user_maximal_coordinate = (
        (0.0, 0.0, altitude_range[0]),
        (
            0.0,
            0.0,
            altitude_range[1],
        ),
    )
    (
        px4_minimal_coordinate,
        px4_maximal_coordinate,
    ) = (
        JSON_BINARY_PARAMETERS.from_user_xyz_to_px4_xyz(
            user_minimal_coordinate,
        ),
        JSON_BINARY_PARAMETERS.from_user_xyz_to_px4_xyz(
            user_maximal_coordinate,
        ),
    )
    return (px4_maximal_coordinate[2], px4_minimal_coordinate[2])


def from_user_duration_to_px4_duration(duration: float) -> int:
    return JSON_BINARY_PARAMETERS.from_user_frame_to_px4_timecode(
        FRAME_PARAMETERS.from_second_to_frame(duration),
    )


def from_user_hull_to_px4_hull(
    user_hull: list[tuple[float, float]],
) -> list[tuple[int, int]]:
    user_coordinates = [(user_point[0], user_point[1], 0.0) for user_point in user_hull]
    px4_coordinates = [
        (JSON_BINARY_PARAMETERS.from_user_xyz_to_px4_xyz(user_coordinate))
        for user_coordinate in user_coordinates
    ]
    return [
        (x, y)
        for y, x in calculate_convex_hull(
            [(px4_coordinate[1], px4_coordinate[0]) for px4_coordinate in px4_coordinates],
        )
    ]
