import copy
import hashlib
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from publish_release import GitHubRequestError, publish, publish_with_retry


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.release = None
        self.latest = {'tag_name': 'v48', 'html_url': 'https://github.com/example/repo/releases/tag/v48'}
        self.fail_upload = False
        self.corrupt_digest = False

    def request(self, method, path, data=None, content_type=None):
        self.calls.append((method, path, data))
        if method == 'GET':
            if path == '/releases/latest':return copy.deepcopy(self.latest)
            return copy.deepcopy(self.release)
        if method == 'POST' and path == '/releases':
            assert data['draft'] is True
            self.release = dict(data, id=1, assets=[], upload_url='https://uploads.github.com/repos/example/repo/releases/1/assets{?name,label}',
                                html_url='https://github.com/example/repo/releases/tag/v49')
        elif method == 'POST':
            if self.fail_upload:raise RuntimeError('Simulated network failure')
            name = parse_qs(urlsplit(path).query)['name'][0]
            self.release['assets'].append({'id': len(self.release['assets']) + 10, 'name': name, 'state': 'uploaded',
                                          'size': len(data), 'digest': 'bad' if self.corrupt_digest else 'sha256:' + hashlib.sha256(data).hexdigest()})
        elif method == 'PATCH':
            self.release.update(data)
            if data.get('draft') is False:self.latest = copy.deepcopy(self.release)
        elif method == 'DELETE':
            self.release['assets'] = [a for a in self.release['assets'] if a['id'] != int(path.rsplit('/', 1)[1])]
        return copy.deepcopy(self.release)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.files = {'telecom_core_update_v49.zip': b'zip', 'latest.json': b'manifest'}

    def run_publish(self):
        return publish(self.api, {'version': 49}, self.files, 'a' * 40, 'LOT NO.')

    def test_upload_both_before_publish(self):
        result = self.run_publish()
        self.assertFalse(result['draft'])
        self.assertEqual({a['name'] for a in result['assets']}, set(self.files))
        self.assertEqual(self.api.calls[-1][2]['make_latest'], 'true')
        writes = len([c for c in self.api.calls if c[0] != 'GET'])
        self.run_publish()
        self.assertEqual(writes, len([c for c in self.api.calls if c[0] != 'GET']))

    def test_failed_upload_never_publishes_and_retry_resumes(self):
        self.api.fail_upload = True
        with self.assertRaises(RuntimeError):self.run_publish()
        self.assertTrue(self.api.release['draft'])
        self.assertEqual(self.api.latest['tag_name'], 'v48')
        self.api.fail_upload = False
        self.assertFalse(self.run_publish()['draft'])

    def test_mismatched_upload_never_publishes(self):
        self.api.corrupt_digest = True
        with self.assertRaises(RuntimeError):self.run_publish()
        self.assertTrue(self.api.release['draft'])
        self.assertEqual(self.api.latest['tag_name'], 'v48')

    def test_changed_published_version_is_not_overwritten(self):
        self.run_publish()
        self.files['latest.json'] = b'different'
        count = len(self.api.calls)
        with self.assertRaises(RuntimeError):self.run_publish()
        self.assertTrue(all(c[0] == 'GET' for c in self.api.calls[count:]))

    def test_newer_version_is_not_downgraded(self):
        self.api.latest['tag_name'] = 'v50'
        self.assertEqual(self.run_publish()['tag_name'], 'v50')
        self.assertTrue(all(c[0] == 'GET' for c in self.api.calls))

    def test_transient_upload_reconciles_accepted_and_partial_assets(self):
        base = self.api.request
        failed = set()
        delays = []
        def flaky(method, path, data=None, content_type=None):
            if method == 'POST' and '?name=' in path:
                name = parse_qs(urlsplit(path).query)['name'][0]
                if name not in failed:
                    failed.add(name)
                    if name.endswith('.zip'):
                        base(method, path, data, content_type)
                        raise GitHubRequestError(method, 502, 'Simulated lost upload acknowledgement')
                    self.api.release['assets'].append({'id': 99, 'name': name, 'state': 'starter', 'size': 0})
                    raise GitHubRequestError(method, 500, 'Simulated partial upload')
            return base(method, path, data, content_type)
        with patch.object(self.api, 'request', side_effect=flaky):
            result = publish_with_retry(self.api, {'version': 49}, self.files, 'a' * 40, 'LOT NO.', sleep=delays.append)
        self.assertEqual(delays, [5, 15])
        self.assertFalse(result['draft'])
        self.assertEqual(len(result['assets']), 2)
        uploads = [c for c in self.api.calls if c[0] == 'POST' and '?name=' in c[1]]
        self.assertEqual(len(uploads), 2)
        self.assertTrue(any(c[:2] == ('DELETE', '/releases/assets/99') for c in self.api.calls))

    def test_transient_retry_is_bounded_and_keeps_draft_unpublished(self):
        base = self.api.request
        delays = []
        def unavailable(method, path, data=None, content_type=None):
            if method == 'POST' and '?name=' in path:raise GitHubRequestError(method, 503, 'Simulated unavailable')
            return base(method, path, data, content_type)
        with patch.object(self.api, 'request', side_effect=unavailable), self.assertRaises(GitHubRequestError):
            publish_with_retry(self.api, {'version': 49}, self.files, 'a' * 40, 'LOT NO.', sleep=delays.append)
        self.assertEqual(delays, [5, 15, 30, 45])
        self.assertTrue(self.api.release['draft'])
        self.assertEqual(self.api.latest['tag_name'], 'v48')

    def test_retry_does_not_bypass_permission_or_asset_verification_failure(self):
        delays = []
        with patch.object(self.api, 'request', side_effect=GitHubRequestError('GET', 403, 'Simulated forbidden')), self.assertRaises(GitHubRequestError):
            publish_with_retry(self.api, {'version': 49}, self.files, 'a' * 40, 'LOT NO.', sleep=delays.append)
        self.assertEqual(delays, [])
        self.api.corrupt_digest = True
        with self.assertRaises(RuntimeError):
            publish_with_retry(self.api, {'version': 49}, self.files, 'a' * 40, 'LOT NO.', sleep=delays.append)
        self.assertEqual(delays, [])
        self.assertTrue(self.api.release['draft'])


if __name__ == '__main__':
    unittest.main()
