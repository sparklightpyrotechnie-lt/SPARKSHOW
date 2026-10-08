import itertools
from collections.abc import Iterable
from typing import Any, TypeVar

import bpy
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from pydantic import BaseModel

from ..base import BaseOperator, BasePanel
from ..setup import FPS
from ..tools.collection_tools import is_drone
from ..tools.color_tools import RGBW
from ..tools.tutorial_links_tools import draw_tutorial_button, link

show_center = (43.3938666, 1.7453378, 189.0)


T = TypeVar("T")
client = mqtt.Client(CallbackAPIVersion.VERSION2)


def batched(iterable: Iterable[T], n: int) -> Iterable[tuple[T, ...]]:
    # batched('ABCDEFG', 3) → ABC DEF G
    if n < 1:
        msg = "n must be at least one"
        raise ValueError(msg)
    it = iter(iterable)
    while batch := tuple(itertools.islice(it, n)):
        yield batch


class LiveColor(BaseModel):
    msg_index: int
    frame: int
    payload: list[int]

    @classmethod
    def from_drones_color(cls, frame: int, drones_color: list[RGBW]) -> list["LiveColor"]:
        return [
            LiveColor(
                msg_index=msg_index,
                frame=frame,
                payload=[round(v * 255) for color in batched_drones_color for v in color[:4]]
                + [0] * (252 - 4 * len(batched_drones_color)),
            )
            for msg_index, batched_drones_color in enumerate(batched(drones_color, 63))
        ]


class ParamSet(BaseModel):
    uuid: str = ""
    param_value: str
    target_system: int = 1
    target_component: int = 1
    param_id: str = "DNC_LIVE_ENABLE"
    param_type: int = 6
    broadcast: bool = True


class ColorLed(BaseModel):
    uuid: str = ""
    broadcast: bool = True
    color: int = 0
    mode: int = 2
    blinks: int = 0
    prio: int = 2


def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:  # noqa: ARG001, ANN401
    client.publish("swarm_manager/color_led", ColorLed().model_dump_json())


def run_live_updates() -> float:
    live_color_props = getattr(bpy.context.scene, "live_color_props", None)
    assert live_color_props is not None, "live_color_props not found in scene"

    if not client.is_connected():
        return 1 // FPS

    if live_color_props.running:
        obj = live_color_props.drone_object
        if obj:
            if obj.name.startswith("Drone "):
                live_color_props.color = tuple(obj.color)
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == "VIEW_3D":
                            area.tag_redraw()
            elif obj.active_material and obj.active_material.node_tree:
                nodes = obj.active_material.node_tree.nodes
                emission_node = next((node for node in nodes if node.type == "EMISSION"), None)
                if emission_node:
                    emission_color = emission_node.inputs["Color"].default_value
                    live_color_props.color = tuple(emission_color)
                    for window in bpy.context.window_manager.windows:
                        for area in window.screen.areas:
                            if area.type == "VIEW_3D":
                                area.tag_redraw()

        current_color = live_color_props.color

        if not all(
            abs(a - b) < 1e-6
            for a, b in zip(current_color, live_color_props.last_color, strict=False)
        ):
            live_color_props.last_color = current_color
            for live_color in LiveColor.from_drones_color(0, [live_color_props.color]):
                client.publish("swarm_manager/recv_mqtt_live_color", live_color.model_dump_json())
            live_color_props.error_message = ""

    return 1 // FPS


