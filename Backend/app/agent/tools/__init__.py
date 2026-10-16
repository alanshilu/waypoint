from importlib import import_module


_MODULE_NAMES = [
    "geocode_location",
    "create_trip",
    "generate_route",
    "select_route",
    "search_pois",
    "get_weather",
]


def __getattr__(name):
    if name not in {"TOOL_SCHEMAS", "TOOL_FUNCTIONS"}:
        raise AttributeError(name)

    modules = [import_module(f"{__name__}.{module_name}") for module_name in _MODULE_NAMES]
    if name == "TOOL_SCHEMAS":
        return [module.TOOL_SCHEMA for module in modules]

    return {
        module.TOOL_SCHEMA["name"]: getattr(module, module.TOOL_SCHEMA["name"])
        for module in modules
    }
