"""Discovery of third-party backends via package entry points.

A package registers a backend by declaring, in its ``pyproject.toml``:

```toml
[project.entry-points."safeagenteval.backends"]
mybank = "mybank.backend:MyBackend"
```

Registered backends can then be referenced by name (``--backend mybank``)
anywhere a ``package.module:ClassName`` spec is accepted.
"""

from __future__ import annotations

from importlib.metadata import entry_points


def registered_backends() -> dict[str, str]:
    """Return ``{name: 'package.module:ClassName'}`` for installed backend plugins."""
    try:
        group = entry_points(group="safeagenteval.backends")
    except TypeError:  # Python < 3.10 style API; supported floor is 3.11, defensive only
        return {}
    return {entry.name: entry.value for entry in group}


def resolve_backend_spec(spec: str) -> str:
    """Resolve a registered plugin name to its import spec; pass specs through."""
    if ":" in spec:
        return spec
    registered = registered_backends()
    if spec in registered:
        return registered[spec]
    return spec
