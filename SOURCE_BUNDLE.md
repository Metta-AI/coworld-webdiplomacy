# webDiplomacy Coworld source bundle

The image builds from this repository and its unmodified `webdiplomacy/`
submodule. Both are included in the optional AGPL source archive.

```sh
git submodule update --init --recursive
uv run python adapter/build_source_bundle.py dist/webdiplomacy-coworld-source.tar.gz
tar -tzf dist/webdiplomacy-coworld-source.tar.gz | head
```

Run from a clean, committed checkout. The script checks the submodule against
the committed Git submodule reference and refuses dirty checkouts. It archives tracked source at
`HEAD`, including both licenses, with fixed gzip timestamps. Repeated builds
from the same commits produce the same SHA-256. Record that hash with the image
digest when distributing a release. After extracting, build the game with:

```sh
docker build --platform linux/amd64 -f adapter/Dockerfile -t coworld-webdiplomacy:local .
```
