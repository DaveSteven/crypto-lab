"""Local-only API process entry point."""

import os

import uvicorn

from crypto_lab.api import create_app


def main() -> None:
    # 8000 commonly collides with other local dev services; the default
    # development port is 8642 and stays bound to the loopback interface.
    port = int(os.getenv("CRYPTO_LAB_API_PORT", "8642"))
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
