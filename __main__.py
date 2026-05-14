"""Punkt wejścia: python -m pyconv"""
from pyconv.gui.app import PlexConvertApp


def main() -> None:
    app = PlexConvertApp()
    app.mainloop()


if __name__ == "__main__":
    main()
