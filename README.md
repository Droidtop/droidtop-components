# droidtop-components

The Windows-runtime components [droidtop](https://github.com/Droidtop/droidtop) downloads on
demand: Wine and Proton builds, DXVK, VKD3D-Proton, FEXCore, Box64 and WowBox64, Adreno driver
builds (Turnip and others), and the runtime's base system. Nothing here is built or changed:
every file is either re-hosted unmodified or linked where its maker publishes it.

- `sources/mirror.json`: the files this repository re-hosts, each with where it came from and
  its licence. Each lives as an asset of the release named after its group (`drivers`, `wine`,
  `dxvk`, `base`, ...). Seeded on 2026-10-08 with exactly the set droidtop offered through
  GameNative's component list, so nothing a droidtop user could pick went away.
- `sources/feeds.json`: every source droidtop knows: this mirror, droidtop's own Wine builds
  (any Droidtop repository named for Wine or Proton; new releases appear by themselves),
  third-party release feeds, and Steam. Feeds are linked, not re-hosted.
- `catalog.json`, on the [`catalog` release](https://github.com/Droidtop/droidtop-components/releases/tag/catalog):
  what droidtop reads. Written daily by `.github/workflows/catalog.yml`, which carries every
  file's SHA-256 (droidtop checks each download against it) and attests the catalog with a
  Sigstore build provenance (`gh attestation verify catalog.json -R Droidtop/droidtop-components`).

To offer another file: add it to `sources/mirror.json` (group, name, from, licence, and the
`items` or `path` the runtime asks for). To follow another release feed: add it to
`sources/feeds.json`.

Licences: the scripts are GPL-3.0 (LICENSE; the Turnip feed labels follow DroidDeck's
GPL-3.0 `TurnipReleases.kt`). Each component keeps its own licence, named per file
in `sources/mirror.json` and by its maker for feed items; sources for the LGPL builds are with
their makers (Wine/Proton: github.com/GameNative/proton-wine and the feeds' repositories;
VKD3D-Proton: github.com/HansKristian-Work/vkd3d-proton).
