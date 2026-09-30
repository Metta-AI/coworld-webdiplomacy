"""Compatibility entrypoint for the smoke API-player scenario."""
import sys

from players.scenarios import main

if __name__ == '__main__':
    sys.argv[1:] = ['smoke']
    main()
