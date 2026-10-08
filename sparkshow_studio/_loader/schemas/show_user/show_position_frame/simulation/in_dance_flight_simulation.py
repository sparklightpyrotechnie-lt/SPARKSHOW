import numpy as np

from sparkshow_studio._loader.schemas.show_user import PositionEventUser

from .position_simulation import SimulationInfo, apply_decimal_number_tolerance


def in_dance_flight_simulation(
    position_events_user: list[PositionEventUser],
) -> list[SimulationInfo]:
    position_events_user_frame = [
        position_event_user.frame for position_event_user in position_events_user
    ]
    position_events_user_x = [
        position_event_user.xyz[0] for position_event_user in position_events_user
    ]
    position_events_user_y = [
        position_event_user.xyz[1] for position_event_user in position_events_user
    ]
    position_events_user_z = [
        position_event_user.xyz[2] for position_event_user in position_events_user
    ]
    desired_frames = np.arange(position_events_user[0].frame, position_events_user[-1].frame)
    flight_positions_x = np.interp(
        desired_frames,
        position_events_user_frame,
        position_events_user_x,
    )
    flight_positions_y = np.interp(
        desired_frames,
        position_events_user_frame,
        position_events_user_y,
    )
    flight_positions_z = np.interp(
        desired_frames,
        position_events_user_frame,
        position_events_user_z,
    )
    flight_positions = apply_decimal_number_tolerance(
        np.column_stack(
            (
                flight_positions_x,
                flight_positions_y,
                flight_positions_z,
            ),
        ),
    )
    return [
        SimulationInfo(
            frame=desired_frame,
            position=position,
        )
        for desired_frame, position in zip(
            desired_frames,
            flight_positions,
            strict=True,
        )
    ]