class LIGHTSHOW_PT_gcs(BasePanel):
    bl_parent_id = "SPARKSHOW_STUDIO_PT_lighting"
    bl_label = "📽 Live Color"
    bl_idname = "LIGHTSHOW_PT_gcs"

    def draw(self, context: bpy.types.Context) -> None:
        live_color_props = getattr(context.scene, "live_color_props", None)
        assert live_color_props is not None, "live_color_props not found in scene"

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        # Connection settings box
        conn_box = layout.box()
        conn_box.label(text="GCS Connection", icon="URL")
        conn_box.prop(live_color_props, "gcs_ip", text="GCS IP")

        if not client.is_connected():
            if not live_color_props.connected_to_gcs:
                draw_tutorial_button(
                    layout,
                    context,
                    lambda col: col.operator(
                        "lightshow.gcs_mqtt_connect", text="Connect", icon="LINKED"
                    ),
                    section=link.live_color,
                )
                return
            layout.label(text="Connexion to GCS...", icon="SORTTIME")
            layout.operator("lightshow.gcs_mqtt_reset", text="Reset", icon="FILE_REFRESH")
            return
        conn_box.operator("lightshow.gcs_mqtt_disconnect", text="Disconnect", icon="UNLINKED")

        # Connection control row: Connect/Disconnect drones
        conn_row = conn_box.row(align=True)
        conn_text = "Disconnect drones" if live_color_props.drones_connected else "Connect drones"
        # Using a different icon for disconnect; here we use 'UNLINKED' as a sample
        conn_icon = "UNLINKED" if live_color_props.drones_connected else "LINKED"
        conn_row.operator("lightshow.connect_drones", text=conn_text, icon=conn_icon)

        # Live color control box
        color_box = layout.box()
        color_box.label(text="Live Color Control", icon="COLOR")
        # Status row: Running vs. Stopped
        status_row = color_box.row(align=True)
        status_text = "Stop Live Color" if live_color_props.running else "Run Live Color"
        status_icon = "PAUSE" if live_color_props.running else "PLAY"
        status_row.prop(live_color_props, "running", text=status_text, icon=status_icon)

        # Color picker shown only when live color is active
        if live_color_props.running:
            color_box.separator()
            if live_color_props.error_message:
                color_box.label(text=live_color_props.error_message, icon="ERROR")

            color_box.prop(live_color_props, "drone_object", text="Drone")

            color_row = color_box.row()
            color_row.enabled = not live_color_props.drone_object
            color_row.prop(live_color_props, "color", text="Live Color")


class LIGHTSHOW_OT_gcs_mqtt_reset(BaseOperator):
    bl_label = "Reset"
    bl_description = "Reset the GCS connection"
    bl_idname = "lightshow.gcs_mqtt_reset"

    def execute(self, context: bpy.types.Context) -> set[str]:
        props = getattr(context.scene, "live_color_props", None)
        assert props is not None, "live_color_props not found in scene"
        props.connected_to_gcs = False
        props.running = False
        return {"FINISHED"}


class LIGHTSHOW_OT_gcs_mqtt_connect(BaseOperator):
    bl_label = "Connect to GCS"
    bl_description = "Connect to the GCS with the given IP address"
    bl_idname = "lightshow.gcs_mqtt_connect"

    _timer = None
    _start_time = 0

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        if event.type == "TIMER" and client.is_connected():
            self.cancel(context)
            self.redraw_ui()
            return {"FINISHED"}

        return {"PASS_THROUGH"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        props = getattr(context.scene, "live_color_props", None)
        assert props is not None, "live_color_props not found in scene"
        props.connected_to_gcs = True
        global client  # noqa: PLW0603
        client = mqtt.Client(CallbackAPIVersion.VERSION2)
        client.on_message = on_message
        client.loop_start()
        try:
            client.connect(props.gcs_ip, 1999)
        except (OSError, mqtt.WebsocketConnectionError):
            props.error_message = (
                "Connection error: are you connected to the same network as the GCS?"
            )
            props.connected_to_gcs = False
            self.report({"ERROR"}, props.error_message)
            return {"CANCELLED"}
        if not bpy.app.timers.is_registered(run_live_updates):
            bpy.app.timers.register(run_live_updates)

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.5, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def cancel(self, context: bpy.types.Context) -> None:
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)

    def redraw_ui(self) -> None:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()


class LIGHTSHOW_OT_connect_drones(BaseOperator):
    bl_label = "Connect"
    bl_description = "Connect all drones on this ip to the live color"
    bl_idname = "lightshow.connect_drones"

    def execute(self, context: bpy.types.Context) -> set[str]:
        props = getattr(context.scene, "live_color_props", None)
        assert props is not None, "live_color_props not found in scene"

        if not props.drones_connected:
            client.publish(
                "swarm_manager/recv_mqtt_param_set",
                ParamSet(param_value="2").model_dump_json(),
            )
            props.drones_connected = True
        else:
            client.publish(
                "swarm_manager/recv_mqtt_param_set",
                ParamSet(param_value="0").model_dump_json(),
            )
            props.drones_connected = False
        return {"FINISHED"}


class LIGHTSHOW_OT_gcs_mqtt_disconnect(BaseOperator):
    bl_label = "Disconnect from GCS"
    bl_description = "Disconnect from the GCS"
    bl_idname = "lightshow.gcs_mqtt_disconnect"

    def execute(self, context: bpy.types.Context) -> set[str]:
        props = getattr(context.scene, "live_color_props", None)
        assert props is not None, "live_color_props not found in scene"

        if bpy.app.timers.is_registered(run_live_updates):
            bpy.app.timers.unregister(run_live_updates)

        live_color = LiveColor.from_drones_color(0, [(0.005, 0, 0, 0)])[0]
        client.publish("swarm_manager/recv_mqtt_live_color", live_color.model_dump_json())

        client.disconnect()
        client.loop_stop()

        props.connected_to_gcs = False
        return {"FINISHED"}


