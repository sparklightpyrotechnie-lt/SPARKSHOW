"""IO Star physic parameters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IostarPhysicParameters:
    horizontal_velocity_max: float = 3.5
    """Maximum horizontal velocity of the drone in meter per second."""
    acceleration_max: float = 1.5
    """Maximum acceleration of the drone in meter per second squared."""
    velocity_up_max: float = 3.5
    """Maximum up vertical velocity of the drone in meter per second."""
    velocity_down_max: float = 3.5
    """Maximum down vertical velocity of the drone in meter per second."""
    minimum_distance: float = 1.5
    """Minimum distance between drones in meter."""


IOSTAR_PHYSIC_PARAMETERS_RECOMMENDATION = IostarPhysicParameters()
"""Recommended physic parameters for the IO Star drone."""
IOSTAR_PHYSIC_PARAMETERS_MAX = IostarPhysicParameters(
    horizontal_velocity_max=5.0,
    acceleration_max=2.0,
    velocity_up_max=4.0,
    velocity_down_max=4.0,
    minimum_distance=1.0,
)
"""Maximum physic parameters for the IO Star drone."""
