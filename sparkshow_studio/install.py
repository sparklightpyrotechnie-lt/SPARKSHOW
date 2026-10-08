import subprocess
import sys
from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import cast


@dataclass(frozen=True)
class PackageInfo:
    import_name: str
    download_name: str
    version: str
    local: bool = False


# The Sparkshow loader is bundled and namespaced inside sparkshow_studio._loader
# so Sparkshow can coexist with Lightshow Creator, which uses loader 0.14.x.

PACKAGE_INFOS = [
    PackageInfo(import_name="cv2", download_name="opencv-python", version="4.7.*"),
    PackageInfo(import_name="PIL", download_name="pillow", version="11.1.*"),
    PackageInfo(import_name="paho.mqtt", download_name="paho-mqtt", version="2.0.*"),
    PackageInfo(import_name="pymap3d", download_name="pymap3d", version="3.1.*"),
    PackageInfo(import_name="vtracer", download_name="vtracer", version="0.6.11"),
    PackageInfo(import_name="svgpathtools", download_name="svgpathtools", version="1.6.1"),
    PackageInfo(import_name="fontTools", download_name="fonttools", version="4.55.3"),
    PackageInfo(import_name="svgwrite", download_name="svgwrite", version="1.4.3"),
]


def ensure_pip() -> None:
    pip_package_info = PackageInfo(import_name="pip", download_name="pip", version="23.0.*")
    if not is_package_installed(pip_package_info):
        try:
            subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])
        except subprocess.CalledProcessError as e:
            msg = "Unable to install pip. Please check Blender Python installation and permissions."
            raise ValueError(msg) from e


def is_package_installed(package_info: PackageInfo) -> bool:
    return find_spec(package_info.import_name.split(".")[0]) is not None


def is_package_up_to_date(package_info: PackageInfo) -> bool:
    try:
        package_version = cast(
            "str | None",
            getattr(
                import_module(package_info.import_name),
                "__version__",
                None,
            ),
        )
    except ImportError:
        return False

    if package_info.local:
        print(
            f"{package_info.import_name} version {package_version} must be == {package_info.version}",
        )
        return package_version == package_info.version

    print(
        f"{package_info.import_name} version {package_version} must be >= {package_info.version}",
    )
    return (
        package_version is not None
        and package_version.split(".")[:2] == package_info.version.split(".")[:2]
    )


def install_package(package_info: PackageInfo) -> None:
    if package_info.local:
        package = str(Path(__file__).absolute().parent / package_info.download_name)
    else:
        package = package_info.download_name
    try:
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-user",
                "--upgrade",
                package if package_info.local else f"{package}=={package_info.version}",
            ],
        )
    except subprocess.CalledProcessError as e:
        msg = f"Unable to install package {package}=={package_info.version}. Please ensure that Blender has permission to install Python packages."
        raise ValueError(msg) from e


def install(package_info: PackageInfo, force: bool) -> None:
    if force and package_info.local:
        print(f"Force update {package_info.download_name}")
        install_package(package_info)
    elif not is_package_installed(package_info):
        print(f"Install {package_info.download_name}")
        install_package(package_info)
    elif not is_package_up_to_date(package_info):
        print(f"Update {package_info.download_name}")
        install_package(package_info)
    else:
        print(f"{package_info.download_name} already installed")


def execute_installation(force: bool = False) -> None:
    print("Ensure pip is installed")
    ensure_pip()
    print("Install packages for python")
    for package_info in PACKAGE_INFOS:
        install(package_info, force)
    if any(not is_package_installed(package_info) for package_info in PACKAGE_INFOS):
        msg = "Installation failed, please launch Blender as admin"
        for package_info in PACKAGE_INFOS:
            if not is_package_installed(package_info):
                msg += f"\n - {package_info.download_name} is not installed"
        raise ValueError(msg)
    print("Installation done")
