#!/usr/bin/env python3
"""Writes catalog.json, the one list droidtop reads to know which components it can offer.

Inputs:
  sources/mirror.json  files this repository re-hosts (tools/mirror.py); each item names the
                       content type and id the runtime asks for, each path a base-system file.
  sources/feeds.json   the sources droidtop knows: this mirror, droidtop's own Wine builds
                       (found by name in the Droidtop organisation, so a new repository or
                       release appears by itself), third-party release feeds, Steam.

Feed items are linked where their makers publish them, never re-hosted, and only when GitHub
publishes a SHA-256 for the asset, which droidtop checks the download against. A .wcp (the
Winlator/GameNative content package: a tar.xz or tar.zst with profile.json) is read once to
learn what the runtime will install it as; an Adreno driver zip once for its meta.json name.
Those answers are cached by SHA-256 in probe-cache.json beside the catalog, so each asset is
downloaded once ever.

The Wine/Proton id rules here are the runtime's (droidtop's WineBuildRules.kt): the same
canonical id on both sides, or a build would never count as installed.

usage: build_catalog.py <out dir>
"""
import datetime
import io
import json
import os
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import REPO, asset_sha256, download, gh_api, gh_api_pages, release  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_TAG = 'catalog'

# ---- Wine/Proton ids (keep in step with droidtop's WineBuildRules.kt) ----------------------

WINE_TYPES = ('wine', 'proton')
ARCH_TOKENS = {'x86_64': 'x86_64', 'amd64': 'x86_64', 'x64': 'x86_64', 'arm64ec': 'arm64ec',
               'aarch64': 'arm64ec', 'arm64': 'arm64ec', 'x86': 'x86', 'i386': 'x86'}
# WineInfo's identifier pattern, as droidtop widened it for a flavour word (without the
# trailing "-<verCode>", which the id adds).
RUNTIME_NAME = re.compile(r'^(wine|proton|Proton)-([0-9.]+)(?:-([0-9.]+))?(?:-[a-z][a-z0-9.]*)?-(x86|x86_64|arm64ec)$')
NUMBER = re.compile(r'^\d+(\.\d+)*$')


def runtime_ver_name(type_name, ver_name):
    """What ContentsManager.readProfile makes of a profile's versionName."""
    t = type_name.lower()
    return ver_name if ver_name.lower().startswith(t) else f'{t}-{ver_name}'


def canonical_name(ver_name, arch):
    """The name a Wine/Proton build is installed under: [ver_name] when the runtime already
    reads it and it names [arch]; otherwise <type>-<version>[-<rev>][-<flavour>]-<arch>.
    None when no type or version can be found."""
    if RUNTIME_NAME.match(ver_name) and (arch is None or ver_name.endswith('-' + arch)):
        return ver_name
    toks = [t for t in re.split(r'[-\s]+', ver_name.lower()) if t]
    # "wine-proton-11.0-1" (a Wine-typed profile of a Proton build) is a Proton.
    typ = 'proton' if 'proton' in toks else 'wine' if 'wine' in toks else None
    if typ is None:
        return None
    rest = [t for t in toks if t not in WINE_TYPES]
    named_arch = next((ARCH_TOKENS[t] for t in rest if t in ARCH_TOKENS), None)
    rest = [t for t in rest if t not in ARCH_TOKENS and t != 'wow64']
    arch = arch or named_arch
    if arch is None:
        return None
    vi = next((i for i, t in enumerate(rest) if NUMBER.match(t)), None)
    if vi is None:
        return None
    version = rest[vi]
    rev = rest[vi + 1] if vi + 1 < len(rest) and NUMBER.match(rest[vi + 1]) else None
    used = {vi} | ({vi + 1} if rev else set())
    flavour = '.'.join(f for f in (re.sub(r'[^a-z0-9.]', '', t) for i, t in enumerate(rest) if i not in used) if f)
    if flavour and not flavour[0].isalpha():
        flavour = 'r' + flavour
    return '-'.join([typ, version] + ([rev] if rev else []) + ([flavour] if flavour else []) + [arch])


