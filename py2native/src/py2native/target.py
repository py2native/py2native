import sys
import sysconfig
import platform

configTemplates = []


def addTarget(parser):
    parser.add_argument("--targetOs", type=str, default=None, choices=["Windows", "Linux", "MacOS"], help="Target OS")
    parser.add_argument("--targetProcessor", tyoe=str, default=None, choices=["x86_64", "aarch64"], help="Target Processor")
    parser.add_argument("--targetPython", type=str, default=None, help="Target Python Version")
    parser.add_argument("--targetMode", type=str, default=None, choices=["standard", "freeThreaded"], help="Target Mode")
    parser.add_argument("--targetLimited", action="store_true", default=None, help="Target Limited")

class Target:

    def __init__(self, os=None, processor=None, pythonVersion=None, pythonMode=None, library=False, limited=None):
        configVars = sysconfig.get_config_vars()

        if os is None:
            os = platform.system()
        self.os = os

        if processor is None:
            processor = platform.machine()
            if processor == "AND64":
                processor = "x86_64"

        self.processor = processor

        if pythonVersion is None:
            pythonVersion = configVars.get("py_version")

        self.pythonVersion = pythonVersion

        if pythonMode is None:
            if configVars.get("Py_GIL_DISABLED", 0) == 1:
                pythonMode = "freeThreaded"
            else:
                pythonMode = "standard"
        self.pythonMode = pythonMode

        self.library = library

        if limited is None:
            if library:
                limited = True
            else:
                limited = False

        self.limited = limited

    def get_config_vars(self):
        version = self.pythonVersion.split(".")

        ret = {}

        for configTemplate in configTemplates:
            if configTemplate.get("os") is not  None and configTemplate.get("os") != self.os:
                continue

            if configTemplate.get("processor") is not None and configTemplate.get("processor") != self.processor:
                continue

            if not self.pythonVersion.startswith(configTemplate.get("pythonVersion", "")):
                continue

            if configTemplate.get("pythonMode") is not None and configTemplate.get("pythonMode") != self.pythonMode:
                continue

            if configTemplate.get("limited") is not None and configTemplate.get("limited") != self.limited:
                continue

            ret[configTemplate.varName] = configTemplate.value



        ret = {
            "EXT_SUFFIX": "",
            "LIBPL": "",
            "LIBDIR": "",
            "LIBRARY": "",
            "SYSLIBS": "",
            "LINKFORSHARED": "",
            "installed_platbase": "",
            "py_version": self.pythonVersion
        }
        return ret

