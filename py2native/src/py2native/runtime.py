import sys
import shutil
import subprocess
import logging

logger = logging.getLogger(__name__)

from .utils import getBuildPath, isFreeThreaded
from . import pristine
from .plugin import pluginManager

runtimePath = None

def getRuntimePath():

    global runtimePath
    if runtimePath is not None:
        return runtimePath

    versionInfo = sys.version_info
    pythonVersion = f"{versionInfo.major}.{versionInfo.minor}"

    if isFreeThreaded():
        pythonVersion += "t"

    pristinePath = pristine.getPristinePython()

    return pluginManager.getRuntimeLibPath(pristinePath, getBuildPath())
