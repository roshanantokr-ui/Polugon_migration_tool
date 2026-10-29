from django.conf import settings

from .base import (
    StorageError,
    StorageFile,
    StorageNotConfigured,
    TestCaseStorage,
    test_input_name,
    test_output_name,
)

SUPPORTED_PROVIDERS = ('gdrive',)


def get_storage():
    """
    Returns the TestCaseStorage implementation selected by settings.STORAGE_PROVIDER.

    Raises:
        StorageNotConfigured: If the provider is unknown or not yet authorized.
    """
    provider = (settings.STORAGE_PROVIDER or '').strip().lower()
    if provider == 'gdrive':
        from .google_drive import GoogleDriveStorage
        from .google_oauth import load_credentials
        return GoogleDriveStorage(load_credentials())
    raise StorageNotConfigured(
        f"Unsupported STORAGE_PROVIDER '{provider}'. Supported values: {', '.join(SUPPORTED_PROVIDERS)}."
    )
