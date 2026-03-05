from __future__ import annotations

import asyncio
import logging

from .config import parse_args
from .service import run_service


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    config = parse_args()
    asyncio.run(run_service(config))


if __name__ == "__main__":
    main()

