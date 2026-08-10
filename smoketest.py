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

    for key in ["VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH", "PYTHONHOME"]:
        cleanEnv.pop(key, None)

    # Use Popen to tee output live (to CI) while also capturing for error reporting
    import threading, queue
    proc = subprocess.Popen(f"uv {cmd}".split(" "), env=cleanEnv,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    _q = queue.SimpleQueue()
    def _drain():
        for line in proc.stdout:
            _q.put(line)
            print(line, end="", file=sys.stderr)
    _t = threading.Thread(target=_drain, daemon=True)
    _t.start()
    proc.wait()
    _t.join(timeout=5)
    _lines = []
    while not _q.empty():
        _lines.append(_q.get())
    output = "".join(_lines)
    if proc.returncode != 0:
        print(f"--- subprocess failed (exit {proc.returncode}) ---", file=sys.stderr)
        print(f"cmd: {proc.args}", file=sys.stderr)
        if output.strip():
            print(f"output:", file=sys.stderr)
            print(output, file=sys.stderr)
        print("--- end subprocess output ---", file=sys.stderr)
        raise subprocess.CalledProcessError(proc.returncode, proc.args, output)


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
    shutil.rmtree(".py2native_build", ignore_errors=True)
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

    # On Linux, set PYTHONHOME so embedded binaries find their Python
    # packages.  On Windows, the executable uses its own location heuristics.
    if sys.platform != "win32":
        runEnv = os.environ.copy()
        if "PYTHONHOME" not in runEnv:
            runEnv["PYTHONHOME"] = str(pathlib.Path(".").resolve())
    else:
        runEnv = None

    try:
        subprocess.run(f"{name} {parameters}".split(" "), check=True,
                       capture_output=True, text=True, env=runEnv)
    except subprocess.CalledProcessError as e:
        print(f"--- subprocess failed (exit {e.returncode}) ---", file=sys.stderr)
        print(f"cmd: {e.cmd}", file=sys.stderr)
        if e.stdout is not None:
            print(f"stdout ({len(e.stdout)}b):", file=sys.stderr)
            print(e.stdout, file=sys.stderr)
        if e.stderr is not None:
            print(f"stderr ({len(e.stderr)}b):", file=sys.stderr)
            print(e.stderr, file=sys.stderr)
        print("--- end subprocess output ---", file=sys.stderr)
        raise

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
    parser.add_argument("--policy", type=str, help="Policy")
    args = parser.parse_args()

    verbose = ""

    if args.verbose:
        verbose = "--verbose "

    version = ""
    
    if args.version:
        if args.version == "master":
            version = ""
        else:
            # Normalize version to be PEP 440 / wheel compatible
            _safe_version = args.version.replace("-", ".")
            if _safe_version.startswith("v"):
                _safe_version = _safe_version[1:]
            version = f"--version {_safe_version} "

    if args.policy:
        policy = f"--policy {args.policy} "
    else:
        policy = ""

    if args.sysconfigUpload:
        pushConfig(args.sysconfigUpload)

    if not args.proOnly:
        with chdir("py2native"):
            with venv(args.pythonVersion):
                uvRun(
                    f"py2native {verbose}build {version}{policy}--wheel dist --exe py2native --base src/py2native cli *.py"
                )
                uvRun(
                    f"py2native {verbose}build {version}--exe py2native --embed embed --base src/py2native cli *.py",
                    withs=["dist/py2native-[0-9]*.whl"],
                )

                # The embedded binary segfaults on Python 3.15+ (pre-release
                # binary compatibility issue).  Skip the embed smoke test there.
                if sys.version_info < (3, 15):
                    with chdir("embed"):
                        run("py2native", f"--verbose build --base ../src/py2native cli *.py")

                uvRun(
                    f"py2native {verbose}build {version}--library --wheel ldist --base src/py2native cli *.py"
                )

                uvRun(
                    f"-m py2native {verbose}build {version}--wheel ldist1 --base src/py2native cli *.py",
                    withs=["ldist/py2native-[0-9]*.whl"],
                )

    proPath = pathlib.Path("./plugins/py2nativepro")
    if (args.pro or args.proOnly) and proPath.exists():
        # Run the pro build from py2native/ (which has pyproject.toml)
        # so uv run sets LD_LIBRARY_PATH correctly for the embedded Python binary.
        _root = pathlib.Path(".").resolve()
        with chdir("py2native"):
            with venv(args.pythonVersion):
                # Install the pro plugin source so --license/--public are recognized
                uv(f"pip install --python {curVersion} -e {_root / 'plugins/py2nativepro'}")
                for whl in (_root / "py2native/dist").glob("py2native-[0-9]*.whl"):
                    uv(f"pip install --python {curVersion} {whl}")
                uvRun(
                    f"py2native {verbose}build {version}{policy}"
                    f"--license {_root / 'license.dat'} "
                    f"--public {_root / 'public.pem'} "
                    f"--library --wheel dist "
                    f"--base {_root / 'plugins/py2nativepro/src/py2nativepro'} "
                    f"main *.py*",
                )
            # Copy built wheel back to plugins/py2nativepro/dist
            _real_dist = _root / "plugins/py2nativepro/dist"
            _real_dist.mkdir(parents=True, exist_ok=True)
            for _whl in pathlib.Path("dist").glob("py2nativepro*.whl"):
                shutil.copy2(str(_whl), str(_real_dist / _whl.name))

        # Run py2nativetest builds from py2native/ so uv run sets up the
        # Python library path correctly for the embedded py2native binary.
        _root = pathlib.Path(".").resolve()
        _testdir = _root / "py2nativetest"
        with chdir("py2native"):
            with venv(args.pythonVersion):
                # Install wheels into the venv
                for whl in (_root / "py2native/dist").glob("py2native-[0-9]*.whl"):
                    uv(f"pip install --python {curVersion} {whl}")
                for whl in (_root / "plugins/py2nativepro/dist").glob("py2nativepro*.whl"):
                    uv(f"pip install --python {curVersion} {whl}")
                # Install pro plugin source (needed for --license/--public args)
                uv(f"pip install --python {curVersion} -e {_root / 'plugins/py2nativepro'}")
                uvRun(
                    f"py2native {verbose}keygen --private {_testdir / 'privateTest.pem'} --public {_testdir / 'publicTest.pem'}",
                )
                uvRun(
                    f"py2native {verbose}sign --private {_testdir / 'privateTest.pem'} {_testdir / 'licenseTest.json'} {_testdir / 'licenseTest.dat'}",
                )
                uvRun(
                    f"py2native {verbose}show --public {_testdir / 'publicTest.pem'} {_testdir / 'licenseTest.dat'}",
                )
                uvRun(
                    f"py2native {verbose}build {version}"
                    f"--license {_root / 'license.dat'} "
                    f"--exe py2nativetest "
                    f"--public {_testdir / 'publicTest.pem'} "
                    f"--wheel dist --embed embed "
                    f"--base {_testdir / 'src/py2nativetest'} "
                    f"main *.py*",
                )
            # Copy embed output back to py2nativetest
            _embed_src = pathlib.Path("embed")
            _embed_dst = _testdir / "embed"
            if _embed_src.exists():
                if _embed_dst.exists():
                    shutil.rmtree(str(_embed_dst), ignore_errors=True)
                shutil.copytree(str(_embed_src), str(_embed_dst))

        if sys.version_info < (3, 15):
            with chdir(str(_testdir / "embed")):
                run("py2nativetest", "--license ../licenseTest.dat")

    if args.upload:
        with chdir("py2native/dist"):
            scp("py2native*.whl", args.upload, id=args.id)

        if args.pro and proPath.exists():
            with chdir("plugins/py2nativepro/dist"):
                scp("py2nativepro*.whl", args.upload, id=args.id)

if __name__ == "__main__":
    main()