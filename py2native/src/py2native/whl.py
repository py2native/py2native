import argparse
import logging

logger = logging.getLogger(__name__)
import base64
import hashlib
import pathlib
import sys
import sysconfig
import zipfile

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

from . import runtime
from .plugin import pluginManager
from .utils import getBuildPath
from .version import version as toolVersion


def hash_file(filepath):
    """Generates the PEP 427 compliant hash and file size."""
    with open(filepath, "rb") as f:
        data = f.read()
        digest = hashlib.sha256(data).digest()
        # urlsafe base64, UTF-8 decoded, no trailing '=' padding
        hash_str = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")
        return f"sha256={hash_str}", len(data)


def find_active_pyproject(current_dir) -> pathlib.Path | None:
    """Finds pyproject.toml by searching upward from the current working directory."""

    # Check the current directory and all parent directories
    for directory in [current_dir, *current_dir.parents]:
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate

        # Do leave the project root
        if (directory / ".git").is_dir():
            return None

    return None  # Not found


def get_wheel_tags(library):
    """Dynamically generates strict CPython ABI tags."""
    # e.g., '311' for Python 3.11
    py_ver = f"{sys.version_info.major}{sys.version_info.minor}"

    configVars = sysconfig.get_config_vars()

    soabi = configVars.get("SOABI") or ""
    gil_disabled = bool(configVars.get("Py_GIL_DISABLED"))
    free_threaded = gil_disabled or f"cpython-{py_ver}t" in soabi

    # For free-threaded CPython, python tag stays cpXY while ABI tag is cpXYt.
    python_tag = f"cp{py_ver}"
    abi_tag = f"cp{py_ver}{'t' if free_threaded else ''}"

    if library:
        py_hex = (sys.version_info.major << 24) | (sys.version_info.minor << 16)
        if py_hex >= 0x030b0000 and not free_threaded:
            abi_tag = "abi3"

    # Get platform (e.g., win_amd64, manylinux_2_17_x86_64, macosx_11_0_arm64)
    plat_name = sysconfig.get_platform().replace("-", "_").replace(".", "_")

    plat_name = pluginManager.fixPlatformName(plat_name)

    return python_tag, abi_tag, plat_name


