"""Small, local-first tool catalog for Jev.

Tools are opt-in. Filesystem and shell access are constrained to a caller supplied
workspace root; network and UI tools are descriptions only until an adapter exists.
"""

from .catalog import (
    ToolCatalog,
    ToolSpec,
    build_local_catalog,
    catalog_as_choice_options,
    catalog_as_tool_definitions,
)

__all__ = [
    "ToolCatalog",
    "ToolSpec",
    "build_local_catalog",
    "catalog_as_choice_options",
    "catalog_as_tool_definitions",
]