def start_stop_live_color(self: bpy.types.Property, context: bpy.types.Context) -> None:  # noqa: ARG001
    live_color_props = getattr(context.scene, "live_color_props", None)
    assert live_color_props is not None, "live_color_props not found in scene"

    if not live_color_props.running:
        live_color_props.last_color = live_color_props.color
        live_color = LiveColor.from_drones_color(0, [(0, 0.005, 0, 0)])[0]
        client.publish("swarm_manager/recv_mqtt_live_color", live_color.model_dump_json())
    else:
        live_color = LiveColor.from_drones_color(0, [live_color_props.color])[0]
        client.publish("swarm_manager/recv_mqtt_live_color", live_color.model_dump_json())


def verify_mesh_is_drone(self: bpy.types.Property, context: bpy.types.Context) -> None:  # noqa: ARG001
    live_color_props = getattr(context.scene, "live_color_props", None)
    assert live_color_props is not None, "live_color_props not found in scene"

    if live_color_props.drone_object and not is_drone(live_color_props.drone_object):
        live_color_props.drone_object = None
        live_color_props.error_message = "Selected object is not a valid drone."
        return

    if live_color_props.drone_object:
        live_color_props.drone_object.select_set(True)
    else:
        bpy.ops.object.select_all(action="DESELECT")


class LiveColorProperties(bpy.types.PropertyGroup):
    __annotations__ = {
        "running": bpy.props.BoolProperty(
            name="GCS Live Color",
            description="Enable GCS live color",
            default=False,
            update=start_stop_live_color,
        ),
        "drones_connected": bpy.props.BoolProperty(
            name="Drones Connected",
            description="Whether the drones were connected to the GCS",
            default=False,
        ),
        "gcs_ip": bpy.props.StringProperty(
            name="GCS IP",
            description="The IP address of the GCS",
            default="10.11.1.1",
        ),
        "connected_to_gcs": bpy.props.BoolProperty(
            name="GCS Connected",
            description="Whether the GCS is connected",
            default=False,
        ),
        "color": bpy.props.FloatVectorProperty(
            name="Color",
            description="The RGB color values for the live color.",
            subtype="COLOR",
            min=0,
            max=1,
            soft_min=0,
            soft_max=1,
            size=4,
            default=(0.004, 0.011, 0.022, 0.005),
        ),
        "last_color": bpy.props.FloatVectorProperty(
            name="Last GCS Live Color",
            description="The last GCS live color",
            subtype="COLOR",
            min=0,
            max=1,
            soft_min=0,
            soft_max=1,
            size=4,
            default=(1.0, 0.0, 0.0, 0.0),
        ),
        "drone_object": bpy.props.PointerProperty(
            name="Object",
            type=bpy.types.Object,
            description="Live color will display the color of this object. Note: Ensure that the color is applied to the drone.",
            update=verify_mesh_is_drone,
        ),
        "error_message": bpy.props.StringProperty(
            name="Error Message",
            description="Error message",
            default="",
        ),
    }


def disconnect_from_gcs() -> None:
    if bpy.app.timers.is_registered(run_live_updates):
        bpy.app.timers.unregister(run_live_updates)
    live_color = LiveColor.from_drones_color(0, [(0.005, 0.005, 0, 0)])[0]
    client.publish("swarm_manager/recv_mqtt_live_color", live_color.model_dump_json())
    client.disconnect()
    client.loop_stop()


classes = [
    LIGHTSHOW_PT_gcs,
    LIGHTSHOW_OT_gcs_mqtt_reset,
    LIGHTSHOW_OT_gcs_mqtt_connect,
    LIGHTSHOW_OT_gcs_mqtt_disconnect,
    LIGHTSHOW_OT_connect_drones,
    LiveColorProperties,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.live_color_props = bpy.props.PointerProperty(type=LiveColorProperties)  # type: ignore


def unregister() -> None:
    if bpy.app.timers.is_registered(run_live_updates):
        bpy.app.timers.unregister(run_live_updates)
    for cls in classes:
        bpy.utils.unregister_class(cls)
    disconnect_from_gcs()
