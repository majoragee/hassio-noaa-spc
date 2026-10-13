#!/usr/bin/env bash
# Cut a release: bump the version, tag it, push to both remotes, and publish
# a GitHub release for HACS.
#
# Usage: scripts/release.sh X.Y.Z
set -euo pipefail

VERSION="${1:-}"
TAG="v${VERSION}"
GITHUB_REPO="majoragee/hassio-noaa-spc"

die() { echo "release: $*" >&2; exit 1; }

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "usage: $0 X.Y.Z"
cd "$(git rev-parse --show-toplevel)"
[[ "$(git branch --show-current)" == "main" ]] || die "must be on main"
[[ -z "$(git status --porcelain)" ]] || die "working tree is not clean"
git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null && die "tag ${TAG} already exists"
git remote get-url github >/dev/null 2>&1 || die "no 'github' remote"

sed -i -E "s/(\"version\": \")[^\"]+(\")/\1${VERSION}\2/" custom_components/noaa_spc/manifest.json
sed -i -E "s/^version = \"[^\"]+\"/version = \"${VERSION}\"/" pyproject.toml
sed -i -E "s#hassio-noaa-spc/[0-9]+\.[0-9]+\.[0-9]+ #hassio-noaa-spc/${VERSION} #" \
  custom_components/noaa_spc/api/products.py

.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q

if [[ -n "$(git status --porcelain)" ]]; then
  git commit -am "Release ${TAG}"
fi
git tag -a "${TAG}" -m "Release ${TAG}"

git push origin main "${TAG}"
git push github main "${TAG}"
gh release create "${TAG}" --repo "${GITHUB_REPO}" --title "${TAG}" --generate-notes --verify-tag

echo "Released ${TAG}"
