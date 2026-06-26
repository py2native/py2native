import argparse
import logging
import pathlib
# Let distutils emit all messages; DistutilsFilter in main() controls visibility
try:
    from setuptools._distutils import log as distutils_log
    distutils_log.set_verbosity(2)
except Exception:
    pass

logger = logging.getLogger("py2native")

# __package__ = "py2native"

from .builder import build
from .plugin import pluginManager

buildPath = None


def main():
    parser = argparse.ArgumentParser(
        description="Py2Native - Compile Python to Native Code",
        epilog="(C) Copyright 2026 by RSJ Software GmbH Germering. All rights reserved.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )

    parser.add_argument(
        "--verbose", action="store_true", help="Enable debug logging output"
    )

    subParsers = parser.add_subparsers(title="Command", dest="command")

    buildParser = subParsers.add_parser("build", help="Build the executable")
    buildParser.add_argument("--embed", type=pathlib.Path, help="Embedded directory to build")
    buildParser.add_argument("--wheel", type=pathlib.Path, help="Create Wheel")
    buildParser.add_argument("--library", action="store_true", help="Create library")
    buildParser.add_argument("--base", type=pathlib.Path, default=pathlib.Path("."), help="Base directory")
    buildParser.add_argument("--no-console", action="store_true", help="Disable console")
    buildParser.add_argument("--exe", type=str, default=None, help="Output executable name (default: derived from main module)")
    buildParser.add_argument("--version", type=str, default=None, help="Version")
    buildParser.add_argument("--policy", type=str, default=None, help="Policy")
    pluginManager.extendBuildParser(buildParser)
    buildParser.add_argument("mainModule", type=str, help="Main modules")
    buildParser.add_argument("sources", type=str, nargs="+", help="Source files")
    buildParser.set_defaults(func=build)

    pluginManager.extendSubParsers(subParsers)

    args = parser.parse_args()

    logging.raiseExceptions = False

    class DistutilsFilter(logging.Filter):
        def filter(self, record):
            if record.name == "root" and record.levelno < logging.WARNING:
                if args.verbose:
                    record.levelno = logging.DEBUG
                    record.levelname = "DEBUG"
                    # Truncate long distutils command lines that choke RichHandler
                    if len(record.msg) > 500:
                        record.msg = record.msg[:250] + " ... " + record.msg[-200:]
                    return True
                return False
            return True

    from rich.logging import RichHandler

    class ModuleFormatter(logging.Formatter):
        def format(self, record):
            record.module_short = record.name.rsplit(".", 1)[-1] if "." in record.name else record.name
            return super().format(record)

    handler = RichHandler(
        show_path=False,
        show_time=False,
        show_level=False,
        markup=True,
        rich_tracebacks=True,
    )
    handler.setFormatter(ModuleFormatter("[dim]%(levelname)-5s[/dim] [cyan]%(module_short)s[/cyan]: %(message)s"))
    handler.addFilter(DistutilsFilter())
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG if args.verbose else logging.INFO)

    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return

    func(args)


if __name__ == "__main__":
    main()
