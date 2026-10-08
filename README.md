# droidtop-components

The Windows-runtime components [droidtop](https://github.com/Droidtop/droidtop) downloads on
demand: Wine and Proton builds, DXVK, VKD3D-Proton, FEXCore, Box64 and WowBox64, Adreno driver
builds (Turnip and others), and the runtime's base system. Nothing here is built or changed:
every file is either re-hosted unmodified or linked where its maker publishes it.

- `sources/mirror.json`: the files this repository offers, each with where it came from (`from`,
  plus `official`: other places its maker publishes the same bytes), its SHA-256, its licence and,
  for LGPL/GPL builds, where its source is (`source`). Each re-hosted file lives as an asset of the
  release named after its group (`drivers`, `wine`, `dxvk`, `base`, ...); each release's notes list
  its files' licences and sources. Seeded on 2026-10-08 with exactly the set droidtop offered through
  GameNative's component list, so nothing a droidtop user could pick went away.
- `sources/feeds.json`: every source droidtop knows: this mirror, droidtop's own Wine builds
  (any Droidtop repository named for Wine or Proton; new releases appear by themselves),
  third-party release feeds, and Steam. Feeds are linked, not re-hosted.
- `catalog.json`, on the [`catalog` release](https://github.com/Droidtop/droidtop-components/releases/tag/catalog):
  what droidtop reads. Written daily by `.github/workflows/catalog.yml`. Every item and file carries
  its SHA-256 and `urls`: our copy first, then its makers' copies; droidtop tries them in order and
  accepts only bytes with that SHA-256. The catalog is attested with a Sigstore build provenance
  (`gh attestation verify catalog.json -R Droidtop/droidtop-components`) and, once the signing
  secrets exist, signed (below).

To offer another file: add it to `sources/mirror.json` (group, name, from, sha256, licence, and the
`items` or `path` the runtime asks for). To follow another release feed: add it to
`sources/feeds.json`. `tools/test_rules.py` checks that every file has a SHA-256 and a licence.

## Licences

The scripts are GPL-3.0 (LICENSE; the Turnip feed labels follow DroidDeck's GPL-3.0
`TurnipReleases.kt`). Each component keeps its own licence, named per file in `sources/mirror.json`.
The rule: a file is re-hosted unless its terms explicitly forbid redistribution; such a file is
link-only (`hosting: "link"`, `prohibitedBy` quotes the clause) and droidtop fetches it from its
maker with the recorded SHA-256.

| Files | Licence | Here |
|---|---|---|
| Wine/Proton builds (`wine`, `base/proton-9.0-*`), Wine prefix templates except the common one | LGPL-2.1-or-later | re-hosted; source: GameNative/proton-wine (exact tag for Proton 11.0-1, re-hosted as `source-*.tar.gz` beside it; branch only for the others, which name no commit) |
| DXVK, d8vk, DXVK-Sarek/async/gplasync | Zlib | re-hosted |
| VKD3D-Proton | LGPL-2.1-or-later | re-hosted, with the source archive of the tag or commit each is named for |
| Box64, WowBox64, FEXCore | MIT | re-hosted |
| Turnip, Zink, VirGL, Mesa opengl32, Vulkan wrappers | MIT (Mesa; libadrenotools BSD-2-Clause) | re-hosted |
| `wincomponents/ddraw`, `openal` | MIT (cnc-ddraw), LGPL-2.0-or-later (OpenAL Soft 1.25.1, source re-hosted) | re-hosted |
| `container_files/extras` | 7-Zip (LGPL-2.1 + unRAR restriction), Steamless (CC BY-NC-ND 4.0), wine-mono | re-hosted unmodified, non-commercially |
| `imagefs_*` | Termux-built packages (GPL, LGPL, MIT, BSD...) | re-hosted; recipes: termux/termux-packages |
| Qualcomm Adreno drivers, Vortek | proprietary, no licence accompanies them | re-hosted (no clause forbids it) |
| `wincomponents/direct3d, xaudio, directmusic, directplay` | Microsoft DirectX End User Runtime: "You may not ... publish the software for others to copy" | link only |
| `wincomponents/directshow, directsound, wmdecoder` | Windows 7 system files: same clause (Windows 7 terms, 8) | link only |
| `wincomponents/vcrun2010` | Visual C++ 2010 runtime terms, 2: same clause | link only |
| `container_files/container_pattern_common_20260821` | Monotype and Microsoft fonts inside: "You may not copy or distribute this software."; "Any other use is prohibited." | link only |

## Takedown

To stop re-hosting a file (a takedown request, or terms that turn out to forbid it): in
`sources/mirror.json` set `"hosting": "link"` and `"prohibitedBy": "<who asked / which clause>"`
on its entry (a whole group: every entry with that `group`), and push to `main`. The workflow's
mirror job then removes our copy from the release, and the catalog lists only its maker's URL
with the same SHA-256, so droidtop keeps installing the identical file from its maker.

## Catalog signature

When the repository secrets `CATALOG_SIGNING_KEY` (a PEM P-256 private key) and
`CATALOG_SIGNING_CERT` (its certificate) exist, the workflow writes `catalog.json.sig` (base64 DER
ECDSA/SHA-256 over the exact bytes of `catalog.json`) and `catalog.cert` to the `catalog` release,
and `catalog.json` names them in its `signature` field. The certificate is droidtop's plugin
certificate format with `catalogs` instead of `pluginIds`, issued by droidtop's master key over
these bytes:

    droidtop-catalog-cert-v1
    id:<certId>
    catalogs:Droidtop/droidtop-components
    key:<publicKeySpki>
    notBefore:<epoch s>
    notAfter:<epoch s>

droidtop checks the pair once its build pins a master key, and accepts an unsigned catalog
until then.
