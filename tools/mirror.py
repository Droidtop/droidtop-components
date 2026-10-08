#!/usr/bin/env python3
"""Re-hosts every file named in sources/mirror.json, unmodified, as an asset of this
repository's release named after its group (drivers, dxvk, wine, base, ...).

The releases are the state: a file already there is never fetched again or replaced, so a
mirrored build stays exactly what it was when it was first fetched. A new file is checked
before upload against the SHA-256 in mirror.json when it has one, else against the SHA-256
GitHub publishes for it when its source is a GitHub release. A file from a host that
publishes no checksum is taken as fetched, its SHA-256 written to the job summary; from then
on GitHub's digest of our asset fixes it, and the catalog carries that digest.
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
}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = json.load(open(os.path.join(root, 'sources', 'mirror.json')))['files']
    summary, failed, releases = [], [], {}
    work = tempfile.mkdtemp(prefix='mirror-')
    for e in files:
        group = e['group']
        if group not in releases:
            releases[group] = release(
                group, create=True, title=GROUP_TITLES.get(group, group),
                notes='Files re-hosted unmodified for droidtop; sources/mirror.json says where each came from.')
        have = {a['name'].lower() for a in releases[group]['assets']}
        if e['name'].lower() in have:
            continue
        dest = os.path.join(work, e['name'])
        try:
            actual = download(e['from'], dest)
            expected = e.get('sha256') or upstream_github_sha256(e['from'])
            if expected and expected.lower() != actual:
                raise RuntimeError(f'SHA-256 {actual} is not the expected {expected}')
            subprocess.run(['gh', 'release', 'upload', group, dest, '-R', REPO], check=True)
            summary.append(f'| {group} | {e["name"]} | `{actual}` | {"checked" if expected else "first fetch"} |')
            print(f'mirrored {group}/{e["name"]} {actual}', flush=True)
        except Exception as ex:  # one bad source must not stop the rest
            failed.append(f'{group}/{e["name"]} from {e["from"]}: {ex}')
            print(f'FAILED {group}/{e["name"]}: {ex}', file=sys.stderr, flush=True)
        finally:
            if os.path.exists(dest):
                os.remove(dest)
    out = os.environ.get('GITHUB_STEP_SUMMARY')
    if out:
        with open(out, 'a') as s:
            s.write(f'## Mirror\n\n{len(summary)} new file(s), {len(failed)} failure(s).\n\n')
            if summary:
                s.write('| Release | File | SHA-256 | Check |\n|---|---|---|---|\n' + '\n'.join(summary) + '\n')
            for f in failed:
                s.write(f'- FAILED {f}\n')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
