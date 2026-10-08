from dataclasses import dataclass

from sparkshow_studio._loader.parameters import FRAME_PARAMETERS


@dataclass(frozen=True)
class LandParameters:
    land_fast_speed: float = 3.0
    land_low_speed: float = 0.4
    land_safe_hgt: float = 3.0
    rtl_reposition_duration: float = 1
    rtl_speed: float = 2.0

    def get_first_land_second_delta(self, drone_hgt_meter: float) -> float:
        if drone_hgt_meter < self.land_safe_hgt:
            return drone_hgt_meter / self.land_low_speed
        return (drone_hgt_meter - self.land_safe_hgt) / self.land_fast_speed

    def get_first_land_altitude(self, drone_hgt_meter: float) -> float:
        if drone_hgt_meter < self.land_safe_hgt:
            return 0.0
        return self.land_safe_hgt

    def get_second_land_second_delta(self, drone_hgt_meter: float) -> float:
        if drone_hgt_meter < self.land_safe_hgt:
            return 0.0
        return self.land_safe_hgt / self.land_low_speed

    def get_second_land_altitude_start(self, drone_hgt_meter: float) -> float:
        if drone_hgt_meter < self.land_safe_hgt:
            return 0.0
        return self.land_safe_hgt

    def get_land_second_delta(self, drone_hgt_meter: float) -> float:
        return self.get_first_land_second_delta(
            drone_hgt_meter,
        ) + self.get_second_land_second_delta(drone_hgt_meter)

    def get_land_frame_delta(self, drone_hgt_meter: float) -> int:
        return FRAME_PARAMETERS.from_second_to_frame(
            self.get_land_second_delta(drone_hgt_meter),
        )

    def get_rtl_reposition_frame_delta(self) -> int:
        return FRAME_PARAMETERS.from_second_to_frame(self.rtl_reposition_duration)


LAND_PARAMETERS = LandParameters()
