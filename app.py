"""app.py — alternatywny punkt wejścia: python app.py

Dodaje katalog projektu do sys.path ORAZ tworzy alias pakietu 'pyconv'
żeby relative imports w gui/ działały zarówno przy:
  python app.py          (bez instalacji)
  python -m pyconv       (po instalacji)
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _bootstrap_package(pkg_name: str, root: Path) -> None:
    """Rejestruje root jako pakiet pkg_name w sys.modules jeśli go jeszcze nie ma."""
    if pkg_name in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        pkg_name,
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    if spec is None:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(root)]  # type: ignore[assignment]
        pkg.__package__ = pkg_name
        pkg.__spec__ = None  # type: ignore[assignment]
        sys.modules[pkg_name] = pkg
        return
    pkg = importlib.util.module_from_spec(spec)
    pkg.__path__ = [str(root)]  # type: ignore[assignment]
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg
    with contextlib.suppress(Exception):
        spec.loader.exec_module(pkg)  # type: ignore[union-attr]


_bootstrap_package("pyconv", ROOT)

from gui.app import PlexConvertApp  # noqa: E402


def main() -> None:
    app = PlexConvertApp()
    app.mainloop()


if __name__ == "__main__":
    main()
