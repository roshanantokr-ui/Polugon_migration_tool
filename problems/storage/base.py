from abc import ABC, abstractmethod
from dataclasses import dataclass


class StorageError(Exception):
    """Raised when a storage provider operation fails."""


class StorageNotConfigured(StorageError):
    """Raised when the storage provider is missing configuration or authorization."""


@dataclass(frozen=True)
class StorageFile:
    """
    A single file to be stored under test_cases/{problem_id}/.

    Fields:
        name (str): The file name inside the problem folder, e.g. '1' or '1.a'.
        content (bytes): The raw file content.
        mime_type (str): The MIME type sent to the provider.
    """
    name: str
    content: bytes
    mime_type: str = 'text/plain'


def test_input_name(test_number):
    """
    Returns the storage file name for a test input: test_cases/{problem_id}/{test_number}.
    """
    return str(test_number)


def test_output_name(test_number):
    """
    Returns the storage file name for a test output: test_cases/{problem_id}/{test_number}.a.
    """
    return f"{test_number}.a"


class TestCaseStorage(ABC):
    """
    Provider-neutral interface for storing a problem's test-case files.

    Files are organised as test_cases/{problem_id}/{name}. Implementations decide
    how that path maps onto the provider (blob names, folders, keys, ...).
    """
    display_name = 'cloud storage'

    @abstractmethod
    def replace_problem_files(self, problem_id, files):
        """
        Makes test_cases/{problem_id}/ contain exactly `files`.

        Implementations must keep the previous files in place if the upload fails,
        and must remove files from the previous migration that are not in `files`.

        Args:
            problem_id (str|int): The database problem ID.
            files (list[StorageFile]): The complete new set of files.

        Raises:
            StorageError: If the files could not be stored.
        """

    @abstractmethod
    def list_problem_files(self, problem_id):
        """
        Returns the sorted file names currently stored for a problem.

        Args:
            problem_id (str|int): The database problem ID.

        Returns:
            list[str]: File names, or an empty list if nothing is stored.
        """

    @abstractmethod
    def read_problem_file(self, problem_id, name):
        """
        Returns the content of one stored file.

        Args:
            problem_id (str|int): The database problem ID.
            name (str): The file name inside the problem folder.

        Returns:
            bytes: The file content.

        Raises:
            StorageError: If the file does not exist or cannot be read.
        """
