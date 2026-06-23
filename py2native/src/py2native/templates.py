headerTemplate = """
#include <string.h>

#include "Python.h"

{{for module in modules}}
extern PyObject* PyInit_{{module}}(void);
{{endfor}}

{{for package in packages}}
PyMODINIT_FUNC  PyInit_{{package}}(void);
{{endfor}}
"""

bootstrapTemplate = """
import sys
import importlib
import importlib.machinery
import logging
logging.basicConfig(level=logging.WARNING)
import pathlib
import types
import base64
import hashlib
import json
import time
import traceback

package = "{{package}}"
packages = {{packages}}
logger = logging.getLogger(f"bootstrap {{package}}")

cdef extern from "Python.h":
    ctypedef struct PyModuleDef:
        const char* m_name;

    void Py_INCREF(object)
    object PyModule_FromDefAndSpec(PyModuleDef *definition, object spec)
    int PyModule_ExecDef(object module, PyModuleDef* definition)

cdef extern from "{{package}}.h":
{{for module in modules}}
    object PyInit_{{module}}()
{{endfor}}

definitions = {
{{for module in modules}}
    "{{module}}": PyInit_{{module}},
{{endfor}}
    }

def debugMsg(*args):
    {{if debug}}
    print(*args)
    {{else}}
    pass
    {{endif}}

cdef class CythonPackageLoader:
    cdef object _init_func
    cdef PyModuleDef* definition
    cdef object def_o
    cdef str name

    def __init__(self, name):
        debugMsg("Create CythonPackageLoader", name)
        self._init_func = definitions[name]
        self.name = name

    def load_module(self, fullname):
        debugMsg(package, "load_module", fullname)
        if fullname in sys.modules:
            return sys.modules[fullname]
        # Build and exec the module old-style
        self.def_o = self._init_func()
        self.definition = <PyModuleDef*>self.def_o
        Py_INCREF(self.def_o)
        spec = importlib.machinery.ModuleSpec(fullname, self, is_package=(fullname in packages))
        module = PyModule_FromDefAndSpec(self.definition, spec)
        sys.modules[fullname] = module
        try:
            PyModule_ExecDef(module, self.definition)
            module.__file__ = f"{sys.executable}/{self.name}"
            if spec.submodule_search_locations is not None:
                package_path = module.__name__.replace(".", "/")
                module.__path__ = [f"{sys.executable}/{package_path}"]
        except Exception:
            del sys.modules[fullname]
            logger.exception("Exception")
            raise
        return module

    def create_module(self, spec):
        debugMsg(package, self.name, "create_module", spec)
        if package != "__main__":
            if spec.name.split(".")[-1] != self.name:
                raise ImportError()
        # Call the PyInit function here (not in __init__) so that
        # sys.modules[spec.name] is already set by the import machinery.
        self.def_o = self._init_func()
        self.definition = <PyModuleDef*>self.def_o
        Py_INCREF(self.def_o)
        # Wrap the spec so that spec.parent returns "" instead of None.
        # Cython's init code copies spec.parent to __package__, and None
        # would break relative imports.
        class _SpecWrapper:
            def __init__(self, wrapped):
                self._wrapped = wrapped
            @property
            def name(self):
                return self._wrapped.name
            @property
            def parent(self):
                return "py2native"
            def __getattr__(self, name):
                return getattr(self._wrapped, name)
        module = PyModule_FromDefAndSpec(self.definition, _SpecWrapper(spec))
        # The compiled module was part of the "py2native" package.
        # Set __package__ to "py2native" so relative imports like
        # "from .build import build" resolve as "py2native.build".
        # The finder handles dotted names and we pre-created the
        # "py2native" package in sys.modules.
        module.__package__ = "py2native"
        # Ensure the module is in sys.modules before exec_module runs,
        # so that imports of submodules (e.g. cli.shared) can find the parent.
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module):
        try:
            PyModule_ExecDef(module, self.definition)
            module.__file__ = f"{sys.executable}/{self.name}"
            spec = getattr(module, "__spec__", None)
            if spec is not None and spec.submodule_search_locations is not None:
                package_path = module.__name__.replace(".", "/")
                module.__path__ = [f"{sys.executable}/{package_path}"]
        except Exception:
            logger.exception("Exception")
            raise

class CythonPackageMetaPathFinder:
    def __init__(self, modules_set):
        self.modules_set = modules_set

    def find_spec(self, fullname, path, target=None):
        debugMsg(package, "find_spec", fullname, path)
        nameParts = fullname.split(".")

        if package == "__main__":
            # Only match top-level names OR names under the expected
            # package (e.g. "py2native.cli"). Do NOT match other
            # packages like "packaging.utils".
            if len(nameParts) == 1:
                namePart = nameParts[0]
            elif len(nameParts) == 2 and nameParts[0] == "py2native":
                namePart = nameParts[1]
            else:
                return None
            is_pkg = namePart in packages
        else:
            if len(nameParts) > 1:

                if nameParts[-2] != package:
                    return None
            namePart = nameParts[-1]
            is_pkg = len(nameParts) == 1 and namePart in packages

        if namePart not in self.modules_set:
            return None

        return importlib.machinery.ModuleSpec(fullname, CythonPackageLoader(namePart), is_package=is_pkg)

    def invalidate_caches(self):
        pass

cdef bootstrap_cython_submodules():
    debugMsg(package, "bootstrap_cython_submodules")
    modules_set = {{modules}}
    sys.meta_path.insert(0, CythonPackageMetaPathFinder(modules_set))
    #sys.meta_path.append(CythonPackageMetaPathFinder(modules_set))

cdef bootstrap_runtime_paths():
    exe_dir = pathlib.Path(sys.executable).resolve().parent
    roots = [exe_dir, exe_dir.parent]
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"

    extra_paths = []
    for root in roots:
        extra_paths.append(root / "lib" / py_ver / "lib-dynload")
        extra_paths.append(root / "lib" / py_ver / "site-packages")
        extra_paths.append(root / "Lib" / "site-packages")
        extra_paths.append(root / "DLLs")

    for path in extra_paths:
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)

{{code}}

cdef bootstrap_runtime_api():
    package_runtime_name = f"{{package}}.py2native_runtime"
    global_runtime = sys.modules.get("py2native_runtime")

    if package == "__main__":
        if global_runtime is None:
            runtime_module = types.ModuleType("py2native_runtime")
            sys.modules["py2native_runtime"] = runtime_module
            global_runtime = runtime_module
        else:
            runtime_module = global_runtime
    else:
        runtime_module = sys.modules.get(package_runtime_name)
        if runtime_module is None:
            runtime_module = types.ModuleType(package_runtime_name)
            sys.modules[package_runtime_name] = runtime_module
        if global_runtime is not None:
            # Inherit core runtime API for plugin/package runtime modules while
            # still keeping package-local runtime objects isolated.
            for _name, _value in global_runtime.__dict__.items():
                if _name not in runtime_module.__dict__:
                    runtime_module.__dict__[_name] = _value

    runtime_module.__api_version__ = "1"
    _features = dict(getattr(runtime_module, "__features__", {}))
    _features.update({{features}})
    runtime_module.__features__ = _features

    {{for k,v in (exports or {}).items()}}
    runtime_module.{{k}} = {{v}}
    {{endfor}}

    if package == "__main__":
        # Expose runtime API under package-qualified names so relative imports
        # like "from . import py2native_runtime" work inside compiled packages.
        for pkg in packages:
            sys.modules[f"{pkg}.py2native_runtime"] = runtime_module
    else:
        sys.modules[package_runtime_name] = runtime_module

bootstrap_cython_submodules()
bootstrap_runtime_paths()
bootstrap_runtime_api()

{{if mainModule}}
sys.frozen = True

# Remove the pre-created placeholder package so the custom finder
# can load the real compiled module.
if "{{mainModule}}" in sys.modules:
    del sys.modules["{{mainModule}}"]
# Also ensure the package namespace exists so that relative imports
# like "from .build import build" resolve correctly.
import types as _types
_pkg = _types.ModuleType("py2native")
_pkg.__path__ = []
_pkg.__package__ = "py2native"
sys.modules.setdefault("py2native", _pkg)

try:
    _main_mod = importlib.import_module("{{mainModule}}")
    _main_mod.main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
{{else}}
__path__ = [f"{sys.executable}/{{package}}"]
{{endif}}

"""
