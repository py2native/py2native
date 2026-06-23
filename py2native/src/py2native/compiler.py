import collections
import logging
import pathlib

logger = logging.getLogger(__name__)

from . import runtime, templates
from .plugin import pluginManager
from .utils import capture_output, getBuildPath, isFreeThreaded, pythonCall, template


def _dedupe_keep_order(items):
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _format_filenames(paths, width=72):
    """Format a list of paths as comma-separated filenames, wrapping at *width* chars.
    Returns a single string; RichHandler indents continuation lines automatically."""
    names = [pathlib.Path(str(p)).name for p in paths]
    if not names:
        return ""
    lines = []
    current = ""
    for name in names:
        candidate = f"{current}{name}, " if current else f"{name}, "
        if len(candidate) > width and current:
            lines.append(current.rstrip(", "))
            current = f"{name}, "
        else:
            current = candidate
    if current:
        lines.append(current.rstrip(", "))
    return "\n".join(lines)


def patchEmbeddedBootstrap(bootstrapCPath, sharedModuleName):
    content = bootstrapCPath.read_text()

    # Inject config template (home detection etc.)
    marker = "PyConfig_InitPythonConfig(&config);"
    if marker in content:
        inject = pluginManager.getConfigTemplate()
        content = content.replace(marker, inject, 1)

    # With --embed-modules, Cython registers the shared module automatically.
    # Patch 3 is no longer needed since there's no dotted parent name.

    bootstrapCPath.write_text(content)


def getCompiler(noInit=False):
    return pluginManager.newCompiler(noInit=noInit)


def cythonCall(*args):

    if isFreeThreaded():
        args = ["-X", "freethreading_compatible=True", *args]

    pythonCall(f"-m cython -3 --no-docstrings {' '.join(args)}")


