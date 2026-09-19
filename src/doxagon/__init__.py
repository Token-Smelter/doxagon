"""Doxagon package.

The package root intentionally avoids loading checkout-derived configuration so
explicit vault services stay isolated. Legacy root exports remain lazy for
callers that explicitly request them.
"""


def __getattr__(name: str):
    if name in {"load_graph", "build_graph", "save_logos", "compute_hash", "invalidate_cache"}:
        from doxagon import graph

        return getattr(graph, name)
    if name == "load_schema":
        from doxagon.schema import load_schema

        return load_schema
    if name in {"ROOT_DIR", "LIBRARY_DIR"}:
        from doxagon import config

        return getattr(config, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
