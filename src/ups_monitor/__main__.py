from __future__ import annotations

from .config import Settings
from .server import serve


def main() -> None:
    serve(Settings.from_environment())


if __name__ == "__main__":
    main()
