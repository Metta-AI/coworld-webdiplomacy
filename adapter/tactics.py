"""Compatibility entrypoint for the tactics API-player scenario."""
import sys

from players.scenarios import main

if __name__ == '__main__':
    sys.argv[1:] = ['tactics']
    main()
