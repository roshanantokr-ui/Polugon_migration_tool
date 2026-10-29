import logging

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .storage import StorageError
from .storage import google_oauth

logger = logging.getLogger(__name__)

staff_required = user_passes_test(lambda u: u.is_authenticated and u.is_staff, login_url='/users/login/')

SESSION_STATE_KEY = 'google_drive_oauth_state'
SESSION_VERIFIER_KEY = 'google_drive_oauth_code_verifier'
SESSION_MESSAGE_KEY = 'google_drive_message'


def _flash(request, level, text):
    request.session[SESSION_MESSAGE_KEY] = {'level': level, 'text': text}


@staff_required
@require_GET
def google_drive_status(request):
    """
    Shows whether Google Drive is connected and offers connect/disconnect actions.
    """
    context = {
        'connected': google_oauth.is_connected(),
        'redirect_uri': settings.GOOGLE_OAUTH_REDIRECT_URI,
        'message': request.session.pop(SESSION_MESSAGE_KEY, None),
    }
    return render(request, 'problems/google_drive.html', context)


@staff_required
@require_POST
def google_drive_connect(request):
    """
    Starts the OAuth flow and redirects the staff user to Google's consent screen.
    """
    try:
        url, state, code_verifier = google_oauth.build_authorization_url()
    except StorageError as e:
        _flash(request, 'danger', str(e))
        return redirect('problems:google_drive_status')
    request.session[SESSION_STATE_KEY] = state
    request.session[SESSION_VERIFIER_KEY] = code_verifier
    return redirect(url)


@staff_required
@require_GET
def google_drive_callback(request):
    """
    OAuth redirect URI (GOOGLE_OAUTH_REDIRECT_URI). Exchanges the code and stores the token.
    """
    state = request.session.pop(SESSION_STATE_KEY, None)
    code_verifier = request.session.pop(SESSION_VERIFIER_KEY, None)

    if request.GET.get('error'):
        _flash(request, 'warning', f"Google Drive was not connected: {request.GET['error']}.")
        return redirect('problems:google_drive_status')
    if not state or request.GET.get('state') != state:
        _flash(request, 'danger', "Google Drive connection failed: the sign-in request expired or did not "
                                  "match. Use 127.0.0.1 (not localhost) and try again.")
        return redirect('problems:google_drive_status')

    try:
        google_oauth.exchange_code(request.build_absolute_uri(), state, code_verifier)
    except Exception as e:
        # The exception text from oauthlib does not contain tokens; log the type only to be safe.
        logger.error("Google OAuth code exchange failed: %s", type(e).__name__)
        _flash(request, 'danger', f"Google Drive connection failed ({type(e).__name__}). Please try again.")
        return redirect('problems:google_drive_status')

    _flash(request, 'success', "Google Drive connected.")
    return redirect('problems:google_drive_status')


@staff_required
@require_POST
def google_drive_disconnect(request):
    """
    Removes the locally stored token.
    """
    try:
        google_oauth.disconnect()
        _flash(request, 'info', "Google Drive disconnected on this machine. To revoke access completely, "
                                "remove the app at https://myaccount.google.com/permissions.")
    except StorageError as e:
        _flash(request, 'danger', str(e))
    return redirect('problems:google_drive_status')
