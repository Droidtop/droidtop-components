#!/usr/bin/env python3
"""Re-hosts every file named in sources/mirror.json, unmodified, as an asset of this
repository's release named after its group (drivers, dxvk, wine, base, ...).

The releases are the state: a file already there is never fetched again or replaced, so a
mirrored build stays exactly what it was when it was first fetched. A new file is checked
before upload against the SHA-256 in mirror.json when it has one, else against the SHA-256
GitHub publishes for it when its source is a GitHub release. A file from a host that
publishes no checksum is taken as fetched, its SHA-256 written to the job summary; from then
on GitHub's digest of our asset fixes it, and the catalog carries that digest.

hosting "link": the file's terms explicitly forbid redistribution (prohibitedBy cites the
clause). It is not re-hosted, and a copy still on our release is removed: this is the takedown
switch (README.md, "Takedown"). droidtop then fetches it from its maker's URL with the same
SHA-256.

source: for an LGPL/GPL build whose exact source is known (source.exact), the source archive of
that tag or commit is re-hosted in the same release (LGPL-2.1 section 4: "equivalent access to
copy the source code from the same place"). Every release's notes list each file's licence and
where its source is.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import REPO, download, release, upstream_github_sha256  # noqa: E402

GROUP_TITLES = {
    'base': 'Windows runtime base system',
    'container-files': 'Wine prefix templates',
    'core-drivers': 'Adreno core drivers',
    'graphics-driver': 'Graphics driver packages',
    'wincomponents': 'Windows components',
    'dxwrapper': 'DXVK and VKD3D runtime archives',
    'drivers': 'Adreno driver builds',
    'dxvk': 'DXVK builds',
    'vkd3d': 'VKD3D-Proton builds',
    'box64': 'Box64 and WowBox64 builds',
    'fexcore': 'FEXCore builds',
    'wine': 'Wine and Proton builds',
    'tools': 'Tools built by droidtop from upstream source',
}


def source_asset(src):
    """(asset name, archive URL) of an exact source pointer, else None."""
    if not src or not src.get('exact'):
        return None
    repo, ref = src['repo'], src['ref']
    return f'source-{repo.split("/")[1]}-{ref}.tar.gz', f'https://github.com/{repo}/archive/{ref}.tar.gz'


def source_text(src):
    if not src:
        return ''
    where = f'[{src["repo"]}@{src["ref"]}](https://github.com/{src["repo"]}/tree/{src["ref"]})'
    asset = source_asset(src)
    return where + (f', archive `{asset[0]}` in this release' if asset else f' (not exact: {src.get("note", "")})')


def notes(group, entries):
    lines = [f'Files re-hosted unmodified for droidtop; sources/mirror.json says where each came from. '
             f'droidtop checks every download against the SHA-256 listed here.', '',
             '| File | SHA-256 | Licence | Corresponding source |', '|---|---|---|---|']
    linked = []
    for e in entries:
        if e.get('hosting') == 'link':
            linked.append(e)
            continue
        lic = f'[{e["licence"]}]({e["licenceUrl"]})' if e.get('licenceUrl') else e['licence']
        lines.append(f'| {e["name"]} | `{e.get("sha256", "")}` | {lic} | {source_text(e.get("source"))} |')
    if linked:
        lines += ['', 'Not re-hosted (their terms forbid redistribution); droidtop fetches them from the URL below:', '']
        lines += [f'- {e["name"]} (`{e["sha256"]}`): {e["from"]}. {e["prohibitedBy"]}' for e in linked]
    return '\n'.join(lines) + '\n'


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = json.load(open(os.path.join(root, 'sources', 'mirror.json')))['files']
    summary, failed, releases = [], [], {}
    work = tempfile.mkdtemp(prefix='mirror-')
    by_group = {}
    for e in files:
        by_group.setdefault(e['group'], []).append(e)
    for group, entries in by_group.items():
        releases[group] = release(
            group, create=True, title=GROUP_TITLES.get(group, group),
            notes='Files re-hosted unmodified for droidtop; sources/mirror.json says where each came from.')
        have = {a['name'].lower(): a for a in releases[group]['assets']}
        uploads = []
        for e in entries:
            if e.get('hosting') == 'link':
                if e['name'].lower() in have:
                    subprocess.run(['gh', 'release', 'delete-asset', group, have[e['name'].lower()]['name'],
                                    '-R', REPO, '-y'], check=True)
                    summary.append(f'| {group} | {e["name"]} | `{e.get("sha256", "")}` | taken down (link only) |')
                    print(f'taken down {group}/{e["name"]}', flush=True)
                continue
            if e['name'].lower() not in have:
                uploads.append((e['name'], e['from'], e.get('sha256') or upstream_github_sha256(e['from'])))
            src = source_asset(e.get('source'))
            if src and src[0].lower() not in have and src[0] not in [u[0] for u in uploads]:
                uploads.append((src[0], src[1], None))
        for name, url, expected in uploads:
            dest = os.path.join(work, name)
            try:
                actual = download(url, dest)
                if expected and expected.lower() != actual:
                    raise RuntimeError(f'SHA-256 {actual} is not the expected {expected}')
                subprocess.run(['gh', 'release', 'upload', group, dest, '-R', REPO], check=True)
                summary.append(f'| {group} | {name} | `{actual}` | {"checked" if expected else "first fetch"} |')
                print(f'mirrored {group}/{name} {actual}', flush=True)
            except Exception as ex:  # one bad source must not stop the rest
                failed.append(f'{group}/{name} from {url}: {ex}')
                print(f'FAILED {group}/{name}: {ex}', file=sys.stderr, flush=True)
            finally:
                if os.path.exists(dest):
                    os.remove(dest)
        notes_file = os.path.join(work, f'{group}.md')
        with open(notes_file, 'w') as f:
            f.write(notes(group, entries))
        subprocess.run(['gh', 'release', 'edit', group, '-R', REPO, '--notes-file', notes_file], check=True)
    out = os.environ.get('GITHUB_STEP_SUMMARY')
    if out:
        with open(out, 'a') as s:
            s.write(f'## Mirror\n\n{len(summary)} change(s), {len(failed)} failure(s).\n\n')
            if summary:
                s.write('| Release | File | SHA-256 | Check |\n|---|---|---|---|\n' + '\n'.join(summary) + '\n')
            for f in failed:
                s.write(f'- FAILED {f}\n')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
