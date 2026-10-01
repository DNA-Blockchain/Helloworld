# Making a release

Users install and update from **tagged releases**, never from master. Day-to-day work merges into
master freely, and nothing reaches users until a release is tagged. People testing the newest code can
install master with `RABBIT_CHANNEL=dev`.

## Checklist

1. **Everything for this release is merged**, and master's `verify` check is green on GitHub.
2. **Pick the version.** Bump MAJOR if an API in `schemas/` changed in a way that breaks older parts, MINOR for new features, PATCH for fixes only.
3. **On a branch `release-X.Y.Z`:**
   - Put `X.Y.Z` in `VERSION`.
   - In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, and add a fresh empty `## [Unreleased]` above it.
   - Run `python -m pytest`. Everything must pass, including the schema contract tests once they exist.
4. **Open the PR "Release X.Y.Z"** and merge it once `verify` passes.
5. **Tag the merge commit:**
   ```sh
   git switch master && git pull
   git tag -a vX.Y.Z -m "RabbitSoftware X.Y.Z"
   git push origin vX.Y.Z
   ```
6. **The `release` workflow takes over** (`.github/workflows/release.yml`):
   - It checks that the tag matches `VERSION`.
   - It runs the tests.
   - It publishes a GitHub release whose notes are the changelog section for that version.
   - It attaches the **code manifest** (`rabbitsoftware-X.Y.Z-code-manifest.json`): the author, the license, the commit and the SHA-256 of every file, plus one fingerprint over all of them (`scripts/code_fingerprint.py`).
7a. **Record the release's authorship on the chain:** `python rabbit.py publish-code-fingerprint vX.Y.Z`. It shows the fingerprint and asks before publishing a `code_release` entry.
7. **Check the release page.** Then install it once from scratch with each installer:
   - Windows: `irm https://raw.githubusercontent.com/DNA-Blockchain/Helloworld/master/install.ps1 | iex`
   - Linux/WSL: `curl -fsSL https://raw.githubusercontent.com/DNA-Blockchain/Helloworld/master/install.sh | bash`

   Both should report "release vX.Y.Z".
8. **Existing installs** pick up the release with `rabbit update`. It asks first.

## If a release is broken

Fix it on master and release a PATCH version. Don't move or delete a published tag: installs and `rabbit
update` compare against it.
