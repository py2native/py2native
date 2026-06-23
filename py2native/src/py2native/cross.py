import pathlib
import os
from contextlib import chdir
import zipfile
import tarfile
import logging

logger = logging.getLogger(__name__)

import requests

class CrossCompiler:
    def __init__(self):
        self.macros = {}
        self.includeDirs = ["/opt/python-win/include"]
        self.libDirs = ["/opt/python-win/embed"]
        self.compiler = "x86_64-w64-mingw32-clang"

    @classmethod
    def newCompiler(cls):
        return CrossCompiler()

    def define_macro(self, name, value):
        self.macros[name] = value

    def add_include_dir(self, newDir):
        self.includeDirs.append(newDir)

    def add_library_dir(self, newDir):
        self.libDirs.append(newDir)

    def compile(self, sources):

        cmd = f'{self.compiler} -c'

        for source in sources:
            cmd += f" {source}"

        for key, value in self.macros.items():
            cmd  += f" -D{key}={value}"

        for includeDir in self.includeDirs:
            cmd +=f" -I{includeDir}"

        os.system(cmd)

        ret = []
        for source in sources:
            sourcePath = pathlib.Path(source)
            objectPath = sourcePath.with_suffix(".o")
            ret.append(str(objectPath))
        return ret

    def link_executable(self, objects, outputName, output_dir="."):

        cmd = self.compiler

        for object in objects:
            cmd += f" {object}"

        output = pathlib.Path(output_dir) / outputName
        output = output.with_suffix(".exe")
        cmd += f" -o {str(output)}"

        for libDir in self.libDirs:
            cmd += f" -L{libDir}"

        cmd += " -l python312"

        cmd += " -municode"

        os.system(cmd)

    def link_shared_object(self, objects, outputName, output_dir="."):
        cmd = self.compiler

        for object in objects:
            cmd += f" {object}"

        output = pathlib.Path(output_dir) / outputName
        output = output.with_suffix(".pyd")
        cmd += f" -o {str(output)}"

        for libDir in self.libDirs:
            cmd += f" -L{libDir}"

        cmd += " -l python312"

        cmd += " -shared"
        os.system(cmd)

    def prepare_python(self, version, target):
        targetPath = pathlib.Path(target)
        targetPath.mkdir(parents=True, exist_ok=True)
        with chdir(targetPath):
            fileName = f"python-{version}-embed-amd64.zip"
            url = f"https://www.python.org/ftp/python/{version}/{fileName}"
            self.downloadFile(fileName, url)
            self.unpackZip("embed", fileName)

            fileName = f"Python-{version}.tar.xz"
            url = f"https://www.python.org/ftp/python/{version}/{fileName}"
            self.downloadFile(fileName, url)
            self.unpackXz("Python-{version}", fileName)
            includeDir = pathlib.Path(f"Python-{version}/Include")
            targetPath = "./include"
            includeDir.move(targetPath)

    def download(self, target):
        downloadFile = self.downloadFile("llvm.zip", "https://github.com/mstorsjo/llvm-mingw/releases/download/20260602/llvm-mingw-20260602-ucrt-i686.zip")
        self.unpackZip(target, downloadFile)

    def downloadFile(self, target, url):
        with  requests.get(url, stream=True) as req:

            with open(target, "wb") as targetFile:
                for chunk in req.iter_content(chunk_size=1024*1024):
                    targetFile.write(chunk)

        return target

    def unpackZip(self, targetDir, fileName):
        with zipfile.ZipFile(fileName, "rb") as zipFile:
            zipFile.extractall(targetDir)

    def unpackXz(selfself, targetDir, fileName):
        with tarfile.open(fileName, "r:xz") as tar:
            tar.extractall(targetDir)
