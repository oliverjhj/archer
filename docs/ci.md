# CI and deployment

Everything under `.github/`: what runs, when, and what it needs.

## CI - `workflows/ci.yml`

Runs on every push to `main` and every pull request. None of the four jobs
needs a `.env`, a database, IBM Cloud credentials or any secret.

| Job | What it does |
|---|---|
| `compile-and-validate` | Python 3.12 syntax check (`py_compile`), `pyproject.toml` and YAML validation |
| `unit-tests` | `pytest backend/tests/unit -m unit`, fully offline. See [testing](testing.md) |
| `frontend` | `npm ci`, then type check and production build on Node 20, matching the Dockerfile build stage |
| `docker-build` | Builds the image from `backend/Dockerfile`, without running it |

The evaluation suite isn't in CI, because it makes real model calls and needs
live credentials. See [evals](evals.md).

## Deployment - `workflows/deploy-code-engine.yml`

Runs when CI succeeds on a push to `main`, so a merge goes live without a
manual step and a commit that fails CI never does. It can also be run by hand
(`workflow_dispatch`) to redeploy without a new commit. Deploys run one at a
time, so a second merge waits for the first.

Each run:

1. Logs in to IBM Cloud with `IBM_CLOUD_API_KEY`.
2. Prunes the Container Registry namespace to its two newest images.
3. Builds the image at the commit CI tested and pushes it, tagged with the
   commit SHA and `latest`.
4. Points the existing Code Engine application at the new image.

Runtime configuration lives in a Code Engine secret, which the workflow never
reads or changes.

It needs the `IBM_CLOUD_API_KEY` repository secret, eight repository variables
listed at the top of the workflow file, and a GitHub environment named
`staging`. The IBM Cloud side is described in
[infrastructure](../infrastructure/README.md), and setting it all up from
scratch in [make your own](make-your-own.md#6-deploy-to-ibm-code-engine).

## Dependency updates - `dependabot.yml`

Dependabot checks three ecosystems weekly, on Monday mornings, grouping minor
and patch updates into one pull request each:

- Python dependencies in `backend/`.
- GitHub Actions versions.
- Docker base images in `backend/Dockerfile`. Major and minor updates to the
  `python` and `node` images are ignored: the Python version is changed only
  after the tests have been run against it, and the Node version is pinned so
  CI and the image build with the same one. Patch updates, which carry the
  security fixes, still come through.
