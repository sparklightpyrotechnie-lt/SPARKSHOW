from dataclasses import dataclass


@dataclass(frozen=True)
class TakeoffParameters:
    takeoff_altitude_meter_min: float = 1.0
    takeoff_altitude_meter_max: float = 20.0
    takeoff_elevation_duration_second: float = 3.0
    takeoff_stabilisation_duration_second: float = 7.0
    takeoff_total_duration_tolerance: float = 4 / 24 + 1e-8
    takeoff_maximum_time: float = 259 / 24  # 259 frames to sec = nb frames to go to 20m
    nb_drones_per_platform: int = 6
    platform_width: float = 0.77
    platform_length: float = 1.16

    @property
    def takeoff_duration_second(self) -> float:
        return self.takeoff_elevation_duration_second + self.takeoff_stabilisation_duration_second


TAKEOFF_PARAMETERS = TakeoffParameters()