def runtime_ver_code(ver_code):
    """WineInfo drops the last two characters of an id ("-1"), so the code is one digit."""
    return ver_code if 0 <= ver_code <= 9 else 0


# ---- ELF ------------------------------------------------------------------------------------

def elf_info(head):
    """Machine and interpreter of an ELF file from its first bytes, or None."""
    if len(head) < 64 or head[:4] != b'\x7fELF':
        return None
    is64, e = head[4] == 2, ('<' if head[5] == 1 else '>')
    machine = struct.unpack_from(e + 'H', head, 18)[0]
    if is64:
        phoff = struct.unpack_from(e + 'Q', head, 32)[0]
        phentsize, phnum = struct.unpack_from(e + 'HH', head, 54)
    else:
        phoff = struct.unpack_from(e + 'I', head, 28)[0]
        phentsize, phnum = struct.unpack_from(e + 'HH', head, 42)
    interp = None
    for i in range(phnum):
        off = phoff + i * phentsize
        if off + phentsize > len(head):
            break
        if struct.unpack_from(e + 'I', head, off)[0] == 3:  # PT_INTERP
            if is64:
                p_off, p_sz = struct.unpack_from(e + 'Q', head, off + 8)[0], struct.unpack_from(e + 'Q', head, off + 32)[0]
            else:
                p_off, p_sz = struct.unpack_from(e + 'I', head, off + 4)[0], struct.unpack_from(e + 'I', head, off + 16)[0]
            if p_off + p_sz <= len(head):
                interp = head[p_off:p_off + p_sz].rstrip(b'\0').decode(errors='replace')
    return {'machine': {0xB7: 'aarch64', 0x3E: 'x86_64', 0x03: 'x86'}.get(machine, hex(machine)), 'interp': interp}


def engine_of(interp):
    """bionic: Android's linker, droidtop's Wine runtime; linux-glibc: needs a glibc userland."""
    if interp is None:
        return 'bionic'
    return 'bionic' if 'linker' in interp else 'linux-glibc'


def build_arch(machine):
    return {'aarch64': 'arm64ec', 'x86_64': 'x86_64', 'x86': 'x86'}.get(machine)


# ---- probes ---------------------------------------------------------------------------------

def probe_wcp(path):
    """profile.json and the wine binary's ELF header of a .wcp, read as a stream."""
    with open(path, 'rb') as f:
        magic = f.read(6)
    tool = ['xz', '-dc'] if magic.startswith(b'\xfd7zXZ') else ['zstd', '-dc'] if magic.startswith(b'\x28\xb5\x2f\xfd') else None
    if tool is None:
        return {'error': 'not a tar.xz or tar.zst'}
    proc = subprocess.Popen(tool + [path], stdout=subprocess.PIPE)
    profile, heads = None, {}
    # bin/wine is often a symlink into lib/wine/<arch>-unix; wineserver is a real binary.
    unix_bin = re.compile(r'(^|/)(bin/(wineserver|wine|wine64)|lib/wine/[^/]+-unix/wine)$')
    try:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as tar:
            for m in tar:
                name = m.name[2:] if m.name.startswith('./') else m.name
                if name == 'profile.json' and m.isfile():
                    profile = json.load(tar.extractfile(m))
                elif m.isfile() and unix_bin.search(name):
                    heads[name] = tar.extractfile(m).read(65536)
                if profile is not None:
                    wine = profile.get('proton') or profile.get('wine')
                    if not wine or f'{wine.get("binPath", "bin").strip("/")}/wineserver' in heads:
                        break
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()
    if profile is None:
        return {'error': 'no profile.json'}
    out = {'type': profile.get('type'), 'versionName': profile.get('versionName'),
           'versionCode': int(profile.get('versionCode') or 0), 'description': profile.get('description')}
    wine = profile.get('proton') or profile.get('wine')
    if wine:
        bin_path = wine.get('binPath', 'bin').strip('/')
        order = [f'{bin_path}/wineserver', f'{bin_path}/wine', f'{bin_path}/wine64'] + sorted(heads)
        info = next((i for i in (elf_info(heads[p]) for p in order if p in heads) if i), None)
        if info:
            out['elf'] = info
    return out


