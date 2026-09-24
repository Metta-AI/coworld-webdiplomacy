# webDiplomacy Coworld source bundle

The game image builds from this adapter and the unmodified webDiplomacy revision in `UPSTREAM_COMMIT`. The bundle is an internal review artifact. Legal review determines the public source-offer text and distribution terms.

```sh
git clone https://github.com/kestasjk/webDiplomacy.git upstream
git -C upstream checkout "$(cat UPSTREAM_COMMIT)"
python3 adapter/build_source_bundle.py dist/webdiplomacy-coworld-source.tar.gz --upstream upstream
tar -tzf dist/webdiplomacy-coworld-source.tar.gz | head
```

The archive has `webdiplomacy-coworld/` with this repository's tracked source at `HEAD` and its pinned `upstream/` checkout. It includes both license texts, build files, configuration schema, and player examples. The script refuses dirty source checkouts or a different upstream revision. The gzip header has a fixed timestamp, so repeated builds from the same commits have the same SHA-256. Record that SHA-256 and the game image digest together when preparing a release. After extracting, run `docker compose build` from `webdiplomacy-coworld/`.
