"""app.py - punkt wejscia: python app.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pyconv.gui.app import PlexConvertApp


def main() -> None:
    app = PlexConvertApp()
    app.mainloop()


if __name__ == "__main__":
    main()
