import sys
import sysconfig
import json
import base64
import pathlib
import os
import logging

logger = logging.getLogger(__name__)

from . import pristine
from . import whl
from . import compiler
from . import embed

from .utils import getBuildPath

from .plugin import pluginManager

buildPath = None

def _normalize_source_pattern(pattern):
    if pattern.startswith("**."):
        return f"**/*{pattern[2:]}"
    return pattern

def build(args):

    pluginManager.extendBuild(args)

    sourceDirectory = args.base

    mainModule = args.mainModule

    exeName = pluginManager.getExecutableName(args.exe if args.exe else mainModule.split(".")[0])

    sources = []

    for source in args.sources:
        source = _normalize_source_pattern(source)
        for filePath in sourceDirectory.glob(source):
            sources.append(filePath.relative_to(sourceDirectory))

    if args.library:
        sources = [source for source in sources if source.name != "__main__.py"]

    if not sources:
        raise ValueError(
            f"No sources matched in {sourceDirectory}."
            f"Patterns: {args.sources}. "
            f"If running in bash, quote globs like '*.py'."
        )

    pristinePythonPath = pristine.getPristinePython()

    from .compiler import _format_filenames
    source_list = _format_filenames(sources)
    logger.info(f"Compiling {mainModule} with sources {source_list}")
    buildPath = getBuildPath()
    compileMainModule = None if args.library else mainModule

    exePath = compiler.compile(
        sourceDirectory,
        exeName,
        compileMainModule,
        projectMainModule=mainModule,
        sources=sources,
        targetPath=buildPath,
        library=args.library,
        noConsole=args.no_console,
        noInit=not args.library
    )
    logger.info(f"[bold green]Compiled to {exePath}[/bold green]")
    wheelPath = None

    if args.wheel:
        args.wheel.mkdir(parents=True, exist_ok=True)
        logger.info(f"Creating wheel at {args.wheel}")
        moduleNames = [source.stem for source in sources if source.stem != "__init__"] if args.library else None
        wheelPath = whl.createWheel(
            exePath,
            args.wheel,
            library=args.library,
            moduleNames=moduleNames,
            mainModuleName=mainModule if args.library else None,
            sourcePath=sourceDirectory.resolve(),
            version=args.version,
            policy=args.policy
        )
        logger.info(f"Created wheel at {wheelPath}")

    if args.embed:
        if args.library:
            if wheelPath is None:
                logger.info(f"Creating temp wheel at {buildPath}")
                moduleNames = [source.stem for source in sources if source.stem != "__init__"]
                wheelPath = whl.createWheel(
                    exePath,
                    buildPath,
                    library=args.library,
                    moduleNames=moduleNames,
                    mainModuleName=mainModule,
                    sourcePath=sourceDirectory.resolve(),
                    version=args.version,
                    policy=args.policy
                )
                logger.info(f"Created wheel at {wheelPath}")
            logger.info(f"Embedding {wheelPath} into {args.embed}")
            embed.embed(args.embed,  whlPath=wheelPath, sourcePath=sourceDirectory.resolve())
            logger.info(f"Embedded {wheelPath} into {args.embed}")
        else:
            logger.info(f"Embedding {exePath} into {args.embed}")
            embed.embed(args.embed, exePath=exePath, sourcePath=sourceDirectory.resolve())
            logger.info(f"Embedded {exePath} into {args.embed}")
