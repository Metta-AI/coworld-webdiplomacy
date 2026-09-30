"""Hold units and mark Ready through the same API available to any bot."""

import os
import time
from urllib.error import HTTPError, URLError

from players.api import WebDiplomacy, holds


def main():
    api = WebDiplomacy(
        os.environ["WEBDIP_URL"],
        os.environ["WEBDIP_API_KEY"],
        os.environ["WEBDIP_GAME_ID"],
        os.environ["WEBDIP_COUNTRY_ID"],
    )
    previous = None
    while True:
        try:
            context = api.context()
            game = context["game"]
            phase = (int(game["turn"]), game["phase"])
            if game["phase"] == "Finished":
                return
            if game["phase"] != "Pre-game" and phase != previous:
                api.orders(context, holds(context))
                previous = phase
        except HTTPError as error:
            if error.code not in (400, 404):
                raise
            # A phase can change between reading its context and saving Ready.
        except (URLError, TimeoutError):
            pass
        time.sleep(0.2)


if __name__ == "__main__":
    main()
