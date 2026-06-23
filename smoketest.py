# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests",
#     "rich",
# ]
# ///
import argparse
import contextlib
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import platform
import sysconfig
import json

logger = logging.getLogger("smoketest")

import requests

curVersion = "1.14"

@contextlib.contextmanager
def chdir(newDir):
    oldDir = os.getcwd()
    try:
        os.chdir(newDir)
        yield
    finally:
        os.chdir(oldDir)


def uv(cmd):
    cleanEnv = os.environ.copy()

    for key in ["VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"]:
        cleanEnv.pop(key, None)

    subprocess.run(f"uv {cmd}".split(" "), env=cleanEnv, check=True)


def uvRun(cmd, withs=[]):
    global curVersion

    withArgs = ""
    for pattern in withs:
        for path in findWhl(pattern):
            withArgs += f" --with {str(path)}"
    uv(f"run --python {curVersion} {withArgs} {cmd}".replace("  ", " ").strip())


@contextlib.contextmanager
def venv(pythonVersion):
    global curVersion
    uv(f"python install {pythonVersion}")
    # Force-remove stale .venv so old cached packages (e.g. an installed
    # py2native with --sourceDirectory) don't shadow the correct version.
    shutil.rmtree(".venv", ignore_errors=True)
    uv(f"venv --python {pythonVersion} --clear")
    oldVersion = curVersion
    try:
        curVersion = pythonVersion
        yield
    finally:
        curVersion = oldVersion


def findWhl(pattern="*.whl"):
    path = pathlib.Path(".")
    for found in path.glob(pattern):
        yield found


def scp(source, target, id=None):
    idString = ""

    if id:
        idString = f"-i {id} "

    for filePath in findWhl(source):
        subprocess.run(f'scp -o "StrictHostKeyChecking=no" {idString}{str(filePath)} {target}', shell=True, check=True)


def run(name, parameters):
    if sys.platform == "win32":
        name = f"{name}.exe"
    else:
        name = f"./bin/{name}"

    subprocess.run(f"{name} {parameters}".split(" "), check=True)

def pushConfig(prefix):
    system = platform.system()
    machine = platform.machine()
    configVars = sysconfig.get_config_vars()
    paths = sysconfig.get_paths()

    py_version = configVars["py_version"]
    py_version_short = configVars["py_version_short"]
    py_version_nodot = configVars["py_version_nodot"]

    netConfig = {"configVars": configVars, "paths": paths}
    #netConfig = json.dumps(netConfig)
    #netConfig = netConfig.replace(py_version_nodot, "{py_version_nodot}")
    #netConfig = netConfig.replace(py_version, "{py_version}")
    #netConfig = netConfig.replace(py_version_short, "{py_version_short}")
    #netConfig = json.loads(netConfig)

    fileName = f"{prefix}-sysconfig-{system}-{machine}-{configVars['py_version']}-{configVars.get('Py_GIL_DISABLED', 0)}.json"

    config = { "fileName": fileName,
               "prefix": prefix,
               "system": system,
               "machine": machine,
               "py_version": py_version,
               "py_version_short": py_version_short,
               "py_version_nodot": py_version_nodot,
               "configVars": netConfig["configVars"],
               "paths": netConfig["paths"]}

    requests.put(f"https://staging.py2native.dev/api/collect/{fileName}", json=config)


def main():
    parser = argparse.ArgumentParser(
        description="Py2Native Smoketest",
        epilog="(C) Copyright 2026 by RSJ Software GmbH Gemering. All rights reserved.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--pythonVersion", type=str, default="3.14", help="Python Version"
    )
    parser.add_argument("--upload", type=str, default=None, help="Upload")
    parser.add_argument("--id", type=str, default=None, help="Upload ID File")
    parser.add_argument("--pro", action="store_true", help="Pro Version (RSJ only)")
    parser.add_argument("--proOnly", action="store_true", help="Pro Version only (RSJ only)")
    parser.add_argument("--sysconfigUpload", type=str, default=None, help="Upload sysconfig")
    parser.add_argument("--verbose", action="store_true", help="Verbose")
    parser.add_argument("--version", type=str, help="Version")
    args = parser.parse_args()

    verbose = ""

    if args.verbose:
        verbose = "--verbose "

    if args.version:
        version = f"--version {args.version} "

    if args.sysconfigUpload:
        pushConfig(args.sysconfigUpload)

    if not args.proOnly:
        with chdir("py2native"):
            with venv(args.pythonVersion):
                uvRun(
                    f"py2native {verbose}build {version}--wheel dist --exe py2native --base src/py2native cli *.py"
                )
                uvRun(
                    f"py2native {verbose}build {version}--exe py2native --embed embed --base src/py2native cli *.py",
                    withs=["dist/py2native*.whl"],
                )

                with chdir("embed"):
                    run("py2native", f"{verbose}build {version}--base ../src/py2native cli *.py")

                uvRun(
                    f"py2native {verbose}build {version}--library --wheel ldist --base src/py2native cli *.py"
                )

                uvRun(
                    f"-m py2native {verbose}build {version}--wheel ldist1 --base src/py2native cli *.py",
                    withs=["ldist/py2native*.whl"],
                )

    proPath = pathlib.Path("./plugins/py2nativepro")
    if (args.pro or args.proOnly) and proPath.exists():
        with chdir("plugins/py2nativepro"):
            shutil.rmtree(pathlib.Path("dist"), ignore_errors=True)
            with venv(args.pythonVersion):
                uvRun(
                    f"py2native {verbose}build {version}--license ../../license.dat --public ../../public.pem --library --wheel dist --base src/py2nativepro main *.py",
                    withs=["../../py2native/dist/py2native*.whl"],
                )

        with chdir("py2nativetest"):
            with venv(args.pythonVersion):
                withs = [
                    "../py2native/dist/py2native*.whl",
                    "../plugins/py2nativepro/dist/py2nativepro*.whl",
                ]
                uvRun(
                    f"py2native {verbose}keygen --private privateTest.pem --public publicTest.pem",
                    withs=withs,
                )
                uvRun(
                    f"py2native {verbose}sign --private privateTest.pem licenseTest.json licenseTest.dat",
                    withs=withs,
                )
                uvRun(
                    f"py2native {verbose}show --public publicTest.pem licenseTest.dat",
                    withs=withs,
                )
                uvRun(
                    f"py2native {verbose}build {version}--license ../license.dat --exe py2nativetest --public publicTest.pem --wheel dist --embed embed --base src/py2nativetest main *.py",
                    withs=withs,
                )

            with chdir("embed"):
                run("py2nativetest", "--license ../licenseTest.dat")

    if args.upload:
        with chdir("py2native/dist"):
            scp("py2native*.whl", args.upload, id=args.id)

        if args.pro and proPath.exists():
            with chdir("plugins/py2nativepro/dist"):
                scp("py2nativepro*.whl", args.upload, id=args.id)

if __name__ == "__main__":
    main()