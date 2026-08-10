import stat
import os
import os.path
import sys
import shutil
import logging
import pathlib
import contextlib
import subprocess
import shlex
import sysconfig

logger = logging.getLogger(__name__)


buildPath = None

def getBuildPath():
    global buildPath
    if buildPath is None:
        buildPath = pathlib.Path("./.py2native_build")
        buildPath.mkdir(exist_ok=True, parents=True)
        gitignore = buildPath / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n!.gitignore")
    return buildPath


@contextlib.contextmanager
def capture_output():
    """Capture fd 1/2 output into a buffer, drained by a background thread.

    Unlike the old captureOutput(), the pipe is drained concurrently so
    subprocesses never block.  Returns the captured text when the block
    exits — usable in an ``if output: logger.debug(output)`` pattern.
    """
    import io, threading

    buf = io.StringIO()
    r, w = os.pipe()
    old_out = os.dup(1)
    old_err = os.dup(2)

    def _drain():
        try:
            while True:
                data = os.read(r, 65536)
                if not data:
                    break
                buf.write(data.decode(errors='replace'))
        except OSError:
            pass

    drainer = threading.Thread(target=_drain, daemon=True)
    # Quiet the root logger so distutils log.info() doesn't leak to console
    # via handlers that might bypass fd-level redirection (e.g. RichHandler).
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.ERROR)
    try:
        os.dup2(w, 1)
        os.dup2(w, 2)
        os.close(w)
        drainer.start()
        yield buf
    finally:
        root.setLevel(old_level)
        # Flush Python-level buffers to the pipe before restoring fds.
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(old_out, 1)
        os.dup2(old_err, 2)
        os.close(old_out)
        os.close(old_err)
        os.close(r)
        drainer.join(timeout=5)


def chmodRW(path):
    path.chmod(path.stat().st_mode | stat.S_IWRITE | stat.S_IREAD | stat.S_IWUSR | stat.S_IRUSR | stat.S_IWGRP | stat.S_IRGRP)

