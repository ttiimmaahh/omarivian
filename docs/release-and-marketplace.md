# OmaRivian release and marketplace runbook

Last verified: 2026-08-26

This document separates confirmed requirements from project recommendations. Marketplace and GitHub behavior can change; recheck the linked primary sources immediately before publishing.

## Current release state

- Public repository: <https://github.com/ttiimmaahh/omarivian>
- Default branch: `main`
- Telemetry and UI baseline: [`2518fa6390f1c27fa00bff947dec3a9740471a21`](https://github.com/ttiimmaahh/omarivian/commit/2518fa6390f1c27fa00bff947dec3a9740471a21)
- `manifest.json` version: `0.1.0`
- `pyproject.toml` version: `0.1.0`
- Existing tags/releases: none
- License: MIT
- Marketplace plugin ID: `io.github.ttiimmaahh.omarivian`

The official marketplace validator was dry-run against the pushed repository at the commit above and passed:

```text
Repository is public and reachable
Found 1 valid, uniquely identified plugin manifest
Root README and license files detected
Quattro compatibility passed at commit 2518fa6
No supported root preview detected
```

The official Automated Security Baseline was then run against the exact same commit. It returned:

```text
outcome: passed
findings: []
capabilities: []
blocksApproval: false
verifiedPublicationDisposition: clear
```

These are point-in-time local dry runs of the marketplace's current public scripts, not marketplace approval or a security audit.

## What GitHub releases mean for this plugin

GitHub releases are based on Git tags. GitHub can create the tag during release creation and automatically provides source ZIP and tarball downloads. Custom binary assets are optional. [GitHub: About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases) [GitHub: Managing releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)

Omarchy does **not** install from GitHub release assets. It clones the repository and updates from mutable upstream `HEAD`; the marketplace explicitly warns that standard installation is not bound to the verified snapshot. A GitHub release is useful for human-readable version history, but it does not pin normal Omarchy installs. [Official Omarchy shell plugin lifecycle](https://github.com/basecamp/omarchy/blob/quattro/shell/README.md) [Marketplace verification boundary](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/VERIFICATION.md#installation-boundary)

Neither GitHub nor the marketplace requires a `v` prefix. **Project recommendation:** establish `v<manifest-version>` as the repository convention, starting with `v0.1.0`.

## First release recommendation

Publish `v0.1.0` as the project's first standard GitHub release. The `0.x` version and README both identify it as early-development software, while the release notes preserve the unsupported private-API and R1-validation limitations.

The repository's tag-driven release workflow reruns every hosted validation job, verifies that the tag matches both version declarations, requires matching release notes, and creates the GitHub release only after those checks pass.

After the final release commit is pushed and its branch CI succeeds:

```sh
git tag -a v0.1.0 -m "OmaRivian v0.1.0"
git push origin v0.1.0
```

The tag push triggers `.github/workflows/release.yml`; do not create the release manually in parallel.

No wheel, Python sdist, QML bundle, or custom source archive is required. GitHub's generated source archives are sufficient for the release page, while Omarchy installs directly from the repository.

## Release notes should cover

- Initial OmaRivian bar widget and details panel.
- R1 legacy telemetry path and R2 Parallax fallback.
- Battery, range, charging, security, cabin, software, odometer, artwork, and optional location.
- Read-only behavior and explicit absence of vehicle commands.
- Linux Secret Service token storage and location privacy controls.
- Requirements: Omarchy Quattro, Python 3.10+, `secret-tool`, and an unlocked Secret Service provider.
- Known limitations: private unsupported Rivian API; R1 is test-covered but not physically validated by the maintainer.
- Install, upgrade, unlink, and removal commands.

## Official marketplace requirements

The marketplace publishing guide requires: [Publish a plugin](https://omarchyplugins.com/publish.html)

- A public GitHub repository.
- One plugin with a valid root `manifest.json`.
- A root README and license.
- Safe installation and removal instructions.
- Documented external dependencies.
- An optional root preview image.

The marketplace submission guide additionally requires: [CLI and AI submission guide](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/SUBMISSION.md)

- A globally unique, permanent plugin ID outside `omarchy.*`.
- One category from the official list.
- One to three official tags.
- Five explicit ownership, documentation, consent, and security acknowledgements.
- A new-listing issue using the exact prescribed headings and checklist.
- Automated compatibility validation and an exact-commit Automated Security Baseline.
- Explicit maintainer `approved-and-verified` approval before publication.

The marketplace validates compatibility and a limited deterministic security baseline. It does not perform a full security review, and Omarchy plugins run unsandboxed. [Marketplace security policy](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/SECURITY.md)

### Recommended listing metadata

- **Repository:** `https://github.com/ttiimmaahh/omarivian`
- **Category:** `Widgets`
- **Tags:** `bar`, `quickshell`
- **Suggested missing tag:** `vehicles` or `automotive` (optional; reviewers decide)
- **Plugin ID:** `io.github.ttiimmaahh.omarivian`
- **Name:** `OmaRivian`
- **License:** `MIT`

Maintainer notes should disclose:

- Python 3.10+, `secret-tool`, and Secret Service requirements.
- Use of Rivian's private unsupported owner API.
- Read-only API allowlist and absence of vehicle commands.
- Sensitive session storage in Secret Service.
- Location disabled by default and removed from local state when disabled.
- R2 validation status and the request for R1 owner feedback.

### Submission mechanism

The official submission route is a GitHub issue form:

<https://github.com/HANCORE-linux/omarchy-plugin-marketplace/issues/new?template=submit-plugin.yml>

For CLI submission, follow the exact issue format in [SUBMISSION.md](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/SUBMISSION.md). An AI agent must show the completed issue title/body and receive explicit owner approval before creating the issue.

## Preview image

A preview is optional; without one, the marketplace uses a fallback. If supplied, it must be one root file named:

- `preview.png`
- `preview.jpg` / `preview.jpeg`
- `preview.webp`
- `preview.avif`

The marketplace accepts normal screenshots and optimizes them automatically. The input limit is 50 MB and 40 megapixels. [Submission guide](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/SUBMISSION.md#check-the-repository)

**Project recommendation:** add a sanitized root `preview.png` showing the bar and open panel. It must not expose real coordinates, VIN fragments, account identity, precise odometer/location history, or other private telemetry. Use synthetic fixture data or capture with location disabled.

## Rights and branding decision

The repository contains `assets/rivian-mark.svg`, titled “Rivian compass mark.” The submission checklist requires the owner to confirm ownership or permission for the plugin and preview assets, and the publishing guide makes the submitter responsible for assets and rights. [Submission issue form](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/.github/ISSUE_TEMPLATE/submit-plugin.yml)

The repository owner has explicitly chosen to ship the first version with the Rivian mark, based on comparable vehicle widgets in the ecosystem using their associated manufacturers' logos. This is therefore an accepted owner risk rather than a release blocker.

Retain the existing non-affiliation disclaimer, do not imply Rivian sponsorship or endorsement, and use only project-owned or otherwise permitted preview imagery. The repository's MIT license does not grant rights to third-party trademarks.

## Exact pre-release checklist

### Repository and version

- [x] Publish `v0.1.0` as a standard early-development GitHub release.
- [x] Accept the owner decision to ship the existing Rivian mark and non-affiliation disclaimer.
- [ ] Add a sanitized `preview.png`, or consciously accept marketplace fallback imagery.
- [x] Keep `manifest.json` and `pyproject.toml` versions identical.
- [x] Ensure README status and release status do not contradict each other.
- [x] Draft `docs/releases/v0.1.0.md`.
- [ ] Ensure `main` contains only intended release content and is pushed.

### Validation

```sh
omarchy plugin validate .
qmllint -I "$OMARCHY_PATH/shell" BarWidget.qml Panel.qml
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/model.test.js
git diff --check
git status --short
```

- [ ] Test clean install from the public repository.
- [ ] Test click, refresh, Escape, shell summon/hide, restart, disable/re-enable, unlink, and removal.
- [ ] Confirm no tokens, coordinates, VINs, or personal telemetry are committed.
- [ ] Re-run the marketplace compatibility validator against pushed `HEAD`.
- [ ] Re-run the exact-commit Automated Security Baseline.

### GitHub release

- [ ] Push tag `v0.1.0` at the final release commit.
- [ ] Verify the tag-triggered validation workflow succeeds.
- [ ] Verify generated source archives contain `manifest.json` at the archive root directory.
- [ ] Verify the published release page and notes.

### Marketplace submission

- [ ] Confirm category `Widgets` and one to three tags.
- [ ] Review every submission checklist statement, especially asset ownership and configuration consent.
- [ ] Show the final issue title/body to the owner.
- [ ] Obtain explicit approval before creating the submission issue.
- [ ] Keep repository `HEAD` unchanged while exact-commit validation and maintainer approval are pending.
- [ ] Respond to validation on the existing issue instead of opening duplicates.

## Updating after listing

A new upstream commit makes the previously verified snapshot display as `Update unverified`. To publish an update, use the marketplace verification form, choose **Verify and publish a newer upstream commit**, and provide the existing plugin ID, repository URL, and full 40-character current `HEAD` SHA. [Plugin verification](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/VERIFICATION.md#promoting-a-plugin-update)

Because Omarchy users track mutable repository `HEAD`, prefer this discipline after listing:

1. Develop on feature branches.
2. Merge only release-ready commits to `main`.
3. Tag and release the same final commit.
4. Submit that exact commit through the marketplace update workflow.

## Primary sources

- [Official Omarchy shell README](https://github.com/basecamp/omarchy/blob/quattro/shell/README.md)
- [Official Omarchy plugin development guide](https://omarchyplugins.com/develop.html)
- [Marketplace publishing guide](https://omarchyplugins.com/publish.html)
- [Marketplace submission guide](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/SUBMISSION.md)
- [Marketplace submission issue form](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/.github/ISSUE_TEMPLATE/submit-plugin.yml)
- [Marketplace security policy](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/SECURITY.md)
- [Marketplace verification guide](https://github.com/HANCORE-linux/omarchy-plugin-marketplace/blob/main/VERIFICATION.md)
- [GitHub release documentation](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
