"""app.py — alternatywny punkt wejścia: python app.py

Dla uruchomienia bez instalacji pakietu.
"""
import sys
from pathlib import Path

# Dodaj katalog projektu do sys.path gdy uruchamiany bezpośrednio
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui.app import PlexConvertApp


def main() -> None:
    app = PlexConvertApp()
    app.mainloop()


if __name__ == "__main__":
    main()