def system(cmd):
    args = shlex.split(cmd, posix=(os.name != "nt"))
    path = os.environ.get("PATH", "")
    localBin = f".{os.sep}bin"
    newPath = f"{localBin}{os.pathsep}{path}" if path else localBin
    with withEnv("PATH", newPath):
        result = subprocess.run(
            args,
            shell=False,
            text=True,
            timeout=600,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        out = result.stdout or ""
        if result.returncode:
            raise Exception(f"Command failed: {cmd}\nlog: {out}")
        return result.returncode

def pythonCall(cmd):
    exePath = pathlib.Path(sys.executable)

    from .plugin import pluginManager

    pythonPath = pluginManager.getExePath(exePath, "python")

    system(f"{str(pythonPath)} {cmd}")

def copytree(src, dst, symlinks=False, ignore=None):
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            if not os.path.isdir(d):
                shutil.copytree(s, d, symlinks, ignore)
            else:
                copytree(s, d, symlinks, ignore)
        else:

            shutil.copy2(s, d)

def template(templatePath, targetPath, **kwargs):

    from Cython.Tempita import Template

    if isinstance(templatePath, pathlib.Path):
        templateString = templatePath.read_text()
    else:
        templateString = templatePath

    templateObj = Template(templateString)

    content = templateObj.substitute(**kwargs)

    targetPath.write_text(content)

@contextlib.contextmanager
def withEnv(name, value):
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            del os.environ[name]
        else:
            os.environ[name] = old

def isFreeThreaded():
    return sysconfig.get_config_vars().get("Py_GIL_DISABLED") == 1


class PlatformCompiler:
    """Wraps a distutils CCompiler with platform-specific compile/link arguments.

    All platform knowledge is injected at construction time — no pluginManager
    dispatch occurs at call time.  The caller in compiler.py sees a plain
    CCompiler interface and never passes platform-specific flags.
    """

    def __init__(self, compiler, *, compile_args=None, compile_lib_args=None,
                 get_linker_args=None):
        self._compiler = compiler
        self._compile_args = list(compile_args or [])
        self._compile_lib_args = list(compile_lib_args or [])
        self._get_linker_args = get_linker_args  # fn(progname, libPath) -> dict
        self._library = False
        self._libraryPath = None

    def __getattr__(self, name):
        return getattr(self._compiler, name)

    # -- compile ---------------------------------------------------------------

    def compile(self, sources, output_dir=None, macros=None, include_dirs=None,
                debug=0, extra_preargs=None, extra_postargs=None, depends=None):
        extra = list(extra_postargs or [])
        extra.extend(self._compile_args)
        if self._library:
            extra.extend(self._compile_lib_args)
        return self._compiler.compile(
            sources,
            output_dir=output_dir,
            macros=macros,
            include_dirs=include_dirs,
            debug=debug,
            extra_preargs=extra_preargs,
            extra_postargs=extra,
            depends=depends,
        )

    # -- link ------------------------------------------------------------------

    def _linker_info(self, output_name):
        if self._get_linker_args:
            return self._get_linker_args(output_name, self._libraryPath) or {}
        return {}

    def link_executable(self, objects, output_progname, output_dir=None,
                        libraries=None, library_dirs=None,
                        runtime_library_dirs=None,
                        debug=0, extra_preargs=None, extra_postargs=None,
                        target_lang=None):
        info = self._linker_info(output_progname)
        entangle = info.get("linkerArgsEntangle", [])

        all_objects = list(objects) + list(info.get("extraObjects", []))
        all_library_dirs = list(library_dirs or []) + info.get("libraryDirs", [])
        all_libraries = list(libraries or []) + info.get("libraries", [])
        all_runtime_dirs = list(runtime_library_dirs or []) + info.get("runtimeLibraryDirs", [])
        all_preargs = list(extra_preargs or []) + info.get("linkerArgs", []) + entangle
        # Deduplicate while preserving order
        _seen = set()
        all_libraries = [x for x in all_libraries if not (x in _seen or _seen.add(x))]
        _seen.clear()
        all_library_dirs = [x for x in all_library_dirs if not (x in _seen or _seen.add(x))]

        try:
            return self._compiler.link_executable(
                all_objects, output_progname,
                output_dir=output_dir,
                libraries=all_libraries,
                library_dirs=all_library_dirs,
                runtime_library_dirs=all_runtime_dirs,
                debug=debug,
                extra_preargs=all_preargs,
                extra_postargs=extra_postargs,
                target_lang=target_lang,
            )
        except Exception as e:
            import sys
            print(f"Link failed: {e}", file=sys.stderr)
            raise

    def link_shared_object(self, objects, output_filename, output_dir=None,
                           libraries=None, library_dirs=None,
                           runtime_library_dirs=None, export_symbols=None,
                           debug=0, extra_preargs=None, extra_postargs=None,
                           target_lang=None):
        info = self._linker_info(output_filename)
        entangle = info.get("linkerArgsEntangle", [])

        all_objects = list(objects) + list(info.get("extraObjects", []))
        all_library_dirs = list(library_dirs or []) + info.get("libraryDirs", [])
        all_libraries = list(libraries or []) + info.get("libraries", [])
        all_runtime_dirs = list(runtime_library_dirs or []) + info.get("runtimeLibraryDirs", [])
        all_preargs = list(extra_preargs or []) + info.get("libraryLinkerArgs", []) + entangle
        # Deduplicate while preserving order
        _seen = set()
        all_libraries = [x for x in all_libraries if not (x in _seen or _seen.add(x))]
        _seen.clear()
        all_library_dirs = [x for x in all_library_dirs if not (x in _seen or _seen.add(x))]

        return self._compiler.link_shared_object(
            all_objects, output_filename,
            output_dir=output_dir,
            libraries=all_libraries,
            library_dirs=all_library_dirs,
            runtime_library_dirs=all_runtime_dirs,
            export_symbols=export_symbols,
            debug=debug,
            extra_preargs=all_preargs,
            extra_postargs=extra_postargs,
            target_lang=target_lang,
        )


def configureCompiler(compiler, noInit=False):
    """Apply common compiler configuration shared across all platforms."""
    compiler.define_macro("NDEBUG")
    if noInit:
        compiler.define_macro("CYTHON_NO_PYINIT_EXPORT", 1)
    compiler.define_macro("CYTHON_COMPRESS_STRINGS", 0)
    if isFreeThreaded():
        compiler.define_macro("Py_GIL_DISABLED", 1)
    compiler.add_include_dir(sysconfig.get_path("include"))

    # -- limited / stable ABI -------------------------------------------------
    # Define Py_LIMITED_API for library builds so the compiled .pyd / .so /
    # .dylib works across Python minor versions without recompilation.
    # Exe builds skip this because the embedding bootstrap uses PyConfig_*
    # functions that live outside the stable ABI.
    py_hex = (sys.version_info.major << 24) | (sys.version_info.minor << 16)

    if not noInit and py_hex >= 0x030b0000 and not isFreeThreaded():
        compiler.define_macro("Py_LIMITED_API", py_hex)

    # Allow cross-cutting plugins (e.g. py2nativepro) to add macros.
    from .plugin import pluginManager
    pluginManager.extendCompiler(compiler)
