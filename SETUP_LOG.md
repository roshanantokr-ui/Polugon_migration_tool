# Setup log — Polygon Migration Tool (private notes)

Factual record of what was run, what happened, and what was changed during setup on 2026-10-29.
Use it for the submission email ("blockers, assumptions") and the PR description.
It intentionally contains no issue assessment or prioritisation.

Times are approximate local time (IST) unless marked UTC.

---

## 1. Environment found at start

| Component | Observed |
|---|---|
| OS / shell | Windows 11 Home, PowerShell 5.1 |
| Python | 3.13.0 64-bit (no `py` launcher on PATH). Spec v0.5 suggests 3.12; decision: use 3.13. |
| Git / VS Code / WSL | Git 2.55.0, VS Code 1.144.0, WSL 2.7.12 |
| Docker | Docker 29.7.2, Compose v5.4.0 — Docker Desktop engine was **not running**; started it |
| PostgreSQL | Native PostgreSQL 18 service already running on **5432**; `psql` not on PATH |
| Other Docker containers | `notes-postgres` on 5433, `jarves-db` on 5434, n8n stack — left untouched |
| Redis | Not installed |
| Starter project | Extracted at `Downloads\Polygon-migration-assignment\Polygon-migration-assignment\`; no `.gitignore`, no `.env`, no venv; not a git repo |

## 2. Local services and Python environment

| Step | Command / action | Result |
|---|---|---|
| Redis | `docker run --name polygon-redis -p 6379:6379 -d redis:7` | `redis-cli ping` → `PONG` |
| PostgreSQL (decision A: keep native PG18 untouched) | `docker run --name polygon-postgres -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=polygon_migration -p 5435:5432 -d postgres:15` | `pg_isready` → accepting connections |
| venv | `python -m venv .venv` (Python 3.13.0) | OK |
| Dependencies | `pip install -r ..\requirement.txt` | All pinned packages installed without errors on 3.13 |
| `.env` | Created from `.env.example`; `SECRET_KEY` generated into the file; `DB_PORT=5435`, `DB_HOST=127.0.0.1`, `REDIS_HOST=127.0.0.1`; Polygon values left blank for the user | OK |
| `.gitignore` | Added at repo root (`.env`, venv, logs, OAuth client JSON / token patterns) | OK |

## 3. Polygon

| Step | Result |
|---|---|
| Account / problem | Problem **id 618555**, name `two-sum-ranto`, statement title "Two Sum" (A + B), checker `std::ncmp.cpp`, `main.cpp` tagged Main correct, testlib validator |
| Validator page | "Select" dropdown was empty until a file was uploaded via "Or upload" / "New file" |
| Adding tests | Message "Added test has been reformatted because of the problem well-formed policy" on each add (line-ending/trailing-newline normalisation) |
| First invocation | Failed (red row) with `tests: 1 (all)`; fixed by the user (cause not recorded here) |
| API credentials | Both variables present (40 chars each); read-only `problems.list` → authenticated, 5 problems visible |
| Test inventory, first check | 4 tests, 2 samples; package rev 1 READY |
| Test inventory, after additions | 13 tests, samples = tests 1, 2, 5; first check showed `modified: True` (uncommitted) |
| After commit | Problem revision 2, no uncommitted changes, **standard package rev 2 READY** |

## 4. Storage provider decisions

1. Started with Azure Blob (starter default). The starter authenticates with `UsernamePasswordCredential`
   (`problems/AzureTestcase.py:35`), which Microsoft documents as work/school-account only and incompatible with MFA.
   User's Azure account is personal.
2. User switched to **Google Drive** (allowed by the brief). Decisions confirmed by the user:
   - OAuth scope `https://www.googleapis.com/auth/drive.file` (app sees only files it creates)
   - One app-wide Drive connection, token stored on the local machine, no DB schema change
   - Names follow the brief exactly, unpadded: `test_cases/{db_problem_id}/{n}` and `{n}.a`
     (starter Azure code used `{n:02d}`)
   - `{problem_id}` = database `Problem.id` (as in the starter's Azure path, `views.py` storage branch)
   - Re-migration: replace folder contents; previous files go to **Drive trash**, not permanent delete
   - Remove Azure code and dependencies after confirming nothing else imports them
3. Google OAuth client: type `web`, redirect URI `http://127.0.0.1:8000/google-drive/callback/`.
   Client JSON copied (not moved) to `C:\Users\Black Man\.polygon-migration\client_secret.json`
   (folder ACL restricted to the current Windows user). Token file: same folder, `google_drive_token.json`.

## 5. Code and configuration changes

| File | Change |
|---|---|
| `problems/storage/base.py` (new) | `TestCaseStorage` interface, `StorageFile`, `StorageError`, `StorageNotConfigured`, naming helpers `test_input_name` / `test_output_name` |
| `problems/storage/__init__.py` (new) | `get_storage()` selects provider from `STORAGE_PROVIDER` (supported: `gdrive`) |
| `problems/storage/google_oauth.py` (new) | OAuth web-server flow with PKCE; token load/refresh/atomic save; tokens never logged |
| `problems/storage/google_drive.py` (new) | Drive implementation: `test_cases/{id}/` folders; upload to `{id}.uploading`, rename to `{id}`, trash previous; on failure trash staging and keep previous |
| `problems/google_drive_views.py` (new) + `problems/templates/problems/google_drive.html` (new) | Staff-only `/google-drive/` status, `/connect/`, `/callback/`, `/disconnect/` |
| `problems/urls.py` | 4 routes added |
| `problems/polygon_api.py` | `upload_custom_checker_to_azure` + `migrate_to_azure_blob` replaced by `build_custom_checker_file`, `_checker_file_from_source`, `migrate_to_storage` (compile logic unchanged, duplicated branch merged) |
| `problems/views.py` | Storage branch uses `get_storage()` + `migrate_to_storage`; POST field `migrate_to_azure` → `migrate_to_storage`; the rollback path previously called `api.delete_azure_blob(...)`, a method not defined anywhere — replaced with a message stating uploaded files were left in place |
| `problems/templates/problems/index.html` | Button "Migrate Test Cases to Cloud Storage", loading text, navbar "Google Drive" link |
| `PolygonMigration/settings.py` | Azure settings removed; `STORAGE_PROVIDER`, `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`, `GOOGLE_DRIVE_TOKEN_FILE`, `GOOGLE_OAUTH_REDIRECT_URI`; `OAUTHLIB_INSECURE_TRANSPORT=1` only when `DEBUG=True` and redirect URI is 127.0.0.1/localhost |
| `.env.example` | Azure and unimplemented-provider placeholders replaced with Google Drive section (placeholders only) |
| `.env` | Only storage lines changed; Polygon lines verified byte-identical before/after |
| `requirement.txt` | Removed `azure-core`, `azure-identity`, `azure-storage-blob`, `msal`, `msal-extensions`, `PyJWT`, `isodate`, `six` (only used by Azure). Added Google API/OAuth packages pinned |
| `problems/AzureTestcase.py` | Deleted (only importer was `polygon_api.py`) |
| `problems/migrations/0002_problem_genie_chat_problem_notes.py` (new) | See §6 |
| `problems/tests.py` | 14 tests (naming, Drive replace/trash/failure behaviour with an in-memory fake, `migrate_to_storage`, OAuth routes) |

Notes:
- Upload errors now raise `StorageError` so the UI shows a failure (starter's Azure upload logged per-file errors and continued).
- Latest `google-api-core` (2.43.1) requires `requests>=2.33`; pinned `google-api-core==2.30.3` to keep the starter's `requests==2.32.4`. `pip check` clean; venv freeze identical to `requirement.txt`.
- Project files use CRLF line endings; new/edited files normalised to CRLF.

## 6. Errors encountered and how each was resolved

| # | Symptom (exact text abridged) | Cause found | Resolution |
|---|---|---|---|
| E1 | `docker info`: failed to connect to `dockerDesktopLinuxEngine` | Docker Desktop not running | Started Docker Desktop |
| E2 | `migrate`: `connection to server at "127.0.0.1", port 5435 failed: Connection refused` | Docker Desktop had stopped mid-session | Restarted Docker Desktop; `docker start polygon-postgres polygon-redis`; containers and data persisted |
| E3 | Fetch: `ProgrammingError … column problems_problem.notes does not exist` (`views.py:146`) | `Problem` model defines `notes` and `genie_chat`; `0001_initial` does not create them. `makemigrations --dry-run` showed only these two fields | Verified DB/connection/columns/0 rows first; generated `0002` (two `AddField`s, SQL reviewed with `sqlmigrate`); applied; `makemigrations --check` → no changes |
| E4 | Migrate to DB: `NameResolutionError … Failed to resolve 'polygon.codeforces.com' ([Errno 11001] getaddrinfo failed)` | Transient DNS failure on the local network | DB confirmed rolled back (0 rows); DNS and HTTPS to Polygon worked on re-check; retried successfully |
| E5 | `runserver`: `Error loading psycopg2 or psycopg module`, paths under `...\Python313\Lib\site-packages` | Command ran with system Python, venv not active | Run `.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000` (or activate venv with process-scoped execution policy bypass) |
| E6 | After adding tests in Polygon, app would still have served 4 tests | Fetched tests cached in Redis for 30 min under the Polygon ID | Cleared cache for 618555 after package rev 2 was READY |
| E7 | Google Drive token missing after first "connected" report | Connect step not completed at that time | User completed Connect; token file present (731 bytes) |

## 7. Verification results

| Check | Result |
|---|---|
| `manage.py check` | OK (only warning: `STATICFILES_DIRS` folder `static/` does not exist) |
| `manage.py test problems` | 14/14 passed |
| Polygon auth | `problems.list` OK |
| Fetch 618555 (after E3 fix) | HTTP 200, title "Two Sum", checker `ncmp`, legend/input/output present, previews shown |
| First end-to-end run (4 tests) | DB: Problem id 1, easy, tags `implementation`,`math`, 2 sample rows, 4 test rows. Drive `test_cases/1/`: `1,1.a … 4,4.a`; all 8 files byte-identical to Polygon |
| Demo reset (user-approved) | Problem id 1 deleted (cascade), Drive `test_cases/1` moved to trash, Redis cleared; tags and superuser kept. Next migration will be Problem id **2** → `test_cases/2/` |

## 8. Assumptions

- Local development only (`DEBUG=True`, plain-http OAuth redirect on 127.0.0.1).
- Google OAuth app in Testing mode; refresh tokens for test users expire after ~7 days → reconnect via `/google-drive/` if needed.
- Database problem ID is used for storage paths (stable while the `Problem` row exists).

## 9. Still to do

- [ ] Full 13-test run on camera; afterwards verify DB rows and all 26 Drive files in `test_cases/2/`
- [ ] Git: baseline commit from original ZIP, feature branch, private GitHub repo, PR description, collaborator `nalinabrol`
- [ ] `DOCUMENTATION.md` (candidate)
- [ ] `ISSUES.md` §3.1 and §3.2 (candidate)
- [ ] Submission email; fill in actual time spent: ______
