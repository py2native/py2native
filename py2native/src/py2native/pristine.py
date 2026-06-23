import logging

logger = logging.getLogger(__name__)

from .utils import withEnv, system, getBuildPath
from .plugin import pluginManager

pristinePath = None

def getPristinePython():
    global pristinePath

    if pristinePath:
        return pristinePath

    buildPath = getBuildPath()

    pristinePath = buildPath / "python"

    #shutil.rmtree(pristinePath, ignore_errors=True)
    pristinePath.mkdir(parents=True, exist_ok=True)

    installSelector, orgVersionName = pluginManager.getInstallSelector()

    wrkPath = findPython(pristinePath, orgVersionName)

    if wrkPath:
        logger.info(f"Found existing pristine Python at {wrkPath}")
        pristinePath = wrkPath
        return wrkPath

    with withEnv("UV_PYTHON_INSTALL_DIR", str(pristinePath)):
        system(f"uv python install {installSelector}")

    logger.info(f"Installed pristine Python at {pristinePath}")

    pristinePath = findPython(pristinePath, orgVersionName)

    logger.info(f"Using pristine Python at {pristinePath}")

    return pristinePath

def findPython(basePath, versionName):
    preferred = []
    found = []

    for candidate in basePath.glob("cpython-*"):
        if candidate.is_dir():
            name = candidate.name
            found.append(name)
            if versionName in name:
                preferred.append(name)

    if len(found):
        ret = sorted(preferred or found)[0]
        return basePath / ret
