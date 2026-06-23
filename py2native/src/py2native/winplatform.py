import sys
import sysconfig
import pathlib
import shutil
import os
import logging

logger = logging.getLogger(__name__)

from .wintemplate import configTemplate
from .utils import PlatformCompiler, configureCompiler, isFreeThreaded

class Plugin:
    
    def __init__(self, pluginManager):
        if sys.platform != "win32":
            raise Exception("Unsupported platform")

        self.pluginManager = pluginManager

        self.toolchain = os.environ.get("PY2_MINGW32")
        self._use_mingw = False

    def extendBuildParser(self, buildParser):
        #buildParser.add_argument("--no-console", action="store_true", help="Disable console")
        pass

    def extendBuild(self, args):
        self.noConsole = args.no_console
        self.library = args.library

    def _find_mingw_compiler(self):
        """Return the path to the MinGW clang compiler (forward slashes), or None."""
        winPlatform = (sysconfig.get_platform() or "").lower()
        if "arm64" in winPlatform:
            compilerName = "aarch64-w64-mingw32-clang.exe"
        else:
            compilerName = "x86_64-w64-mingw32-clang.exe"

        # 1. Try the configured toolchain directory.
        if self.toolchain and self.toolchain.exists():
            candidate = self.toolchain / "bin" / compilerName
            if candidate.is_file():
                return candidate.as_posix()

        # 2. Search PATH for a globally installed compiler.
        found = shutil.which(compilerName)
        if found:
            return found.replace("\\", "/")

        return None

    def newCompiler(self, noInit=False):
        from setuptools._distutils.ccompiler import new_compiler

        mingw_cc = self._find_mingw_compiler()

        if mingw_cc:
            os.environ["CC"] = mingw_cc
            os.environ["CXX"] = f"{mingw_cc}++"
            os.environ["LDSHARED"] = f"{mingw_cc} -shared"
            logger.info("Using MinGW compiler: %s", mingw_cc)
        else:
            for var in ("CC", "CXX", "LDSHARED"):
                os.environ.pop(var, None)

        self._use_mingw = mingw_cc is not None
        try:
            compiler = new_compiler(compiler="mingw32" if self._use_mingw else None)
        except Exception:
            if self._use_mingw:
                logger.warning(
                    "MinGW compiler init failed, falling back to MSVC"
                )
                for var in ("CC", "CXX", "LDSHARED"):
                    os.environ.pop(var, None)
                self._use_mingw = False
                compiler = new_compiler(compiler=None)
            else:
                raise

        configVars = sysconfig.get_config_vars()
        lib_dir = pathlib.Path(configVars.get("installed_platbase")) / "libs"
        if lib_dir.exists():
            compiler.add_library_dir(str(lib_dir))
        configureCompiler(compiler, noInit=noInit)

        # Collect args from cross-cutting plugins (e.g. Pro LTO flags).
        compile_args = ["-flto"] if self._use_mingw else ["/GL"]
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
        return {
         "objSuffix": ".o" if self._use_mingw else ".obj",
         "exeSuffix": ".exe",
         "extSuffix": ".pyd"
        }

    def getExtraSources(self, modBuildPath, exeName):
        rcPath = (modBuildPath / exeName).with_suffix(".rc")
        if rcPath.exists():
            return [rcPath]
        return []

    def getCompileLibArgs(self):
        return []

    def getLinkerArgs(self, exeName, libraryPath):

        if self.noConsole:
            subsystem = "WINDOWS"
        else:
            subsystem = "CONSOLE"

        py_lib = f"python{sys.version_info.major}{sys.version_info.minor}"

        ret = {
            "extraObjects":[] if self._use_mingw else ["kernel32.lib", "ucrt.lib", "vcruntime.lib"],
            "linkerArgs": ["-flto", "-municode", f"-m{subsystem.lower()}", "-l", py_lib] if self._use_mingw else ["/ENTRY:wmainCRTStartup", f"/SUBSYSTEM:{subsystem}", "/LTCG"],
            "libraryDirs": [],
            "libraries": [],
            "runtimeLibraryDirs": [],
            "libraryLinkerArgs": ["-l", py_lib] if self._use_mingw else [],
            }

        return ret

    def appendExecutable(self, exePath, zipPath):
        if zipPath.exists():
            zipContent = zipPath.read_bytes()
            with exePath.open("ab") as f:
                f.write(zipContent)

    def getConfigTemplate(self):
        return configTemplate

    def fixPlatformName(self, plat_name):
        return plat_name

    def auditWheel(self, runtimePath, wheelPath, outputPath):  #
        shutil.copy2(wheelPath, outputPath / wheelPath.name)

    def getRuntimeLibraries(self, productName, version, rlibraryPath):
        dllPath = pathlib.Path(sys.base_prefix)
        if dllPath.exists():
            for dll in dllPath.glob("python*.dll"):
                yield (f"{productName}-{version}.data/scripts/{dll.name}", dll.read_bytes())

    def ensureDynload(self, targetPath):
        return targetPath / "python.exe"

    def getInstallSelector(self):
        versionInfo = sys.version_info
        versionNameShort = f"{versionInfo.major}.{versionInfo.minor}"
        orgVersionName = f"{versionInfo.major}.{versionInfo.minor}.{versionInfo.micro}"

        # Match pristine runtime architecture to the active interpreter ABI.
        # On Windows ARM, uv can resolve an emulated x86_64 interpreter for 3.14t.
        winPlatform = (sysconfig.get_platform() or "").lower()
        if "arm64" in winPlatform:
            winArch = "aarch64"
        else:
            winArch = "x86_64"

        if isFreeThreaded():
            installSelector = f"cpython-{versionNameShort}+freethreaded-windows-{winArch}-none"
        else:
            installSelector = f"cpython-{versionNameShort}-windows-{winArch}-none"

        return installSelector, orgVersionName

    def getRuntimeLibPath(self, pristinePath, buildPath):
        versionInfo = sys.version_info

        return pristinePath / f"python{versionInfo.major}{versionInfo.minor}.dll"

    def getExecutableName(self, mainModule):

        if self.library:

            ext_suffix = ".pyd"
            exeName = f"{mainModule}{ext_suffix}"
        else:
            exeName = f'{mainModule}.exe'

        return exeName

    def getExecutablePath(self, targetPath):
        return targetPath

    def getExePath(self, path, name):
        p1 = pathlib.Path(path)
        p1 = p1.parent / name
        return p1.with_suffix(".exe")

    def resolveExePath(self, exePath):
        # MSVC appends .exe automatically — if the expected path
        # doesn't exist, try with .exe extension
        if not exePath.exists():
            exePathExe = exePath.with_suffix(".exe")
            if exePathExe.exists():
                return exePathExe
        return exePath