def compile(
    sourcePath,
    exeName,
    mainModule,
    sources,
    force=True,
    noConsole=False,
    library=False,
    targetPath=None,
    noInit=False,
    projectMainModule=None,
):

    cwd = pathlib.Path.cwd()
    resolved_source_path = pathlib.Path(sourcePath).resolve()

    if cwd in resolved_source_path.parents or cwd == resolved_source_path:
        relPath = resolved_source_path.relative_to(cwd)
    else:
        # Fallback if sourcePath is not under cwd
        relPath = resolved_source_path.name

    modBuildPath = getBuildPath() / relPath
    modBuildPath.mkdir(parents=True, exist_ok=True)

    cSources = []
    objects = []
    pySources = []

    modules = []

    packageModules = collections.defaultdict(list)
    qualifiedModules = []

    basicInfo = pluginManager.getCompileBasics()
    objSuffix = basicInfo["objSuffix"]
    exeSuffix = basicInfo["exeSuffix"]

    cSources += pluginManager.getExtraSources(modBuildPath, exeName)

    sourceSet = set()
    for source in sources:
        if isinstance(source, pathlib.Path):
            sourcePattern = source.as_posix()
        else:
            sourcePattern = str(source)

        # Python 3.10 pathlib.glob expects a string pattern.
        sourceSet.update(list(sourcePath.glob(sourcePattern)))
    sources = sorted(list(sourceSet))

    for filePath in sources:
        modName = filePath.stem
        if modName != "__init__":
            if filePath.parent == sourcePath:
                package = ""
            else:
                package = filePath.parent.stem
            objPath = (modBuildPath / modName).with_suffix(objSuffix)
        else:
            continue

        dirty = True
        if not force:
            if objPath.exists():
                if objPath.stat().st_mtime > filePath.stat().st_mtime:
                    dirty = False

        packageModules[package].append(modName)
        modules.append(modName)

        if package:
            qualifiedModules.append(f"{package}.{modName}")
        else:
            qualifiedModules.append(modName)

        if dirty:
            pySources.append(filePath)
            cSources.append((modBuildPath / modName).with_suffix(".c"))
        else:
            objects.append(objPath)

    packages = list(filter(lambda x: len(x) > 0, packageModules.keys()))

    extensions = {"pxd": {}, "code": {}, "features": {}, "exports": {}}

    newExtensions = pluginManager.extendTemplate()

    if newExtensions:
        extensions |= newExtensions

    sharedName = "_p2n_shared"

    sharedPath = modBuildPath / "_p2n_shared.c"
    cythonCall("--generate-shared", str(sharedPath), "--module-name", sharedName)

    cSources.append(sharedPath)

    code = ""
    for k, v in extensions["code"].items():
        code += f"{v}\n"

    pxd = ""
    for k, v in extensions["pxd"].items():
        pxd += f"{v}\n"

    sourceDirs = set([modBuildPath])

    for pySource in pySources:
        sourceDirs.add(pySource.parent)

    for sourceDir in sourceDirs:
        pxdPath = sourceDir / "_p2n_bootstrap.pxd"

        if pxd:
            pxdPath.write_text(pxd)
        else:
            pxdPath.unlink(missing_ok=True)

    entry_package = None
    entry_module = projectMainModule or mainModule
    if library and entry_module and "." in entry_module:
        entry_package = entry_module.split(".", 1)[0]

    template(
        templates.bootstrapTemplate,
        modBuildPath / "_p2n_bootstrap.pyx",
        modules=packageModules[""] + packages,
        package="__main__",
        packages=packages,
        qualifiedModules=qualifiedModules,
        mainModule=mainModule,
        code=code,
        features=extensions["features"],
        exports=extensions["exports"],
        debug=False,
    )

    template(
        templates.headerTemplate,
        modBuildPath / "__main__.h",
        modules=packageModules[""],
        packages=packages,
    )

    cythonCall(
        "--embed",
        "--shared",
        sharedName,
        "--embed-modules",
        sharedName,
        str(modBuildPath / "_p2n_bootstrap.pyx"),
    )
    if not (modBuildPath / "_p2n_bootstrap.c").exists():
        raise FileNotFoundError(
            f"Expected generated file not found: {modBuildPath / '_p2n_bootstrap.c'}. "
            "Cython invocation likely did not run correctly."
        )
    patchEmbeddedBootstrap(modBuildPath / "_p2n_bootstrap.c", sharedName)
    # In library builds the embedded bootstrap's main() is never called —
    # the wheel's __init__.py handles finder, cython_runtime, and import
    # order itself.  Excluding it avoids potential symbol conflicts with
    # _p2n_shared.c when that file is compiled with noInit=False (i.e. it
    # exports a real PyInit__p2n_shared that Python's import machinery
    # invokes directly).
    if not library:
        cSources.append(modBuildPath / "_p2n_bootstrap.c")

    for package in packages:
        package_code = ""
        package_features = None
        package_exports = None
        if library and entry_package == package:
            package_code = code
            package_features = extensions["features"]
            package_exports = extensions["exports"]

        template(
            templates.bootstrapTemplate,
            modBuildPath / f"{package}.pyx",
            modules=packageModules[package],
            package=package,
            qualifiedModules=qualifiedModules,
            packages=[],
            code=package_code,
            features=package_features,
            exports=package_exports,
            debug=False,
        )
        if package_code:
            (modBuildPath / f"{package}.pxd").write_text(pxd)
        else:
            (modBuildPath / f"{package}.pxd").unlink(missing_ok=True)
        template(
            templates.headerTemplate,
            modBuildPath / f"{package}.h",
            modules=packageModules[package],
            package=package,
            packages=[],
        )

        pySources.append((modBuildPath / package).with_suffix(".pyx"))

        cSources.append((modBuildPath / package).with_suffix(".c"))

    if len(pySources):
        pySources = list(map(str, pySources))
        rest = pySources
        while len(rest):
            batch = rest[:20]
            args = []
            for sd in sourceDirs:
                args.extend(["-I", str(sd)])
            args.extend(["--output-file", str(modBuildPath), "--shared", sharedName])
            args.extend(batch)
            cythonCall(*args)
            rest = rest[20:]

    cSourcesRel = []

    for cSource in cSources:
        try:
            cSourcesRel.append(str(cSource))
        except Exception:
            logger.warning("Problem resolving %s", cSource)

    cSourcesRel = _dedupe_keep_order(cSourcesRel)

    logger.info("Source files: %s", _format_filenames(cSourcesRel))

    # Split: bootstrap needs the full API (PyConfig_* calls), so it is
    # always compiled with noInit=True (no Py_LIMITED_API, no PyInit export).
    # Everything else (modules + shared.c) uses the caller's noInit value,
    # which controls both Py_LIMITED_API and CYTHON_NO_PYINIT_EXPORT.
    _bootstrap_name = "_p2n_bootstrap.c"
    bootstrap_sources = [
        s for s in cSourcesRel if pathlib.Path(s).name == _bootstrap_name
    ]
    module_sources = [s for s in cSourcesRel if pathlib.Path(s).name != _bootstrap_name]

    for sources, _noInit in (
        (bootstrap_sources, True),
        (module_sources, noInit),
    ):
        if not sources:
            continue
        logger.info("Compiling %s (noInit=%s)", _format_filenames(sources), _noInit)
        compiler = getCompiler(noInit=_noInit)
        compiler._library = library
        with capture_output() as cap:
            try:
                compiled = compiler.compile(sources)
            except Exception:
                output = cap.getvalue().strip()
                if output:
                    logger.debug("Compiler output: %s", output)
                raise
        output = cap.getvalue().strip()
        if output:
            logger.debug("Compiler output: %s", output)
        for co in compiled:
            objects.append(pathlib.Path(co))

    outputName = pathlib.Path(exeName).stem

    libraryPath = runtime.getRuntimePath()

    objects = list(map(str, objects))
    objects = _dedupe_keep_order(objects)
    logger.info("Objects %s", _format_filenames(objects))

    compiler = getCompiler()
    compiler._library = library
    compiler._libraryPath = libraryPath

    if library:
        logger.info("Linking shared object: %s -> %s", outputName, exeName)
        with capture_output() as cap:
            compiler.link_shared_object(objects, exeName, output_dir=str(targetPath))
        output = cap.getvalue().strip()
        if output:
            logger.debug("Linker output: %s", output)
        exePath = targetPath / exeName

    else:
        with capture_output() as cap:
            compiler.link_executable(objects, outputName, output_dir=str(targetPath))
        output = cap.getvalue().strip()
        if output:
            logger.debug("Linker output: %s", output)

        exePath = targetPath / exeName
        exePath = pluginManager.resolveExePath(exePath)

        pluginManager.appendExecutable(exePath, targetPath / "library.zip")

        pluginManager.makeExecutable(exePath)

    return exePath
