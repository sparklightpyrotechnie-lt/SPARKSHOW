from sparkshow_studio._loader.parameters import FRAME_PARAMETERS, LandType
from sparkshow_studio._loader.parameters.json_binary_parameters import JSON_BINARY_PARAMETERS
from sparkshow_studio._loader.schemas.show_user import DroneUser

from .in_dance_flight_simulation import in_dance_flight_simulation
from .land_simulation import land_simulation, rtl_simulation
from .position_simulation import SimulationInfo
from .stand_by_simulation import stand_by_simulation
from .takeoff_simulation import takeoff_simulation


def get_flight_simulation(
    drone_user: DroneUser,
    last_frame: int = -1,
    land_type: LandType = LandType.Land,
) -> list[SimulationInfo]:
    if len(drone_user.position_events) < 2:
        msg = "Drone user must have at least 2 position events"
        raise ValueError(msg)
    simulation_infos: list[SimulationInfo] = []
    last_frame_stand_by = drone_user.position_events[0].frame  # last frame stand by
    if last_frame_stand_by != 0:
        simulation_infos += stand_by_simulation(
            FRAME_PARAMETERS.from_second_to_frame(
                JSON_BINARY_PARAMETERS.show_start_frame,
            ),
            drone_user.position_events[0].frame,
            drone_user.position_events[0].xyz,
        )
    simulation_infos += takeoff_simulation(
        drone_user.position_events[0].xyz,
        drone_user.position_events[2].xyz,
        last_frame_stand_by,
        drone_user.position_events[2].frame,
    )
    simulation_infos += in_dance_flight_simulation(
        drone_user.flight_positions,
    )
    last_position = drone_user.position_events[-1].xyz

    if land_type == LandType.Land:
        simulation_infos += land_simulation(
            last_position,
            simulation_infos[-1].frame + 1,
        )
    else:  # RTL
        simulation_infos += rtl_simulation(
            drone_user.position_events[0].xyz,
            last_position,
            simulation_infos[-1].frame + 1,
        )
    if last_frame == -1:
        last_frame = simulation_infos[-1].frame + 1
    simulation_infos += stand_by_simulation(
        frame_begin=simulation_infos[-1].frame + 1,
        frame_end=last_frame + 1,
        stand_by_position=(last_position[0], last_position[1], 0),
    )
    return simulation_infos


def get_partial_flight_simulation(drone_user: DroneUser) -> list[SimulationInfo]:
    return in_dance_flight_simulation(drone_user.position_events)
