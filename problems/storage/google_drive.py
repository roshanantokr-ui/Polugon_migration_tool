import io
import logging

from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from .base import StorageError, StorageNotConfigured, TestCaseStorage
from .google_oauth import CONNECT_HINT

logger = logging.getLogger(__name__)

FOLDER_MIME_TYPE = 'application/vnd.google-apps.folder'
ROOT_FOLDER_NAME = 'test_cases'
STAGING_SUFFIX = '.uploading'
NUM_RETRIES = 3


def _quote(value):
    """Escapes a value for use inside a single-quoted Drive query string."""
    return str(value).replace('\\', '\\\\').replace("'", "\\'")


class GoogleDriveStorage(TestCaseStorage):
    """
    Stores test cases in Google Drive as folders and files:

        My Drive/test_cases/{problem_id}/{test_number}     (input)
        My Drive/test_cases/{problem_id}/{test_number}.a   (output)

    Uses the drive.file scope, so it can only see folders and files it created.

    replace_problem_files() uploads into a staging folder ({problem_id}.uploading),
    then renames it to {problem_id} and moves the previous folder to Drive trash.
    If any upload fails, the staging folder is trashed and the previous files stay live.
    """
    display_name = 'Google Drive'

    def __init__(self, credentials):
        self._service = build('drive', 'v3', credentials=credentials, cache_discovery=False)

    def _execute(self, request, action):
        try:
            return request.execute(num_retries=NUM_RETRIES)
        except RefreshError:
            raise StorageNotConfigured(f"Google Drive authorization has expired or was revoked. {CONNECT_HINT}")
        except HttpError as e:
            raise StorageError(f"Google Drive could not {action} (HTTP {e.status_code}: {e.reason}).")

    def _find(self, parent_id, name, folders_only):
        query = [f"'{_quote(parent_id)}' in parents", "trashed = false", f"name = '{_quote(name)}'"]
        if folders_only:
            query.append(f"mimeType = '{FOLDER_MIME_TYPE}'")
        found, page_token = [], None
        while True:
            response = self._execute(
                self._service.files().list(
                    q=' and '.join(query),
                    spaces='drive',
                    fields='nextPageToken, files(id, name, createdTime)',
                    orderBy='createdTime',
                    pageToken=page_token,
                ),
                f"look up '{name}'",
            )
            found.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            if not page_token:
                return found

    def _list_children(self, folder_id):
        children, page_token = [], None
        while True:
            response = self._execute(
                self._service.files().list(
                    q=f"'{_quote(folder_id)}' in parents and trashed = false",
                    spaces='drive',
                    fields='nextPageToken, files(id, name)',
                    pageToken=page_token,
                ),
                'list folder contents',
            )
            children.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            if not page_token:
                return children

    def _create_folder(self, parent_id, name):
        folder = self._execute(
            self._service.files().create(
                body={'name': name, 'mimeType': FOLDER_MIME_TYPE, 'parents': [parent_id]},
                fields='id',
            ),
            f"create folder '{name}'",
        )
        logger.info("Created Drive folder %s", name)
        return folder['id']

    def _get_or_create_folder(self, parent_id, name):
        existing = self._find(parent_id, name, folders_only=True)
        if existing:
            # Oldest first, so repeated runs keep reusing the same folder.
            return existing[0]['id']
        return self._create_folder(parent_id, name)

    def _root_folder_id(self, create):
        if create:
            return self._get_or_create_folder('root', ROOT_FOLDER_NAME)
        existing = self._find('root', ROOT_FOLDER_NAME, folders_only=True)
        return existing[0]['id'] if existing else None

    def _trash(self, file_id, label):
        self._execute(
            self._service.files().update(fileId=file_id, body={'trashed': True}, fields='id'),
            f"move '{label}' to trash",
        )
        logger.info("Moved Drive item %s to trash", label)

    def _upload(self, folder_id, storage_file):
        media = MediaIoBaseUpload(io.BytesIO(storage_file.content), mimetype=storage_file.mime_type, resumable=False)
        self._execute(
            self._service.files().create(
                body={'name': storage_file.name, 'parents': [folder_id]},
                media_body=media,
                fields='id',
            ),
            f"upload '{storage_file.name}'",
        )

    def replace_problem_files(self, problem_id, files):
        problem_folder_name = str(problem_id)
        staging_name = f"{problem_folder_name}{STAGING_SUFFIX}"
        root_id = self._root_folder_id(create=True)

        # Leftovers from an interrupted run are never live data.
        for leftover in self._find(root_id, staging_name, folders_only=True):
            self._trash(leftover['id'], f"{ROOT_FOLDER_NAME}/{staging_name}")

        previous = self._find(root_id, problem_folder_name, folders_only=True)
        staging_id = self._create_folder(root_id, staging_name)
        try:
            for storage_file in files:
                self._upload(staging_id, storage_file)
        except Exception:
            logger.error("Upload to %s/%s failed; previous files left untouched", ROOT_FOLDER_NAME, staging_name)
            try:
                self._trash(staging_id, f"{ROOT_FOLDER_NAME}/{staging_name}")
            except StorageError as cleanup_error:
                logger.error("Could not trash staging folder: %s", cleanup_error)
            raise
        logger.info("Uploaded %d files to %s/%s", len(files), ROOT_FOLDER_NAME, staging_name)

        self._execute(
            self._service.files().update(fileId=staging_id, body={'name': problem_folder_name}, fields='id'),
            f"rename '{staging_name}' to '{problem_folder_name}'",
        )
        for folder in previous:
            try:
                self._trash(folder['id'], f"{ROOT_FOLDER_NAME}/{problem_folder_name} (previous)")
            except StorageError as e:
                raise StorageError(
                    f"New files are live in {ROOT_FOLDER_NAME}/{problem_folder_name}, but the previous folder could "
                    f"not be moved to trash, so Drive temporarily shows two '{problem_folder_name}' folders. "
                    f"Re-running the upload will clean it up. Details: {e}"
                )

    def _problem_folder_id(self, problem_id):
        root_id = self._root_folder_id(create=False)
        if not root_id:
            return None
        folders = self._find(root_id, str(problem_id), folders_only=True)
        # After a successful replace there is exactly one; prefer the newest otherwise.
        return folders[-1]['id'] if folders else None

    def list_problem_files(self, problem_id):
        folder_id = self._problem_folder_id(problem_id)
        if not folder_id:
            return []
        return sorted(item['name'] for item in self._list_children(folder_id))

    def read_problem_file(self, problem_id, name):
        folder_id = self._problem_folder_id(problem_id)
        if not folder_id:
            raise StorageError(f"No folder {ROOT_FOLDER_NAME}/{problem_id} in Google Drive.")
        matches = self._find(folder_id, name, folders_only=False)
        if not matches:
            raise StorageError(f"File {ROOT_FOLDER_NAME}/{problem_id}/{name} not found in Google Drive.")
        return self._execute(self._service.files().get_media(fileId=matches[0]['id']), f"download '{name}'")
