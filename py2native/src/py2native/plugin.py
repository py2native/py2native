import importlib
import logging
import pathlib
import sys

logger = logging.getLogger(__name__)


class PluginManager:
    def __init__(self, plugins=None, module_names=None):
        self.plugins = list(plugins or [])

        for module_name in module_names:
            plugin = self._load_plugin_from_module(module_name)
            if plugin is not None:
                self.plugins.append(plugin)

    def _load_plugin_from_module(self, module_name):
        try:
            module = importlib.import_module(module_name, package=__package__)
        except Exception as e:
            # logger.debug("Failed to load plugin %s: %s", module_name, e)
            # Dogfood/self-hosting path: allow loading plugins from local
            # `src/<package>` when running from a project checkout without
            # installing that project first.
            if not module_name.startswith("."):
                src_path = pathlib.Path.cwd() / "src"
                src_path_str = str(src_path)
                if src_path.is_dir() and src_path_str not in sys.path:
                    sys.path.insert(0, src_path_str)
                    try:
                        module = importlib.import_module(
                            module_name, package=__package__
                        )
                    except Exception:
                        return None
                else:
                    return None
            else:
                return None

        plugin_cls = getattr(module, "Plugin", None)
        if plugin_cls is None:
            return None

        try:
            return plugin_cls(self)
        except Exception:
            return None

    def register(self, plugin):
        self.plugins.append(plugin)

    def dispatch(self, method_name, *args, **kwargs):
        results = None
        for plugin in self.plugins:
            method = getattr(plugin, method_name, None)
            if callable(method):
                result = method(*args, **kwargs)
                if results is None:
                    results = result
                elif isinstance(results, list):
                    results.append(result)
                else:
                    results |= result
        return results

    def __getattr__(self, method_name):
        def _dispatch(*args, **kwargs):
            return self.dispatch(method_name, *args, **kwargs)

        return _dispatch


pluginManager = PluginManager(
    module_names=["py2nativepro", ".winplatform", ".linuxplatform", ".macplatform"]
)
