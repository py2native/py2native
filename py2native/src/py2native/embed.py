import shutil
import os

from contextlib import contextmanager

from . utils import system
from . import pristine

from .plugin import pluginManager

@contextmanager
def chdir(target):
    cwd = os.getcwd()
    try:
        os.chdir(target)
        yield
    finally:
        os.chdir(cwd)


def embed(targetPath, exePath=None, whlPath=None, sourcePath=None):
    shutil.rmtree(targetPath, ignore_errors=True)

    pristinePythonPath = pristine.getPristinePython()
    buildPath = pristine.getBuildPath()

    targetPath.mkdir(parents=True, exist_ok=True)

    shutil.copytree(pristinePythonPath, targetPath, dirs_exist_ok=True)

    targetPython = pluginManager.ensureDynload(targetPath)

    global reqPath
    reqPath = buildPath / "requirements.txt"
    reqPath = reqPath.resolve()

    with chdir(sourcePath):
        system(f"uv export --no-dev --output-file {str(reqPath)}")

    system(f"uv pip install --python {str(targetPython.resolve())} --no-deps -r {str(reqPath)} --break-system-packages")

    if exePath:
        wrkPath = pluginManager.getExecutablePath(targetPath)
        wrkPath.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exePath, wrkPath)

    if whlPath:
        system(f"uv pip install --python {str(targetPython.resolve())} --break-system-packages {str(whlPath)}")
    return

