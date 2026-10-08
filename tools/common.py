"""Shared helpers for the mirror and catalog scripts: GitHub API calls through the gh CLI
(authenticated by GH_TOKEN in CI), release listings, downloads with a SHA-256."""
import hashlib
import json
import os
import re
import subprocess
import urllib.parse

REPO = os.environ.get('GITHUB_REPOSITORY', 'Droidtop/droidtop-components')
GH_RELEASE_URL = re.compile(r'^https://github\.com/([^/]+/[^/]+)/releases/download/([^/]+)/([^/]+)$')


def gh_api(path, allow_missing=False):
    """GET an API path; None for a 404 when allow_missing."""
    p = subprocess.run(['gh', 'api', '-H', 'Accept: application/vnd.github+json', path],
                       capture_output=True, text=True)
    if p.returncode != 0:
        if allow_missing and ('404' in p.stderr or 'Not Found' in p.stderr):
            return None
        raise RuntimeError(f'gh api {path}: {p.stderr.strip()}')
    return json.loads(p.stdout)


def gh_api_pages(path, limit_pages=10):
    out = []
    sep = '&' if '?' in path else '?'
    for page in range(1, limit_pages + 1):
        chunk = gh_api(f'{path}{sep}per_page=100&page={page}')
        out.extend(chunk)
        if len(chunk) < 100:
            break
    return out


def release(tag, create=False, title=None, notes=''):
    """This repository's release named [tag] with all its assets; created when asked."""
    r = gh_api(f'repos/{REPO}/releases/tags/{tag}', allow_missing=True)
    if r is None and create:
        subprocess.run(['gh', 'release', 'create', tag, '-R', REPO, '--title', title or tag,
                        '--notes', notes, '--latest=false'], check=True)
        r = gh_api(f'repos/{REPO}/releases/tags/{tag}')
    if r is None:
        return None
    # A release lists at most 100 assets inline; read them all.
    r['assets'] = gh_api_pages(f'repos/{REPO}/releases/{r["id"]}/assets')
    return r


def asset_sha256(asset):
    d = asset.get('digest') or ''
    return d[len('sha256:'):] if d.startswith('sha256:') else None


def upstream_github_sha256(url):
    """GitHub's SHA-256 of a release asset given by its download URL; None for other hosts."""
    m = GH_RELEASE_URL.match(url)
    if not m:
        return None
    repo, tag, name = m.groups()
    r = gh_api(f'repos/{repo}/releases/tags/{urllib.parse.unquote(tag)}', allow_missing=True)
    if not r:
        return None
    for a in r.get('assets', []):
        if a['name'] == urllib.parse.unquote(name):
            return asset_sha256(a)
    return None


def download(url, dest):
    """curl [url] to [dest]; returns its SHA-256."""
    subprocess.run(['curl', '-fsSL', '--retry', '5', '--retry-delay', '10', '-o', dest, url], check=True)
    h = hashlib.sha256()
    with open(dest, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()
