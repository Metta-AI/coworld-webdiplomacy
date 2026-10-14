# Classic map assets for The board

Copied from the pinned `webdiplomacy/` submodule (kestasjk/webdiplomacy at `bafb2f80`). webDiplomacy is
AGPL-3.0; see `webdiplomacy/LICENSE` and `webdiplomacy/AGPL.txt` in this repository. The files are
unmodified copies, served locally; there are no runtime CDN requests.

| File | Source | SHA-256 |
|---|---|---|
| classic-key.png | `webdiplomacy/variants/Classic/resources/map.png` (large map: one flat colour per province) | da49ed65a7f952122e6a81bf54b88427c83822ac08fd0ac030d8becec2f5e29b |
| classic-names.png | `webdiplomacy/variants/Classic/resources/mapNames.png` (province names on white) | 754b07328a8455df28ebdb4e60c81b2f88065101f2668497396729302962026f |
| classic-points.json | A point inside each territory: `largeMapX`, `largeMapY` from `webdiplomacy/variants/Classic/install.php` (`InstallTerritory`). Copied from the optimizer IDE's `map-classic.json` (player_ade_webdip, 2026-10-13), checked against install.php. | 3b7444a3794e855cbd0bae83513cb06ebf743eedef3574ed6ec33040e4be55a6 |

`static/board-map.js` flood-fills each province from its point in the key image (as the optimizer IDE's
Map tab does) and paints the provinces itself; the names image is multiplied over the result.
