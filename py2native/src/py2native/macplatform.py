import logging
import pathlib
import platform
import shutil
import stat
import subprocess
import sys
import sysconfig

logger = logging.getLogger(__name__)

from .othertemplate import configTemplate
from .utils import PlatformCompiler, configureCompiler, isFreeThreaded


class Plugin:
    def __init__(self, pluginManager):
        if sys.platform != "darwin":
            raise Exception("Unsupported platform")

        self.pluginManager = pluginManager

    def extendBuild(self, args):
        self.library = args.library

    def newCompiler(self, noInit=False):
        from setuptools._distutils.ccompiler import new_compiler

        compiler = new_compiler()
        configureCompiler(compiler, noInit=noInit)

        compile_args = self.pluginManager.getCompileArgs() or []
        compile_lib_args = self.getCompileLibArgs()

        def get_linker_args(progname, lib_path):
            return self.pluginManager.getLinkerArgs(progname, lib_path)

        return PlatformCompiler(
            compiler,
            compile_args=compile_args,
            compile_lib_args=compile_lib_args,
            get_linker_args=get_linker_args,
        )

    def getCompileLibArgs(self):
        return []

    def getCompileBasics(self):
        return {"objSuffix": ".o", "exeSuffix": "", "extSuffix": ".dylib"}

    def getExtraSources(self, modBuildPath, exeName):
        return []

    def getLinkerArgs(self, exeName, libraryPath):
        if self.library:
            return {
                "extraObjects": [],
                "linkerArgs": [],
                "libraryDirs": [],
                "libraries": [],
                "runtimeLibraryDirs": [],
                "libraryLinkerArgs": ["-undefined", "dynamic_lookup"],
            }

        libraryName = libraryPath.name[3:]
        libraryName = libraryName.split(".")
        libraryName = f"{libraryName[0]}.{libraryName[1]}"

        ret = {
            "extraObjects": [],
            "linkerArgs": [],
            "libraryDirs": [str(libraryPath.parent)],
            "libraries": [libraryName],
            "runtimeLibraryDirs": [
                "@executable_path",
                "@executable_path/../lib",
                f"@executable_path/../lib/{exeName}/",
            ],
            "libraryLinkerArgs": ["-undefined", "dynamic_lookup"],
        }

        return ret

    def makeExecutable(self, exePath):
        exePath.chmod(
            exePath.stat().st_mode
            | stat.S_IEXEC
            | stat.S_IXGRP
            | stat.S_IXOTH
            | stat.S_IXUSR
        )

    def getConfigTemplate(self):
        return configTemplate

    def fixPlatformName(self, plat_name):
        if "universal2" in plat_name:
            # Check the actual physical hardware architecture
            machine = platform.machine().lower()

            if machine == "arm64" or machine == "aarch64":
                # Apple Silicon starts at macOS 11.0, so pip expects 11_0 for arm64 tags
                plat_name = plat_name.replace("10_15_universal2", "11_0_arm64")
                plat_name = plat_name.replace("universal2", "arm64")
            else:
                # Fallback to Intel
                plat_name = plat_name.replace("universal2", "x86_64")

        return plat_name

    def auditWheel(self, runtimePath, wheelPath, outputPath, policy):  #
        shutil.copy2(wheelPath, outputPath / wheelPath.name)

    def getRuntimeLibraries(self, productName, version, libraryPath):
        # Place libpython next to the binary so @executable_path RPATH resolves
        targetName = f"{productName}-{version}.data/scripts/{libraryPath.name}"
        yield (targetName, libraryPath.read_bytes())

    def ensureDynload(self, targetPath):
        return targetPath / "bin" / "python"

    def getInstallSelector(self):
        versionInfo = sys.version_info
        versionNameShort = f"{versionInfo.major}.{versionInfo.minor}"
        orgVersionName = f"{versionInfo.major}.{versionInfo.minor}.{versionInfo.micro}"

        if isFreeThreaded():
            installSelector = f"{versionNameShort}+freethreaded"
        else:
            installSelector = versionNameShort

        return installSelector, orgVersionName

    def getRuntimeLibPath(self, pristinePath, buildPath):
        versionInfo = sys.version_info
        pythonVersion = f"{versionInfo.major}.{versionInfo.minor}"
        if isFreeThreaded():
            pythonVersion += "t"

        libraryName = f"python{pythonVersion}.dylib"
        libraryFileName = f"lib{libraryName}"
        sourcePath = pristinePath / "lib" / libraryFileName

        runtimePath = buildPath / libraryFileName
        shutil.copy2(sourcePath, runtimePath)

        if runtimePath.exists():
            subprocess.run(
                [
                    "install_name_tool",
                    "-id",
                    f"@rpath/{libraryFileName}",
                    str(runtimePath),
                ],
                check=False,
            )

        return runtimePath

    def getExecutableName(self, mainModule):

        if self.library:
            configVars = sysconfig.get_config_vars()
            ext_suffix = configVars.get("EXT_SUFFIX") or ".dylib"
            exeName = f"{mainModule}{ext_suffix}"
        else:
            exeName = f"{mainModule}"

        return exeName

    def getExecutablePath(self, targetPath):
        return targetPath / "bin"

    def getExePath(self, path, name):
        p1 = pathlib.Path(path)
        p1 = p1.parent / name
        return p1

    def resolveExePath(self, exePath):
        return exePath
