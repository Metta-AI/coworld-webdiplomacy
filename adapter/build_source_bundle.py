"""Bundle the exact adapter revision and pinned upstream source for internal review."""

import argparse
import gzip
import io
import subprocess
import tarfile
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
parser.add_argument("--upstream", type=Path, default=Path("upstream"))
args = parser.parse_args()

root = Path(__file__).resolve().parent.parent
pin = (root / "UPSTREAM_COMMIT").read_text().strip()
upstream_head = subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True).strip()
assert upstream_head == pin, f"upstream checkout is {upstream_head}, expected {pin}"
assert not subprocess.check_output(["git", "-C", str(args.upstream), "status", "--porcelain"])
assert not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"])

args.output.parent.mkdir(parents=True, exist_ok=True)
with args.output.open("wb") as output, gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed, tarfile.open(
    fileobj=compressed, mode="w"
) as bundle:
    for label, repository, revision in (
        ("webdiplomacy-coworld", root, "HEAD"),
        ("webdiplomacy-coworld/upstream", args.upstream, pin),
    ):
        archive = subprocess.check_output(["git", "-C", str(repository), "archive", "--format=tar", revision])
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
            for member in source:
                member.name = f"{label}/{member.name}"
                bundle.addfile(member, source.extractfile(member) if member.isfile() else None)
print(args.output)
