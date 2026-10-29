import itertools
import os
import re
import tempfile
from unittest import mock

import httplib2
from django.test import SimpleTestCase, TestCase, override_settings
from googleapiclient.errors import HttpError

from problems.polygon_api import PolygonAPI
from problems.storage import StorageError, StorageFile, TestCaseStorage, test_input_name, test_output_name
from problems.storage.google_drive import FOLDER_MIME_TYPE, GoogleDriveStorage
from users.models import User


class _FakeRequest:
    def __init__(self, fn):
        self._fn = fn

    def execute(self, num_retries=0):
        return self._fn()


class FakeDrive:
    """
    Minimal in-memory stand-in for the Drive v3 `files()` resource, supporting the
    queries GoogleDriveStorage issues. `fail_on_upload` makes the Nth file upload fail.
    """

    def __init__(self):
        self.items = {}
        self._ids = itertools.count(1)
        self.uploads = 0
        self.fail_on_upload = None

    # --- helpers for tests ---
    def add(self, name, parent, folder=False, content=b''):
        item_id = f"id{next(self._ids)}"
        self.items[item_id] = {
            'id': item_id, 'name': name, 'parents': [parent], 'trashed': False,
            'mimeType': FOLDER_MIME_TYPE if folder else 'text/plain',
            'content': content, 'createdTime': item_id.zfill(10),
        }
        return item_id

    def live(self, parent, name=None):
        return [i for i in self.items.values()
                if parent in i['parents'] and not i['trashed'] and (name is None or i['name'] == name)]

    def tree(self, problem_id):
        root = self.live('root', 'test_cases')
        assert len(root) == 1, root
        folders = self.live(root[0]['id'], str(problem_id))
        assert len(folders) == 1, folders
        return {i['name']: i['content'] for i in self.live(folders[0]['id'])}

    # --- Drive API surface ---
    def files(self):
        return self

    def list(self, q, spaces=None, fields=None, orderBy=None, pageToken=None):
        parent = re.search(r"'([^']+)' in parents", q).group(1)
        name = re.search(r"name = '([^']+)'", q)
        folders_only = 'mimeType' in q

        def run():
            found = [i for i in self.live(parent, name.group(1) if name else None)
                     if not folders_only or i['mimeType'] == FOLDER_MIME_TYPE]
            found.sort(key=lambda i: i['createdTime'])
            return {'files': [{'id': i['id'], 'name': i['name'], 'createdTime': i['createdTime']} for i in found]}
        return _FakeRequest(run)

    def create(self, body, fields=None, media_body=None):
        def run():
            if media_body is not None:
                self.uploads += 1
                if self.fail_on_upload == self.uploads:
                    resp = httplib2.Response({'status': 500})
                    resp.reason = 'Backend Error'
                    raise HttpError(resp, b'{}')
                content = media_body.getbytes(0, media_body.size())
                return {'id': self.add(body['name'], body['parents'][0], content=content)}
            return {'id': self.add(body['name'], body['parents'][0], folder=True)}
        return _FakeRequest(run)

    def update(self, fileId, body, fields=None):
        def run():
            self.items[fileId].update(body)
            return {'id': fileId}
        return _FakeRequest(run)

    def get_media(self, fileId):
        return _FakeRequest(lambda: self.items[fileId]['content'])


def make_storage(drive):
    storage = GoogleDriveStorage.__new__(GoogleDriveStorage)
    storage._service = drive
    return storage


def test_files(count):
    files = []
    for n in range(1, count + 1):
        files.append(StorageFile(test_input_name(n), f"in {n}\n".encode()))
        files.append(StorageFile(test_output_name(n), f"out {n}\n".encode()))
    return files


class NamingTests(SimpleTestCase):
    def test_names_follow_brief_without_padding(self):
        self.assertEqual(test_input_name(1), '1')
        self.assertEqual(test_output_name(1), '1.a')
        self.assertEqual(test_input_name(12), '12')
        self.assertEqual(test_output_name(12), '12.a')


