#!/usr/bin/env python3
"""The Wine/Proton id rules, checked against the cases droidtop's WineBuildRulesTest checks."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_catalog import canonical_name, runtime_ver_code, runtime_ver_name  # noqa: E402

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
    for code, want in [(0, 0), (1, 1), (9, 9), (10, 0), (-1, 0)]:
        if runtime_ver_code(code) != want:
            print(f'version code {code}: got {runtime_ver_code(code)}, want {want}')
            bad += 1
    if bad:
        sys.exit(1)
    print(f'{len(CASES)} id cases pass')


if __name__ == '__main__':
    main()
