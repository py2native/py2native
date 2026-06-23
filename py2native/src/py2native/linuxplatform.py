import logging
import os
import pathlib
import shutil
import stat
import sys
import sysconfig

logger = logging.getLogger(__name__)

from .othertemplate import configTemplate
from .utils import PlatformCompiler, configureCompiler, isFreeThreaded, system, withEnv


class Plugin:
    def __init__(self, pluginManager):
        if sys.platform != "linux":
            raise Exception("Unsupported platform")

        self.pluginManager = pluginManager

    def extendBuild(self, args):
        self.library = args.library

    def newCompiler(self, noInit=False):
        from setuptools._distutils.ccompiler import new_compiler

        compiler = new_compiler()
        configVars = sysconfig.get_config_vars()

        for libDirVar in ["LIBPL", "LIBDIR"]:
            libDir = configVars.get(libDirVar)
            if libDir:
                compiler.add_library_dir(libDir)

        libraryName = configVars.get("LIBRARY")
        if libraryName and libraryName.startswith("lib"):
            compiler.add_library(pathlib.Path(libraryName).stem[3:])

        # Keep dependent/system libraries after libpython for static-link resolution.
        for libGroup in [
            configVars.get("LIBS", ""),
            configVars.get("SYSLIBS", ""),
            "-lm -lz",
        ]:
            for token in libGroup.split():
                if token.startswith("-l") and len(token) > 2:
                    compiler.add_library(token[2:])

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

    def getCompileBasics(self):
        return {"objSuffix": ".o", "exeSuffix": "", "extSuffix": ".so"}

    def getExtraSources(self, modBuildPath, exeName):
        return []

    def getCompileLibArgs(self):
        return ["-fPIC"]

    def getLinkerArgs(self, exeName, libraryPath):
        configVars = sysconfig.get_config_vars()

        libraryName = libraryPath.name[3:]
        libraryName = libraryName.split(".")
        libraryName = f"{libraryName[0]}.{libraryName[1]}"

        library_dirs = [str(libraryPath.parent)]

        ret = {
            "extraObjects": [],
            "linkerArgs": configVars.get("LINKFORSHARED", "").split(" ")
            + [
                # "--no-pie",
                "-Wl,-rpath,$ORIGIN",
            ],
            "libraryDirs": [str(libraryPath.parent)],
            "libraries": [libraryName],
            "runtimeLibraryDirs": [
                "$ORIGIN",
                str(libraryPath.resolve().parent),
            ],
            "libraryLinkerArgs": [],
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
        return plat_name

    def auditWheel(self, runtimePath, wheelPath, outputPath):
        if self.library:
            runtimeLibName = runtimePath.name
            runtimeBaseName = runtimeLibName.split(".so")[0] + ".so"
            # Exclude both the base .so and any versioned suffix like .so.1.0
            exclude_args = f"--exclude {runtimeBaseName}"
            if runtimeLibName != runtimeBaseName:
                exclude_args += f" --exclude {runtimeLibName}"
            if not runtimeLibName.endswith(".so.1.0") and not runtimeBaseName.endswith(
                ".so.1.0"
            ):
                exclude_args += f" --exclude {runtimeBaseName}.1.0"

            # auditwheel needs to *locate* the excluded library during
            # dependency analysis even though it won't vendor it. Add the
            # runtime library directory to LD_LIBRARY_PATH for the subprocess.
            lib_dir = str(runtimePath.resolve().parent)
            old_ld = os.environ.get("LD_LIBRARY_PATH", "")
            new_ld = f"{lib_dir}:{old_ld}" if old_ld else lib_dir
            with withEnv("LD_LIBRARY_PATH", new_ld):
                system(f"auditwheel repair {exclude_args} {wheelPath} -w {outputPath}")
        else:
            # For executable wheels, auditwheel creates a wrapper script that breaks
            # uv run. The RPATH is already correct ($ORIGIN), so just copy the wheel.
            shutil.copy2(wheelPath, outputPath / wheelPath.name)

    def getRuntimeLibraries(self, productName, version, libraryPath):
        # Place libpython next to the binary so $ORIGIN RPATH resolves.
        # Yield the exact resolved file
        yield (
            f"{productName}-{version}.data/scripts/{libraryPath.name}",
            libraryPath.read_bytes(),
        )

        # Also yield the base .so name if different, to be safe
        baseName = libraryPath.name.split(".so")[0] + ".so"
        if baseName != libraryPath.name:
            yield (
                f"{productName}-{version}.data/scripts/{baseName}",
                libraryPath.read_bytes(),
            )

        # Also yield .so.1.0 just in case
        so10Name = baseName + ".1.0"
        if so10Name != libraryPath.name and so10Name != baseName:
            yield (
                f"{productName}-{version}.data/scripts/{so10Name}",
                libraryPath.read_bytes(),
            )

    def ensureDynload(self, targetPath):
        versionInfo = sys.version_info
        versionNameShort = f"{versionInfo.major}.{versionInfo.minor}"

        host_dynload = (
            pathlib.Path(sys.base_prefix)
            / "lib"
            / f"python{versionNameShort}"
            / "lib-dynload"
        )
        embed_dynload = targetPath / "lib" / f"python{versionNameShort}" / "lib-dynload"

        if not host_dynload.exists():
            return targetPath / "bin" / "python"

        # Ensure dynamically loaded stdlib extension modules are present in the embedded runtime.
        embed_dynload.mkdir(parents=True, exist_ok=True)
        shutil.copytree(host_dynload, embed_dynload, dirs_exist_ok=True)

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
        version = sys.version_info
        pythonVersion = f"{version.major}.{version.minor}"

        libDir = pristinePath / "lib"
        candidates = [
            libDir / f"libpython{pythonVersion}.so",
            libDir / f"libpython{pythonVersion}.so.1.0",
        ]
        candidates.extend(sorted(libDir.glob(f"libpython{pythonVersion}.so*")))
        candidates.extend(sorted(libDir.glob("libpython*.so*")))

        for candidate in candidates:
            if candidate.exists():
                runtimePath = candidate
                # Ensure the returned path ends with .so instead of .so.1.0
                if runtimePath.name.endswith(".so.1.0"):
                    so_path = runtimePath.with_name(runtimePath.name[:-4])
                    if so_path.exists():
                        runtimePath = so_path
                return runtimePath

        raise FileNotFoundError(
            f"Could not locate libpython shared library under {libDir}"
        )

    def getExecutableName(self, mainModule):

        if self.library:
            configVars = sysconfig.get_config_vars()
            ext_suffix = configVars.get("EXT_SUFFIX") or ".so"
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
