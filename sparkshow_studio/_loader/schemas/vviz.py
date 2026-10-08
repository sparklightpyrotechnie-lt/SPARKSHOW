# ruff: noqa: A003, N815
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from . import ColorEventUser, DroneUser, FireEventUser, PositionEventUser, ShowUser


def convert_enu_to_vviz(xyz: tuple[float, float, float]) -> tuple[float, float, float]:
    return xyz[0], xyz[2], xyz[1]


class GlobalReferenceFrame(BaseModel):
    lat: float
    lon: float
    alt: float


class PositionDeltaSample(BaseModel):
    dt: float | None = None
    dx: float
    dy: float
    dz: float


class AgentDescription(BaseModel):
    homeX: float
    homeY: float
    homeZ: float
    airframe: str
    agentTraversal: list[PositionDeltaSample] = []

    @classmethod
    def from_position_events(
        cls, positions: list["PositionEventUser"], airframe: str
    ) -> "AgentDescription":
        agent_traversal: list[PositionDeltaSample] = []
        if positions[0].frame != 0:
            agent_traversal.append(
                PositionDeltaSample(
                    dt=positions[0].frame / 24,
                    dx=0,
                    dy=0,
                    dz=0,
                )
            )
        last_frame = positions[0].frame
        last_xyz = positions[0].xyz
        for position in positions[1:]:
            dx = position.xyz[0] - last_xyz[0]
            dy = position.xyz[1] - last_xyz[1]
            dz = position.xyz[2] - last_xyz[2]
            dx, dy, dz = convert_enu_to_vviz((dx, dy, dz))
            dt = (position.frame - last_frame) / 24
            last_frame = position.frame
            last_xyz = position.xyz
            agent_traversal.append(
                PositionDeltaSample(
                    dt=dt if dt != 1 / 4 else None,
                    dx=round(dx, 2),
                    dy=round(dy, 2),
                    dz=round(dz, 2),
                )
            )
        home_x, home_y, home_z = convert_enu_to_vviz(positions[0].xyz)
        return AgentDescription(
            homeX=home_x,
            homeY=home_y,
            homeZ=home_z,
            airframe=airframe,
            agentTraversal=agent_traversal,
        )


class LightSample(BaseModel):
    r: int
    g: int
    b: int
    w: int
    frames: int | None = None


class LigthPayloadDescription(BaseModel):
    id: int = 0
    type: str = "Light"
    lumens: float
    colorType: str = "RGBW"
    sourceType: str
    payloadActions: list[LightSample]

    @classmethod
    def from_color_events(
        cls,
        colors: list["ColorEventUser"],
        lumens: float,
        source_type: str,
    ) -> "LigthPayloadDescription":
        payload_actions: list[LightSample] = []
        if colors[0].frame != 0:
            payload_actions.append(
                LightSample(
                    r=0,
                    g=0,
                    b=0,
                    w=0,
                )
            )
        last_frame = 0
        for color in colors:
            frames = color.frame - last_frame
            last_frame = color.frame
            payload_actions.append(
                LightSample(
                    r=round(color.rgbw[0] * 255),
                    g=round(color.rgbw[1] * 255),
                    b=round(color.rgbw[2] * 255),
                    w=round(color.rgbw[3] * 255),
                    frames=frames if frames > 1 else None,
                )
            )

        return LigthPayloadDescription(
            lumens=lumens,
            sourceType=source_type,
            payloadActions=payload_actions,
        )


class PyroPayloadDescription(BaseModel):
    id: int
    type: str = "Pyro"
    eventTime: float
    vdl: str
    partNumber: str = ""

    @classmethod
    def from_fire_events(
        cls,
        fires: list["FireEventUser"],
    ) -> list["PyroPayloadDescription"]:
        return [
            PyroPayloadDescription(id=index + 1, eventTime=fire.frame / 24, vdl=fire.vdl)
            for index, fire in enumerate(fires)
        ]


class Performance(BaseModel):
    id: int
    agentDescription: AgentDescription
    payloadDescription: list[LigthPayloadDescription | PyroPayloadDescription] = []

    @classmethod
    def from_drone_user(
        cls,
        drone_user: "DroneUser",
        airframe: str,
        lumens: float,
        source_type: str,
    ) -> "Performance":
        return Performance(
            id=drone_user.index,
            agentDescription=AgentDescription.from_position_events(
                drone_user.position_events, airframe
            ),
            payloadDescription=[
                LigthPayloadDescription.from_color_events(
                    drone_user.color_events, lumens, source_type
                ),
                *PyroPayloadDescription.from_fire_events(drone_user.fire_events),
            ],
        )


class Vviz(BaseModel):
    version: str = "1.0"
    performanceName: str
    coordinateFrame: str = "ogl"
    globalReferenceFrame: GlobalReferenceFrame | None = None
    defaultPositionRate: float = 4
    defaultColorRate: float = 24
    performances: list[Performance]

    @classmethod
    def from_show_user(
        cls,
        show_user: "ShowUser",
        *,
        performance_name: str,
        lat: float | None = None,
        lon: float | None = None,
        alt: float | None = None,
        airframe: str = "IOStar",
        lumens: float = 900.0,
        source_type: str = "Dome",
    ) -> "Vviz":
        global_reference_frame = (
            GlobalReferenceFrame(lat=lat, lon=lon, alt=alt)
            if lat is not None and lon is not None and alt is not None
            else None
        )
        performances = [
            Performance.from_drone_user(drone_user, airframe, lumens, source_type)
            for drone_user in show_user.drones_user
        ]
        return Vviz(
            performanceName=performance_name,
            globalReferenceFrame=global_reference_frame,
            performances=performances,
        )
