# Infrastructure

Archer runs as a single container on IBM Code Engine, in `eu-gb`. There is no
infrastructure-as-code here by choice: the whole deployment is four resources
and one workflow, and a Terraform layer over that would be more to maintain
than it removes. This file is the description instead.

## What exists

| Resource | Name | Plan | Purpose |
|---|---|---|---|
| Code Engine project | `archer` | standard | Hosts the application |
| Code Engine application | `archer` | - | The running service |
| Container Registry namespace | `archer` | free | Stores the image |
| watsonx.ai Runtime | `archer-watsonx-runtime` | lite | The model |
| watsonx.ai Studio | `archer-watsonx-studio` | free-v1 | Required for the watsonx project |
| Cloud Object Storage | `archer-watsonx-storage` | lite | Required as watsonx project storage |

Everything except Code Engine is on a free plan. **Object Storage is a
prerequisite of a watsonx project, not a dependency of the application** - the
container reads its database from local disk and makes no object storage calls.
That was a deliberate change; see `backend/Dockerfile` and
`scripts/generate_dataset.py`.

## Application configuration

```text
CPU              0.5 vCPU
Memory           1G
Port             8080
Minimum scale    0     (scales to zero when idle)
Maximum scale    2
Image            private.uk.icr.io/archer/archer-backend:<commit sha>
Registry secret  icr-pull
Runtime secret   archer-runtime  (env-from-secret)
```

**Minimum scale is zero deliberately.** The demo is idle almost all of the
time, so an always-warm instance would be paying for nothing. The cost is a
cold start on the first request after a quiet period. That trade is what makes
image size worth caring about, and it is why the dataset is generated into a
cached layer rather than downloaded at startup or copied in after the
application source.

Maximum scale is capped at 2 so that a burst of traffic - or someone pointing a
load generator at a public demo - cannot scale the bill.

## Secrets

Two Code Engine secrets, neither of which is in this repository:

- **`archer-runtime`** (generic) - the eight runtime environment variables. See
  `.env.example` for the names.
- **`icr-pull`** (registry) - lets Code Engine pull the private image.

The application receives the runtime secret via `--env-from-secret`, so no
secret value appears in the application definition, the workflow, or the image.

## Deployment

`.github/workflows/deploy-code-engine.yml` runs automatically after CI passes
on a push to `main`, so every merge goes live; it can also be run manually
(`workflow_dispatch`) to redeploy without a new commit. It clears superseded
images from the registry, builds the image, pushes it to IBM Container
Registry, and updates the Code Engine application to the new tag.

Required GitHub secret: `IBM_CLOUD_API_KEY`.

Required GitHub variables: `IBM_CLOUD_REGION`, `IBM_CLOUD_RESOURCE_GROUP`,
`IBM_CODE_ENGINE_PROJECT`, `IBM_CODE_ENGINE_APP`,
`IBM_CONTAINER_REGISTRY_NAMESPACE`, `IBM_CONTAINER_REGISTRY_HOSTNAME`,
`IBM_CODE_ENGINE_IMAGE_HOSTNAME`, `IBM_CODE_ENGINE_REGISTRY_SECRET`.

## Not IBM-locked

Nothing about the application requires Code Engine. It is a single container
listening on `$PORT`, with no persistent state and no cloud SDK in the runtime
path, so it runs unchanged on Fly.io, Render, Cloud Run or any container host.
The only genuine IBM dependency is watsonx.ai, which is the point of the
project rather than an accident of hosting.

## What it costs

Measured, not estimated:

| Service | Plan | Cost |
|---|---|---|
| Code Engine | Standard | £0.00 - inside the free allowance at this traffic |
| Container Registry | Free | £0.00 |
| watsonx.ai Runtime | Essentials | **£0.01 per 89 Resource Units** |

That puts a question at roughly **£0.00026**, and the 200-question daily
ceiling at about **5p a day** even if the demo is hammered. It is why an
approximate per-process counter is an adequate control rather than a
compromise.

**watsonx.ai started on the Lite plan and had to move.** Lite is genuinely
free and fails safe - it returns `token_quota_reached` rather than billing -
but four evaluation runs exhausted a month's allowance in a single afternoon,
and took the live demo down with them. Lite is fine for experimenting and not
enough for anything public. Essentials was chosen over Standard and
Professional because it has no fixed monthly fee.

## Free-tier limits worth knowing

- **Container Registry:** 512MB storage, 5GB pull traffic per month. Each
  deploy pushes a new SHA-tagged image at roughly 130MB, and although layers
  are shared, **this quota does fill** - a deploy has already failed on it.
  The deploy workflow now keeps only the two newest images, the running one
  and one to roll back to, by running `ibmcloud cr retention-run --images 2`
  before each push. That applies to every repository in the namespace, which
  is safe only while the `archer` namespace holds this application alone.
  Deleted images stay in the registry trash for 30 days, outside the quota:

  ```bash
  ibmcloud cr images                            # list
  ibmcloud cr trash-list                        # deleted, restorable
  ibmcloud cr image-restore <image>:<old-sha>   # bring one back
  ```

  The permanent fix is moving to `ghcr.io`, which is free and unlimited for
  public images. That was not possible while the repository was private,
  because a private image would have needed Code Engine to hold a long-lived
  GitHub token. Now that the repository is public it is straightforward, and it
  would remove Container Registry from the architecture entirely.