class GoogleDriveStorageTests(SimpleTestCase):
    def setUp(self):
        self.drive = FakeDrive()
        self.storage = make_storage(self.drive)

    def test_creates_folder_structure_and_files(self):
        self.storage.replace_problem_files(7, test_files(2))
        self.assertEqual(self.drive.tree(7), {'1': b'in 1\n', '1.a': b'out 1\n', '2': b'in 2\n', '2.a': b'out 2\n'})
        self.assertEqual(self.storage.list_problem_files(7), ['1', '1.a', '2', '2.a'])
        self.assertEqual(self.storage.read_problem_file(7, '2.a'), b'out 2\n')

    def test_repeat_upload_reuses_root_and_leaves_one_problem_folder(self):
        self.storage.replace_problem_files(7, test_files(2))
        self.storage.replace_problem_files(7, test_files(2))
        self.assertEqual(len(self.drive.live('root', 'test_cases')), 1)
        self.assertEqual(sorted(self.drive.tree(7)), ['1', '1.a', '2', '2.a'])

    def test_remigration_with_fewer_tests_removes_stale_files_via_trash(self):
        self.storage.replace_problem_files(7, test_files(20))
        self.storage.replace_problem_files(7, test_files(12))
        self.assertEqual(self.storage.list_problem_files(7), sorted(f.name for f in test_files(12)))
        trashed_folders = [i for i in self.drive.items.values() if i['trashed'] and i['mimeType'] == FOLDER_MIME_TYPE]
        self.assertEqual([f['name'] for f in trashed_folders], ['7'])

    def test_failed_upload_keeps_previous_files_and_trashes_staging(self):
        self.storage.replace_problem_files(7, test_files(3))
        self.drive.fail_on_upload = self.drive.uploads + 4
        with self.assertRaises(StorageError):
            self.storage.replace_problem_files(7, test_files(5))
        self.assertEqual(self.drive.tree(7), {f.name: f.content for f in test_files(3)})
        root_id = self.drive.live('root', 'test_cases')[0]['id']
        self.assertEqual(self.drive.live(root_id, '7.uploading'), [])

    def test_leftover_staging_folder_is_trashed(self):
        root_id = self.drive.add('test_cases', 'root', folder=True)
        leftover = self.drive.add('7.uploading', root_id, folder=True)
        self.storage.replace_problem_files(7, test_files(1))
        self.assertTrue(self.drive.items[leftover]['trashed'])

    def test_other_problems_and_unrelated_files_are_untouched(self):
        root_id = self.drive.add('test_cases', 'root', folder=True)
        other = self.drive.add('8', root_id, folder=True)
        other_file = self.drive.add('1', other, content=b'keep')
        unrelated = self.drive.add('notes.txt', 'root', content=b'keep')
        self.storage.replace_problem_files(7, test_files(1))
        self.storage.replace_problem_files(7, test_files(1))
        for item_id in (other, other_file, unrelated):
            self.assertFalse(self.drive.items[item_id]['trashed'])

    def test_read_missing_file_raises(self):
        self.storage.replace_problem_files(7, test_files(1))
        with self.assertRaises(StorageError):
            self.storage.read_problem_file(7, '9')


class RecordingStorage(TestCaseStorage):
    def __init__(self):
        self.calls = []

    def replace_problem_files(self, problem_id, files):
        self.calls.append((problem_id, list(files)))

    def list_problem_files(self, problem_id):
        return []

    def read_problem_file(self, problem_id, name):
        raise StorageError('not used')


class MigrateToStorageTests(SimpleTestCase):
    def test_builds_numbered_pairs_using_db_id_and_skips_incomplete_tests(self):
        tests = [
            {'input': '1 2\n', 'output': '3\n'},
            {'input': '', 'output': '0\n'},
            {'input': '5 7\n', 'output': '12\n'},
        ]
        api = PolygonAPI()
        storage = RecordingStorage()
        with mock.patch.object(api, 'get_test_cases_from_redis', return_value=tests), \
                mock.patch.object(api, 'build_custom_checker_file', return_value=None):
            uploaded = api.migrate_to_storage('618555', storage, db_problem_id=42)

        self.assertEqual(uploaded, 2)
        problem_id, files = storage.calls[0]
        self.assertEqual(problem_id, 42)
        # Test numbers follow the Polygon order, so the skipped test leaves a gap (as before).
        self.assertEqual({f.name: f.content for f in files},
                         {'1': b'1 2\n', '1.a': b'3\n', '3': b'5 7\n', '3.a': b'12\n'})

    def test_custom_checker_is_uploaded_with_tests(self):
        api = PolygonAPI()
        storage = RecordingStorage()
        checker = StorageFile('custom_checker.cpp', b'// checker')
        with mock.patch.object(api, 'get_test_cases_from_redis', return_value=[{'input': 'a', 'output': 'b'}]), \
                mock.patch.object(api, 'build_custom_checker_file', return_value=checker):
            api.migrate_to_storage('618555', storage, db_problem_id=42)
        self.assertIn(checker, storage.calls[0][1])


class GoogleDriveRouteTests(TestCase):
    def setUp(self):
        self.token_dir = tempfile.TemporaryDirectory()
        self.token_file = os.path.join(self.token_dir.name, 'token.json')
        self.staff = User.objects.create_user(
            email='staff@example.com', password='pw', username='staff', is_staff=True,
            first_name='S', last_name='T', contact_number='0', college='X',
        )

    def tearDown(self):
        self.token_dir.cleanup()

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get('/google-drive/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('/users/login/'))

    def test_callback_with_mismatched_state_stores_nothing(self):
        self.client.force_login(self.staff)
        session = self.client.session
        session['google_drive_oauth_state'] = 'expected'
        session['google_drive_oauth_code_verifier'] = 'v'
        session.save()
        with override_settings(GOOGLE_DRIVE_TOKEN_FILE=self.token_file):
            response = self.client.get('/google-drive/callback/?state=forged&code=abc')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(os.path.exists(self.token_file))

    def test_callback_error_from_google_is_reported(self):
        self.client.force_login(self.staff)
        with override_settings(GOOGLE_DRIVE_TOKEN_FILE=self.token_file):
            self.client.get('/google-drive/callback/?error=access_denied')
            response = self.client.get('/google-drive/')
        self.assertContains(response, 'access_denied')
        self.assertContains(response, 'Not connected')

    def test_connect_redirects_to_google_with_drive_file_scope(self):
        self.client.force_login(self.staff)
        response = self.client.post('/google-drive/connect/')
        self.assertEqual(response.status_code, 302)
        location = response['Location']
        self.assertTrue(location.startswith('https://accounts.google.com/'))
        self.assertIn('drive.file', location)
        self.assertIn('code_challenge_method=S256', location)
        self.assertIn('redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fgoogle-drive%2Fcallback%2F', location)
