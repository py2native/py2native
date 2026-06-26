# Py2Native

More information on [https://py2native.dev](https://py2native.dev)

## Installation
````
uv add --dev Py2Native
````
Installs Py2Native in the current project

## Usage
````
uv run py2native build [--embed <targetDir>] <mainModule> [<module>...]
````
Compiles and links the given modules.

### Environment on Windows 
* P2N_MINGW32 path to unpacked [https://github.com/mstorsjo/llvm-mingw/releases/download/20260602/llvm-mingw-20260602-ucrt-i686.zip](https://github.com/mstorsjo/llvm-mingw/releases/download/20260602/llvm-mingw-20260602-ucrt-i686.zip)

## Restrictions
* No modules with identical names

## Requirements
* C-Python 3.10, 3.11, 3.12, 3.13, , 3.14, 3.14 freethreaded, 3.15, 3.15 freethreaded
* Python supported C Compiler / Linker for your platform
* * Visual Studio or llvm-mingw32  on Windows 
* Windows 8, Windows 10, Windows 11, ManyLinux 2014 or ManiMusl compatible Linux, or MacOS
* X64 CPU or ARM64 CPU
* Internet Access for downloading the used libraries and Python Distributions

## What we do
* Compile your software with Cython to .c and than into the native executables
* Link the object files together into a single executable (that can be a main executablemor a shared library)
* Support importing from within that single executable
* Embed some of the libraries with your executable
* Provide an embedded installation

## Protection
You no longer distribute your source code. 100% of **your** code is compiled to c and then to native executable format so recovering it is pretty difficult.
Reverse engineering is, while still possible, not easy.

Monkey patching is still possible (because big parts of the used libraries are still available in Python source.

### Legal Considerations
* All libraries remain as they are. So copyright messages remain in distribution. 
* LGPL restrictions are still met. The user can replace the library with a different version.

## Deployment Recipes

### Windows
You will usually need an installer to distribute the created embed directory. This directory holds all the used libraries and might contain thousands of files. 
It is recommended to use a tool like NSIS or Inno Setup to create an installer. 

#### InnoSetup
````
[Setup]
AppId="Test Application"
AppName="Test Application"
AppVerName=Test Application
AppPublisher=RSJ Software GmbH
AppPublisherURL=https://www.rsj.de
AppSupportURL=https://www.rsj.de
AppUpdatesURL=https://www.rsj.de
DefaultDirName={commonpf}\TestApplication
DefaultGroupName=Test Application
OutputBaseFilename={#outputName}
Compression=lzma
SolidCompression=yes
InternalCompressLevel=ultra
VersionInfoCompany=RSJ Software GmbH
VersionInfoCopyright=Copyright (C) 2026 by RSJ Software GmbH Germering. All rights reserved.
VersionInfoDescription=Test Application
VersionInfoProductName="Test Application"
VersionInfoVersion={#version}
VersionInfoProductVersion={#version}
VersionInfoTextVersion={#version}
VersionInfoProductTextVersion={#version}
ShowLanguageDialog=no
WizardImageStretch=no
MinVersion=10.0.10240
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: ..\embed\*; DestDir: {app}; Excludes: config.json; Flags: ignoreversion overwritereadonly uninsrestartdelete recursesubdirs setntfscompression;

[Dirs]
Name: {app}/data; Permissions: everyone-full;

[Run]
Filename: "{app}\testApplication.exe"; Flags: postinstall

[Icons]
Name: "{group}\TestApplication"; Filename: "{app}\testApplication.exe"
````
### Linux
You could either do:
* distribute a .zip file with the embed directory
* distribute a .tar.gz file with the embed directory
* create a docker image

### Docker
We recommend multistage docker builds.

#### Ubuntu
We recommend using the official Python image as base image.

````
FROM python:3.14-slim as pyBuilder

RUN apt-get update
RUN apt-get install -y git build-essential zlib1g-dev

RUN ln -s /usr/local/lib/libpython3.14.so /usr/lib/libpython3.14.so && \
    mkdir -p /usr/lib/python3.14/config-3.14-x86_64-linux-gnu && \
    ln -s /usr/local/lib/libpython3.14.so /usr/lib/python3.14/config-3.14-x86_64-linux-gnu/libpython3.14-pic.a

RUN python -m pip install uv

WORKDIR /builder

COPY . .

ENV PYTHONUNBUFFERED = 1

RUN uv run py2native build --embed ./embed main.py *.py

FROM python:3.14-slim AS runtime

RUN apt-get install openssl

WORKDIR /app
COPY --from=pyBuilder /builder/embed .

CMD ["./bin/main"]
````

#### Alpine
We recommend using the official Python image as base image.

````
FROM python:3.14-alpine as pyBuilder
WORKDIR /builder

RUN apk update && \
    UN apk add uv build-base git zlib-dev

RUN ln -s /usr/local/lib/libpython3.14.so /usr/lib/libpython3.14.so && \
    mkdir -p /usr/lib/python3.14/config-3.14-x86_64-linux-gnu && \
    ln -s /usr/local/lib/libpython3.14.so /usr/lib/python3.14/config-3.14-x86_64-linux-gnu/libpython3.14-pic.a

ENV PYTHONUNBUFFERED = 1    
RUN uv run py2native build --embed ./embed main.py *.py

FROM python:3.14-alpine 
WORKDIR /app
COPY --from=pyBuilder /builder/embed .
CMD ["./bin/main"]
````

# Pro Edition
## Features
* JWT based license management: JWT decoder with elliptic curve signature verification 
* String compression: Many strings are no longer easily accessible with a simple hex editolr

### License Management
py2native includes a specially protected license management:
* You create an elliptic curve keypair (P256)
````
uv run py2native keygen private.pem public.pem
````
* You build your executable with your public key.
````
uv run py2native build --embed ./embed --public-key public.pem main.py *.py
 ````
* You create license file (a text file with a JWT structure))
````
uv run py2native sign private.pem template.json license.dat
````
* You can verify the license in your software
````
from py2native_runtime import verify_license

license = verify_license("token", expected_issuer="xxxx", expected_autionece="My program")
````
* Your code can verify the license end adapt is operation accordingly

## Notes:
* Only the public key is stored in the executable
* The elliptic key verification is handled with compiled code in our software
  (ie no 3rd party libraries)

## License
The Pro Edition requires a special license. You receive a license file from us that you can either 
* specify on the command line (--license)
* in the environment (PY2NATIVE_LICENSE) 
  * NB: You store the content of the license file in the environment, not the path 
to the file. This is especially useful for Docker or for CI/CD pipelines (eg Github Actions).
* store in your home directory (~/.py2native/license.dat)

You need the license just for the build process.