def createWheel(
    executablePath,
    outputPath,
    library=False,
    moduleNames=None,
    mainModuleName=None,
    sourcePath=None,
    version=None):

    buildPath = getBuildPath()

    wrkPath = buildPath / "wrk"
    wrkPath.mkdir(parents=True, exist_ok=True)

    pyprojectTomlPath = find_active_pyproject(sourcePath)

    pyProject = pyprojectTomlPath.read_text()
    pyProject = tomllib.loads(pyProject)

    productName = pyProject["project"]["name"]
    if version is None:
        version = pyProject["project"]["version"]
    dependencies = pyProject["project"].get("dependencies", [])

    python_tag, abi_tag, plat_tag = get_wheel_tags(library)

    # Generates: pycomp-1.0.0-cp311-cp311-win_amd64.whl
    wheel_name = f"{productName}-{version}-{python_tag}-{abi_tag}-{plat_tag}.whl"

    wheelPath = wrkPath / wheel_name

    full_tag = f"{python_tag}-{abi_tag}-{plat_tag}"

    metadata = f"Metadata-Version: 2.1\n"
    metadata += f"Name: {productName}\n"
    metadata += f"Version: {version}\n"

    for dep in dependencies:
        metadata += f"Requires-Dist: {dep}\n"

    metadata = metadata.encode("utf-8")

    # Notice the updated Tag line here
    wheel_info = f"Wheel-Version: 1.0\n"
    wheel_info += f"Generator: Py2Native-custom {toolVersion}\n"
    wheel_info += "Root-Is-Purelib: false\n"
    wheel_info += f"Tag: {full_tag}\n"

    wheel_info = wheel_info.encode("utf-8")

    # Read your compiled executable
    with open(executablePath, "rb") as f:
        exe_data = f.read()

    basicInfo = pluginManager.getCompileBasics()

    if library:
        libraryName = executablePath.name
        moduleSuffix = (
            pathlib.Path(sysconfig.get_config_var("EXT_SUFFIX") or libraryName).suffix
            or ".so"
        )
        moduleStem = mainModuleName or productName
        if moduleStem.startswith(f"{productName}."):
            moduleImportPath = moduleStem[len(productName) + 1 :]
        else:
            moduleImportPath = moduleStem

    exeName = pluginManager.getExePath(".", productName)
    exeName = exeName.name

    # 2. Create the ZIP (Wheel)
    records = []
    with zipfile.ZipFile(wheelPath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Helper to write to zip and track hashes
        def write_file(arcname, data):
            zf.writestr(arcname, data)
            digest = hashlib.sha256(data).digest()
            hash_str = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")
            records.append(f"{arcname},sha256={hash_str},{len(data)}")

        # Write files
        if library:
            libraryName = executablePath.name
            pyd_name_in_wheel = f"{productName}{moduleSuffix}"
            write_file(f"{productName}/{pyd_name_in_wheel}", exe_data)
            # __init__.py sets up a meta-path finder so that imports like
            # "from .sign import sign" resolve to the same .pyd file.
            _qualified = [f"{productName}.{n}" for n in (moduleNames or [])]
            # Also include the shared Cython ABI module and the cython_runtime
            _extra = ["_p2n_shared", "cython_runtime"]
            _all_module_names = _qualified + _extra
            package_init = (
                "import sys\n"
                "import importlib.util\n"
                "import importlib.machinery\n"
                f"_PYD_NAME = '{pyd_name_in_wheel}'\n"
                f"_MODULE_NAMES = {_all_module_names!r}\n"
                "class _BundledFinder:\n"
                "    def find_spec(self, fullname, path, target=None):\n"
                "        if fullname in _MODULE_NAMES:\n"
                "            loader = importlib.machinery.ExtensionFileLoader(fullname, __path__[0] + '/' + _PYD_NAME)\n"
                "            return importlib.util.spec_from_loader(fullname, loader)\n"
                "        return None\n"
                "sys.meta_path.insert(0, _BundledFinder())\n"
                f"# Pre-create '{moduleStem}' in sys.modules so that imports of\n"
                f"# '{moduleStem}.shared' during PyInit_{moduleStem} can find the parent.\n"
                "import types\n"
                f"_main_placeholder = types.ModuleType('{moduleStem}')\n"
                "_main_placeholder.__path__ = []\n"
                f"_main_placeholder.__package__ = '{moduleStem}'\n"
                f"sys.modules['{moduleStem}'] = _main_placeholder\n"
                "import importlib as _importlib\n"
                "# Pre-create cython_runtime in sys.modules so that\n"
                "# PyImport_AddModule('cython_runtime') inside the .so's init\n"
                "# functions finds it without triggering a recursive load.\n"
                "if 'cython_runtime' not in sys.modules:\n"
                "    sys.modules['cython_runtime'] = types.ModuleType('cython_runtime')\n"
                "# Init Cython shared runtime first so that module init functions\n"
                "# inside the same .so can find _p2n_shared already loaded.\n"
                "_importlib.import_module('_p2n_shared')\n"
                f"_native = _importlib.import_module('.{moduleStem}', __name__)\n"
                "__pyx_capi__ = getattr(_native, '__pyx_capi__', None)\n"
                f"from .{moduleStem} import *\n"
            ).encode("utf-8")
            write_file(f"{productName}/__init__.py", package_init)
            package_main = (
                "import importlib as _importlib\n"
                f"_importlib.import_module('.{mainModuleName}', __package__)\n"
                f"_mod = _importlib.import_module('.{moduleImportPath}', __package__)\n"
                "if hasattr(_mod, 'main'):\n"
                "    _mod.main()\n"
            ).encode("utf-8")
            write_file(f"{productName}/__main__.py", package_main)
            write_file(
                f"{productName}-{version}.dist-info/top_level.txt",
                productName.encode("utf-8"),
            )
        else:
            write_file(f"{productName}-{version}.data/scripts/{exeName}", exe_data)

            for k, v in pluginManager.getRuntimeLibraries(
                productName, version, runtime.getRuntimePath()
            ):
                write_file(k, v)

        write_file(f"{productName}-{version}.dist-info/METADATA", metadata)
        write_file(f"{productName}-{version}.dist-info/WHEEL", wheel_info)

        # 3. Write the RECORD file last
        records.append(f"{productName}-{version}.dist-info/RECORD,,")
        zf.writestr(
            f"{productName}-{version}.dist-info/RECORD",
            "\n".join(records).encode("utf-8"),
        )

    pluginManager.auditWheel(runtime.getRuntimePath(), wheelPath, outputPath)

    logger.info(f"Successfully built {wheel_name}")
    return wheelPath


def main():
    parser = argparse.ArgumentParser(
        description="Build a Python wheel.",
        epilog="(C) Copyright 2026 by RSJ Software GmbH Germering. All rights reserved.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--library", action="store_true", help="Create library")
    parser.add_argument("executable", type=pathlib.Path, help="Executable")
    parser.add_argument(
        "outputPath", type=pathlib.Path, help="Path to the output directory."
    )
    args = parser.parse_args()

    createWheel(args.executable, args.outputPath, library=args.library)


if __name__ == "__main__":
    main()