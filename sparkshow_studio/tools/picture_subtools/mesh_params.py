# pyright: ignore

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...setup import Lightshow


class MeshParams:
    def __init__(self) -> None:
        self.nb_vertices_dict: dict[str, int] = {}
        self._img_paths: dict[str, str] = {}
        self.last_selected_mesh: str | None = None

    def set_path(self, mesh_name: str, img_path: str) -> None:
        assert img_path.split(".")[-1].lower() in [
            "svg",
            "png",
            "jpg",
            "jpeg",
        ], f"Invalid file format {img_path}"
        self._img_paths[mesh_name] = img_path

    def get_img_path(self, mesh_name: str) -> str:
        return self._img_paths.get(mesh_name, "")

    def get_previous_values(self, selected_mesh: str, lightshow: "Lightshow") -> None:
        lightshow.nb_vertices = self.nb_vertices_dict.get(selected_mesh, lightshow.nb_drones)

    def save_previous_values(self, selected_mesh: str, lightshow: "Lightshow") -> None:
        self.nb_vertices_dict[selected_mesh] = lightshow.nb_vertices

    def update(self, selected_mesh: str, lightshow: "Lightshow") -> None:
        if selected_mesh != self.last_selected_mesh:
            self.get_previous_values(lightshow.selected_mesh, lightshow)
            self.last_selected_mesh = selected_mesh


mesh_params = MeshParams()
