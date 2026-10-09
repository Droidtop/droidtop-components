# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The component
releases of this repository (`catalog`, `wine`, `wincomponents`, `vkd3d`,
`graphics-driver`, ...) are rolling: each is replaced when its contents are
re-hosted again. This file is the record of how the repository itself and its
scripts changed; what a release held at a given time is in the commit history of
the catalog it publishes.

## [Unreleased]

### Added

- The mirror and catalog for droidtop's Windows-runtime components (2026-10-08).
- A commit-hygiene check, called from the shared workflow in `Droidtop/droidtop-platforms`.

### Changed

- Wine builds from different sources are kept apart, and the scripts are under GPL-3.0 (2026-10-08).
- Only what no licence forbids is re-hosted; the makers' own URLs are listed as fallback mirrors (2026-10-08).
- The Microsoft files and the font-bearing prefix template are re-hosted again, by the owner's decision (2026-10-08).

### Fixed

- VKD3D-Proton source references: a dot the file-name pattern caught is dropped (2026-10-08).
