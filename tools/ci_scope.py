"""Decide which CI jobs a change needs. Prints `images=` and `optimizer=` lines for $GITHUB_OUTPUT.

Usage: python3 -m tools.ci_scope [BASE_SHA]. Without a usable base, every job runs.
"""

import json
import subprocess
import sys

TEMPLATE = "coworld_manifest_template.json"
# What the images are built from, and what the Docker checks run.
IMAGE_PATHS = (
    "adapter/",
    "players/",
    "php/",
    "config/",
    "tools/",
    "webdiplomacy",
    ".gitmodules",
    "compose.yaml",
    ".dockerignore",
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/",
)
# Under tools/, but neither in an image nor used by a Docker check.
NOT_IMAGE_PATHS = ("tools/build_intro_slides.py", "tools/sync_manifest_docs.py")
# optimizer/install.sh copies the root changelog into the lab.
OPTIMIZER_PATHS = ("optimizer/", "CHANGELOG.md", "pyproject.toml", "uv.lock", ".github/workflows/")


def runtime_manifest(text):
    """The manifest template without the docs that `tools.sync_manifest_docs` embeds in it."""
    manifest = json.loads(text)
    del manifest["game"]["docs"], manifest["game"]["protocols"]
    return manifest


def scope(changed, base_template, head_template):
    """`changed` is the changed paths; the templates are file text, or None where the file is absent."""
    images = any(path.startswith(IMAGE_PATHS) and path not in NOT_IMAGE_PATHS for path in changed)
    if TEMPLATE in changed and not images:
        # Most template changes are a doc resync, which no Docker check reads.
        images = (
            base_template is None
            or head_template is None
            or runtime_manifest(base_template) != runtime_manifest(head_template)
        )
    return dict(images=images, optimizer=any(path.startswith(OPTIMIZER_PATHS) for path in changed))


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def main(base):
    merge_base = git("merge-base", base, "HEAD").stdout.strip() if base.strip("0") else ""
    if not merge_base:
        # A manual run, a first push or a rewritten branch: there is nothing to compare against.
        return dict(images=True, optimizer=True)
    changed = git("diff", "--name-only", merge_base, "HEAD").stdout.splitlines()
    templates = [git("show", f"{commit}:{TEMPLATE}") for commit in (merge_base, "HEAD")]
    return scope(changed, *(result.stdout if result.returncode == 0 else None for result in templates))


if __name__ == "__main__":
    for job, needed in main(sys.argv[1] if len(sys.argv) > 1 else "").items():
        print(f"{job}={str(needed).lower()}")
