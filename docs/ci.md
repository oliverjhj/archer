# CI and automation

Everything under `.github/` - what runs, when, and what it needs.

## CI - `workflows/ci.yml`

Runs on every push to `main` and on every pull request. Four jobs, none of
which need a `.env`, a database, IBM Cloud credentials or any secret.

| Job | What it does |
|---|---|
| `compile-and-validate` | Python 3.12 syntax check (`py_compile`), `pyproject.toml` validation, YAML config validation. |
| `unit-tests` | `pytest backend/tests/unit -m unit` - 113 tests, fully offline. |
| `frontend` | `npm ci`, type check and production build of the React app on Node 20, matching the Dockerfile build stage. |
| `docker-build` | Builds the image from `backend/Dockerfile`. Does not run the container. |

The evaluation suite is deliberately not in CI: it makes real model calls and
needs live credentials. See [`evals.md`](evals.md).

## Deployment - `workflows/deploy-code-engine.yml`

Manual trigger (`workflow_dispatch`). Builds the image from the repository root,
pushes it to IBM Container Registry, and updates the IBM Code Engine application
to the new image. Runtime configuration and secrets live in Code Engine and are
not read or modified by the workflow.

Needs the `IBM_CLOUD_API_KEY` repository secret and the repository variables
listed at the top of the workflow file. Provisioning, scaling and cost are
covered in [`../infrastructure/README.md`](../infrastructure/README.md).

## Dependency updates - `dependabot.yml`

Dependabot checks three ecosystems weekly, on Monday mornings, grouping minor
and patch updates into one pull request each:

- Python dependencies in `backend/`.
- GitHub Actions versions.
- Docker base images in `backend/Dockerfile`. Major and minor bumps to the
  `python` and `node` images are ignored deliberately: the runtime version is a
  compatibility decision taken when the test suite has been run against it, and
  the Node version is pinned so that CI and the image agree on what produces
  the artefact. Patch updates still come through, which is where the security
  fixes are.
