from __future__ import annotations

from .config import Settings
from .youtube import create_authorization


def main() -> None:
    settings = Settings()
    result = create_authorization(
        settings.youtube_client_secret, settings.youtube_token
    )
    print(result, flush=True)


if __name__ == "__main__":
    main()