def probe_adrenotools(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if 'meta.json' not in names:
            return {'error': 'no meta.json'}
        meta = json.loads(z.read('meta.json'))
    return {'name': meta.get('name'), 'driverVersion': meta.get('driverVersion'), 'description': meta.get('description')}


# ---- driver labels (were DriverReleases.kt's, borrowed from DroidDeck's TurnipReleases) ------

def classify_banners(name, tag):
    prefix = f'Turnip-{tag}'
    if not name.startswith(prefix) or not name.endswith('.zip'):
        return None
    variant = name[len(prefix):-len('.zip')]
    if variant.endswith('-Wayland') or variant.endswith('-Linux'):
        return None
    if variant == '':
        return 'Adreno 6xx/7xx'
    if variant == '-A8xx':
        return 'Adreno 8xx'
    if variant.startswith('-710-720'):
        return 'Adreno 710/720' + (' (test)' if 'Test' in variant else '')
    if 'oneui' in variant.lower():
        return '8 Gen 2 on One UI'
    return variant.lstrip('-')


def classify_winnative(name, tag):
    m = re.match(r'^WN-Turnip-[^-]+-([a-z]+)_(\w+)\.zip$', name)
    if not m:
        return None
    flavour = {'b': 'Balanced', 'p': 'Performance'}.get(m.group(1), m.group(1))
    gpus = 'all Adreno' if m.group(2) == 'Axxx' else m.group(2)
    return f'{gpus}, {flavour}'


CLASSIFY = {'banners-turnip': classify_banners, 'winnative': classify_winnative}

WCP_TYPES = {'wine': 'wine', 'proton': 'proton', 'dxvk': 'dxvk', 'vkd3d': 'vkd3d', 'box64': 'box64',
             'wowbox64': 'wowbox64', 'fexcore': 'fexcore'}


# ---- catalog --------------------------------------------------------------------------------

def mirrored_items(items, files):
    mirror = json.load(open(os.path.join(ROOT, 'sources', 'mirror.json')))['files']
    assets = {}
    for group in sorted({e['group'] for e in mirror}):
        r = release(group)
        assets[group] = {a['name'].lower(): a for a in (r['assets'] if r else [])}
    missing = 0
    for e in mirror:
        a = assets[e['group']].get(e['name'].lower())
        if a is None or not asset_sha256(a):
            missing += 1
            continue
        if e.get('path'):
            files[e['path']] = {'url': a['browser_download_url'], 'sha256': asset_sha256(a), 'size': a['size']}
        for it in e.get('items', []):
            items.setdefault(it['type'], []).append(dict(
                it, url=a['browser_download_url'], sha256=asset_sha256(a), size=a['size'], source='mirror',
                engine='bionic', licence=e.get('licence'), upstream=e['from']))
    print(f'mirror: {sum(len(v) for v in items.values())} items, {len(files)} files, {missing} not mirrored yet')


def feed_repos(feed):
    if 'repo' in feed:
        return [feed['repo']]
    d = feed['discover']
    pat = re.compile(d['name'], re.I)
    repos = gh_api_pages(f'orgs/{d["org"]}/repos?type=public')
    return sorted(r['full_name'] for r in repos if pat.search(r['name']) and not r.get('archived') and r['full_name'] != REPO)


def feed_items(feed, items, cache, work):
    fmt, pat = feed['format'], re.compile(feed.get('assets', '.'))
    classify = CLASSIFY.get(feed.get('classify'))
    count = 0
    for repo in feed_repos(feed):
        releases = gh_api(f'repos/{repo}/releases?per_page={feed.get("releases", 10)}')
        seen = set()
        for r in releases:  # newest first: the newest release carrying a name wins
            if r.get('draft'):
                continue
            for a in r.get('assets', []):
                name, sha = a['name'], asset_sha256(a)
                if not sha or not pat.search(name) or name.lower() in seen:
                    continue
                label = classify(name, r['tag_name']) if classify else name
                if label is None:
                    continue
                seen.add(name.lower())
                base = {'url': a['browser_download_url'], 'sha256': sha, 'size': a['size'], 'source': feed['id'],
                        'variant': 'bionic', 'tag': r['tag_name'], 'upstream': r['html_url']}
                if fmt == 'linux-tar':
                    arch = next((v for k, v in [('aarch64', 'aarch64'), ('arm64', 'aarch64'), ('x86_64', 'x86_64'),
                                                ('amd64', 'x86_64'), ('x86', 'x86')] if k in name.lower()), 'x86_64')
                    ident = re.sub(r'\.tar\.(gz|xz|zst)$', '', name)
                    items.setdefault(feed['type'], []).append(dict(base, id=ident, name=ident, arch=arch, engine='linux-glibc'))
                    count += 1
                    continue
                probe = cache.get(sha)
                if probe is None:
                    dest = os.path.join(work, 'probe')
                    try:
                        actual = download(a['browser_download_url'], dest)
                        if actual != sha:
                            print(f'{repo} {name}: SHA-256 {actual} is not GitHub\'s {sha}; skipped')
                            continue
                        probe = probe_wcp(dest) if fmt == 'wcp' else probe_adrenotools(dest)
                    except Exception as ex:
                        probe = {'error': str(ex)}
                    finally:
                        if os.path.exists(dest):
                            os.remove(dest)
                    cache[sha] = probe
                if 'error' in probe:
                    continue
                if fmt == 'adrenotools':
                    if not probe.get('name'):
                        continue
                    items.setdefault('driver', []).append(dict(base, id=probe['name'], name=label, engine='bionic'))
                    count += 1
                    continue
                typ = WCP_TYPES.get((probe.get('type') or '').lower())
                if typ is None or probe.get('versionName') is None:
                    continue
                code = probe['versionCode']
                if typ in WINE_TYPES:
                    elf = probe.get('elf') or {}
                    arch = build_arch(elf.get('machine'))
                    ver = canonical_name(runtime_ver_name(probe['type'], probe['versionName']), arch)
                    if ver is None:
                        continue
                    ident = f'{ver}-{runtime_ver_code(code)}'
                    items.setdefault(typ, []).append(dict(base, id=ident, name=ver, arch=ver.rsplit('-', 1)[1],
                                                          engine=engine_of(elf.get('interp'))))
                else:
                    ident = f'{probe["versionName"]}-{code}'
                    items.setdefault(typ, []).append(dict(base, id=ident, name=ident, engine='bionic'))
                count += 1
    print(f'{feed["id"]}: {count} items')


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    feeds = json.load(open(os.path.join(ROOT, 'sources', 'feeds.json')))['sources']
    work = tempfile.mkdtemp(prefix='catalog-')
    cache = {}
    cat = release(CATALOG_TAG)
    if cat and any(a['name'] == 'probe-cache.json' for a in cat['assets']):
        subprocess.run(['gh', 'release', 'download', CATALOG_TAG, '-R', REPO, '-p', 'probe-cache.json', '-D', work], check=True)
        cache = json.load(open(os.path.join(work, 'probe-cache.json')))
    items, files = {}, {}
    mirrored_items(items, files)
    for feed in feeds:
        if feed.get('format'):
            feed_items(feed, items, cache, work)
    catalog = {
        'format': 1,
        # ManifestData's own fields, so the runtime reads the catalog with the same model.
        'version': 1,
        'updatedAt': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'sources': [{k: v for k, v in f.items() if k in ('id', 'label', 'kind', 'engine', 'defaultEnabled', 'about', 'homepage')}
                    for f in feeds],
        'items': items,
        'files': files,
    }
    with open(os.path.join(out, 'catalog.json'), 'w') as f:
        json.dump(catalog, f, indent=1, sort_keys=False)
        f.write('\n')
    with open(os.path.join(out, 'probe-cache.json'), 'w') as f:
        json.dump(cache, f, indent=1, sort_keys=True)
    total = sum(len(v) for v in items.values())
    print(f'catalog: {total} items in {len(items)} types, {len(files)} files')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as s:
            s.write(f'## Catalog\n\n{total} items, {len(files)} base-system files.\n\n| Type | Items |\n|---|---|\n')
            for t, v in sorted(items.items()):
                s.write(f'| {t} | {len(v)} |\n')


if __name__ == '__main__':
    main()
