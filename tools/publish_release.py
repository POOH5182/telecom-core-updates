"""Publish a complete validated draft, then make it latest. Never clobber a release."""
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from telecom_updater import validate_package

ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not token:
            raise ValueError('Repository and scoped Actions token are required.')
        self.prefix = 'https://api.github.com/repos/' + repository
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, path, data=None, content_type=None):
        url = path if path.startswith('https://') else self.prefix + path
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'api.github.com', 'uploads.github.com'}:
            raise ValueError('Unexpected GitHub API host.')
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                   'User-Agent': 'Telecom-Core-Release'}
        if data is not None:
            if not isinstance(data, bytes):
                data = json.dumps(data).encode('utf-8')
                content_type = 'application/json'
            headers['Content-Type'] = content_type or 'application/octet-stream'
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=45) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            if method == 'GET' and exc.code == 404:
                return None
            # Do not emit token-bearing request headers or temporary upload URLs.
            detail = exc.read().decode('utf-8', errors='replace')[:1500]
            raise RuntimeError(f'GitHub {method} failed ({exc.code}): {detail}') from None


def release_number(release):
    match = re.fullmatch(r'v([0-9]+)', (release or {}).get('tag_name', ''))
    return int(match[1]) if match else 0


def matching_assets(release, expected):
    assets = {item['name']: item for item in release.get('assets', [])}
    return all(name in assets and assets[name].get('state') == 'uploaded'
               and assets[name].get('size') == len(data)
               and assets[name].get('digest') == 'sha256:' + hashlib.sha256(data).hexdigest()
               for name, data in expected.items())


def publish(api, manifest, expected, commit, notes):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('A full source commit SHA is required.')
    version = manifest['version']
    latest = api.request('GET', '/releases/latest')
    if release_number(latest) > version:
        print('A newer version is already published; leaving latest unchanged.')
        return latest
    tag = f'v{version}'
    release = api.request('GET', '/releases/tags/' + tag)
    if release and not release['draft']:
        if not matching_assets(release, expected):
            raise RuntimeError(f'{tag} already exists with different files. Increase the version; do not overwrite it.')
        print(f'{tag} is already published with the same verified assets.')
        return release
    metadata = {'tag_name': tag, 'target_commitish': commit, 'name': f'통신 코어 도면 V{version}',
                'body': notes, 'draft': True, 'prerelease': False, 'make_latest': 'false'}
    if release:
        release = api.request('PATCH', '/releases/' + str(release['id']), metadata)
    else:
        release = api.request('POST', '/releases', metadata)
    release_id = release['id']
    upload = release['upload_url'].split('{', 1)[0]
    old = {item['name']: item for item in release.get('assets', [])}
    for name, data in expected.items():
        asset = old.get(name)
        if asset and matching_assets({'assets': [asset]}, {name: data}):
            continue
        if asset:
            # A failed upload can leave a partial asset in our unpublished draft.
            api.request('DELETE', '/releases/assets/' + str(asset['id']))
        api.request('POST', upload + '?name=' + urllib.parse.quote(name, safe=''), data,
                    'application/json' if name.endswith('.json') else 'application/zip')
    verified = api.request('GET', '/releases/' + str(release_id))
    if not verified or not verified['draft'] or not matching_assets(verified, expected):
        raise RuntimeError('Uploaded assets did not verify; release remains a draft.')
    latest = api.request('GET', '/releases/latest')
    if release_number(latest) > version:
        print('A newer version appeared during upload; keeping this release as a draft.')
        return latest
    published = api.request('PATCH', '/releases/' + str(release_id),
                            {'draft': False, 'prerelease': False, 'make_latest': 'true'})
    if not published or published.get('draft') or not matching_assets(published, expected):
        raise RuntimeError('Release publication was not confirmed.')
    print('Published ' + published['html_url'])
    return published


def main():
    directory = ROOT / 'dist'
    manifest_bytes = (directory / 'latest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    archive = (directory / manifest['package']).read_bytes()
    validate_package(archive, manifest)
    api = GitHub(os.environ['GITHUB_REPOSITORY'], os.environ['GH_TOKEN'])
    release = publish(api, manifest, {manifest['package']: archive, 'latest.json': manifest_bytes},
                      os.environ['GITHUB_SHA'], (ROOT / 'RELEASE_NOTES.md').read_text(encoding='utf-8'))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as output:
            output.write(f"배포 확인: [{release['tag_name']}]({release['html_url']})\n")


if __name__ == '__main__':
    main()
