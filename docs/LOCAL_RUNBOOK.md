# Local research application

The local application composes durable source execution, verified materials,
DeepSeek Generation V2, independent Qwen semantic validation, PostgreSQL/LangGraph
checkpoints, report review and approved export. Use the checked-out delivery branch and
its locked environment. This is a local research demonstration, not clinical
decision support or a public hosted service.

## Prepare a fresh checkout

The verified Windows setup uses PowerShell7.6 LTS, Python3.12.13 and uv0.11.32.
Install the locked development/retrieval groups before running all checks:

The snapshot volume must have at least **13 GiB free** when its storage writer is
initialized. Missing disk capacity fails closed rather than producing partial files.

```powershell
uv sync --locked --group dev --group retrieval
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Edit only the infrastructure values in `.env`, replacing `POSTGRES_PASSWORD` with
an actual local password. The application examples in `.env.example` are comments:
the strict Compose validator accepts only its infrastructure variables. Then:

```powershell
pwsh -NoLogo -NoProfile -File ./scripts/validate-environment.ps1 -EnvFile ./.env
pwsh -NoLogo -NoProfile -File ./scripts/validate-compose.ps1 -EnvFile ./.env
docker compose --env-file .env up -d --wait postgres
```

Qdrant is optional for the separate retrieval experiments; `docker compose --env-file
.env up -d --wait` starts both configured infrastructure services. Do not use
`docker compose down -v` on a database whose records must be retained.

Set the following **in the API terminal**, using the database/user/password/port
configured above. If a password contains URL-reserved characters, percent-encode it
in the PostgreSQL URL. These prompts avoid putting credentials in command history:

```powershell
$env:MEDEV_DATABASE_URL = Read-Host 'Loopback postgresql+psycopg URL' -MaskInput
$env:MEDEV_SNAPSHOT_ROOT = [System.IO.Path]::GetFullPath('.local/data/runtime')
$env:MEDEV_CODE_REVISION = git rev-parse HEAD
$env:MEDEV_QWEN_ENDPOINT = Read-Host 'Official Beijing workspace URL ending /compatible-mode/v1/chat/completions'
$env:DASHSCOPE_API_KEY = Read-Host 'Qwen API key' -MaskInput
$env:DEEPSEEK_API_KEY = Read-Host 'DeepSeek generation API key' -MaskInput
```

The Qwen key and fixed model must be available in the configured workspace. An
arbitrary proxy or generic replacement endpoint is not admitted by this profile.
Keep keys and the database URL out of the separate UI terminal. CADEC is optional;
set both absolute asset paths in the API terminal only when the exact approved
assets have been provisioned. The corpus and manifests are not bundled in Git.

## Configuration and startup

The application reads server-process environment variables only; it does not
load `.env` or a credential CSV automatically. `.env.example` has placeholders.

- `MEDEV_DATABASE_URL`: an explicitly selected loopback PostgreSQL database.
- `MEDEV_SNAPSHOT_ROOT`: absolute project `.local/data/` path for snapshots and receipts.
- `MEDEV_CODE_REVISION`: the actual `git rev-parse HEAD` of this checkout.
- `MEDEV_QWEN_ENDPOINT`: the Owner's Beijing workspace URL ending in `/compatible-mode/v1/chat/completions`.
- `DASHSCOPE_API_KEY`: Qwen credential, server-only.
- `DEEPSEEK_API_KEY`: existing independent report-generation credential.
- Optional paired `MEDEV_CADEC_ARCHIVE` and `MEDEV_CADEC_MANIFEST`: exact approved local assets (legacy or ADR-043 recovery profile). Missing assets produce a visible policy skip. CADEC references are metadata-only and cannot support medical claims.

With the environment set, prepare the selected application database and start API:

```powershell
$env:MEDEV_CODE_REVISION = git rev-parse HEAD
uv run --locked --no-sync alembic upgrade head
uv run --locked --no-sync python -m medevidence.local_api
```

In another terminal start the interface:

```powershell
uv run --locked --no-sync streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

Open <http://127.0.0.1:8501>. API listens on loopback port 8000. Source/model
requests begin only after an explicit research submission. Startup and MCP
discovery do not execute old submitted jobs. Do not point tests at the application
database or preserved provider-attempt ledger. Docker supplies infrastructure;
API/UI use the pinned Python environment.

The configured read-only MCP entry point uses the same environment:

```powershell
uv run --locked --no-sync python -m medevidence.local_mcp
```

The original `medevidence.mcp_server` remains the unconfigured discovery shell.
The optional `scripts/preview_api.py` still returns 503 for research submission;
it is not the configured application launcher.

## Research and review

Submit a bounded public research scope. Each source retains its own result,
coverage, failures and limitations. DailyMed uses current labels and rejects an
explicit historical date range. FAERS counts are descriptive reports only.

Reports stop at pending review. Inspect source coverage, citations and limitations
before approving or rejecting. Approval binds the exact report, rendered document,
destination and content hash. Download is available only after approved export.
Restarting with the same implementation resumes review without repeating source,
generation or semantic calls.
The first local-corpus verification after a restart is a cold read and may take
around 32 seconds on the measured machine. API reads are bounded to 90 seconds;
subsequent reads reuse metadata only after rechecking both asset hashes.

The application records actual Git HEAD plus hashes of runtime source, migrations
and locked configuration. Uncommitted code is represented by that manifest rather
than falsely attributed to HEAD alone. A run cannot resume under different
implementation bytes. Unknown provider outcomes are not automatically resent;
retain their receipts for diagnosis. A process retains at most 128 run adapters;
a restart releases them while preserving the PostgreSQL research records.

DailyMed's task material cap blocks the report with a typed failure rather than
presenting truncated material as complete. No raw CADEC corpus text is persisted
in report materials or sent to a model.

## Validation and evidence

```powershell
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync mypy src
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket
```

The real-factory integration test is
`tests/integration/infrastructure/test_local_runtime.py`. It uses an explicitly
disposable PostgreSQL database and simulated external HTTP, exercising public
submission, acquisition, generation, Qwen, restart, review and export, plus source
failure and no-evidence behavior. It is not live-source or clinical validation.

Raw evidence is under project-root `.local/evidence/V1-QWEN-DELIVERY-20260918/`.
The independent Qwen Development comparison is under
`.local/evidence/QWEN-COMPARISON-20260918-004/`: 33/36 agreement, all original
thresholds met. Runtime bytes and parsed answers were replayed against all 36
saved responses. Holdout-20 remains separate and unused for this delivery.
Development agreement is not a held-out score or complete V1 release certification.

## Updating and stopping

Stop API/UI with Ctrl+C in their respective terminals. Preserve database volumes and
snapshot directories. Before starting after a code update, set MEDEV_CODE_REVISION
from the new checkout and run alembic upgrade head. Keep the old checkout for runs
whose immutable implementation identity must be replayed. Outcome-occurrence schema
downgrade is refused if it would collapse existing records; see
[ADR-044](decisions/ADR-044-content-and-occurrence-identities.md).

See [delivery status](DELIVERY_STATUS.md) for evidence counts and validation limits.
