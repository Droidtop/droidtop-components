#!/usr/bin/env python3
"""The Wine/Proton id rules, checked against the cases droidtop's WineBuildRulesTest checks;
the order of a file's download URLs; and that sources/mirror.json is complete."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_catalog import (add_flavour, asset_flavour, canonical_name, mirror_urls, runtime_ver_code,  # noqa: E402
                           runtime_ver_name)

CASES = [
    # (profile type, profile versionName, arch from the wine binary, installed name)
    ('Proton', 'proton-10.0-4-x86_64', 'x86_64', 'proton-10.0-4-x86_64'),
    ('Proton', 'proton-10.0-arm64ec', 'arm64ec', 'proton-10.0-arm64ec'),
    ('Proton', '11.0-2-arm64ec', 'arm64ec', 'proton-11.0-2-arm64ec'),
    ('Proton', 'GE-proton-11.0-7.1-arm64ec', 'arm64ec', 'proton-11.0-7.1-ge-arm64ec'),
    ('Proton', 'proton-11.0-1-beta5-custom-arm64ec', 'arm64ec', 'proton-11.0-1-beta5.custom-arm64ec'),
    ('Wine', 'wine-9.2-x86_64', 'x86_64', 'wine-9.2-x86_64'),
    ('Wine', 'proton-11.0-1-custom', 'arm64ec', 'proton-11.0-1-custom-arm64ec'),
    ('Proton', 'proton-10.0-x86_64', 'arm64ec', 'proton-10.0-arm64ec'),
    ('Wine', '10.5-staging', 'x86_64', 'wine-10.5-staging-x86_64'),
    ('Proton', 'experimental', 'x86_64', None),
]


def main():
    bad = 0
    for typ, ver, arch, want in CASES:
        got = canonical_name(runtime_ver_name(typ, ver), arch)
        if got != want:
            print(f'{typ} {ver} {arch}: got {got}, want {want}')
            bad += 1
    for name, word, want in [('proton-11.0-7-arm64ec', 'ge', 'proton-11.0-7-ge-arm64ec'),
                             ('proton-11.0-7-ge-arm64ec', 'wlc', 'proton-11.0-7-ge.wlc-arm64ec'),
                             ('proton-10.0-arm64ec', 'wlc', 'proton-10.0-wlc-arm64ec')]:
        if add_flavour(name, word) != want:
            print(f'{name} + {word}: got {add_flavour(name, word)}, want {want}')
            bad += 1
    if asset_flavour('GE-proton-11.0-7-arm64ec.wcp') != 'ge' or asset_flavour('proton-11.0-2-x86_64.wcp') is not None:
        print('asset_flavour')
        bad += 1
    for code, want in [(0, 0), (1, 1), (9, 9), (10, 0), (-1, 0)]:
        if runtime_ver_code(code) != want:
            print(f'version code {code}: got {runtime_ver_code(code)}, want {want}')
            bad += 1
    ours, maker, other = 'https://ours/x', 'https://maker/x', 'https://other/x'
    for entry, asset, want in [({'from': maker}, ours, [ours, maker]),
                               ({'from': maker, 'official': [other, maker]}, ours, [ours, maker, other]),
                               ({'from': maker, 'hosting': 'link'}, ours, [maker]),
                               ({'from': maker}, None, [maker])]:
        if mirror_urls(entry, asset) != want:
            print(f'mirror_urls {entry} {asset}: got {mirror_urls(entry, asset)}, want {want}')
            bad += 1
    # mirror.json: every file has a recorded SHA-256 and a licence; a link-only file cites its clause.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for e in json.load(open(os.path.join(root, 'sources', 'mirror.json')))['files']:
        problems = [k for k in ('sha256', 'licence') if not e.get(k)]
        if e.get('hosting') not in (None, 'link'):
            problems.append('hosting')
        if e.get('hosting') == 'link' and not e.get('prohibitedBy'):
            problems.append('prohibitedBy')
        if e.get('source') and not (e['source'].get('repo') and e['source'].get('ref')):
            problems.append('source')
        if problems:
            print(f'mirror.json {e["group"]}/{e["name"]}: missing or bad {", ".join(problems)}')
            bad += 1
    if bad:
        sys.exit(1)
    print(f'{len(CASES)} id cases, mirror URL order and mirror.json pass')


if __name__ == '__main__':
    main()
