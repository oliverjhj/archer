# Infrastructure

Archer runs as a single container on IBM Code Engine, in the `eu-gb` region.
The deployment is a handful of resources and one workflow, so it is described
here instead of being kept as Terraform.

## What exists

| Resource | Name | Plan | Purpose |
|---|---|---|---|
| Code Engine project | `archer` | Standard | Hosts the application |
| Code Engine application | `archer` | - | The running service |
| Container Registry namespace | `archer` | Free | Stores the images |
| watsonx.ai Runtime | `archer-watsonx-runtime` | Essentials | Runs the model |
| watsonx.ai Studio | `archer-watsonx-studio` | Free | Required for the watsonx project |
| Cloud Object Storage | `archer-watsonx-storage` | Lite | Required as the watsonx project's storage |

Cloud Object Storage is there only because a watsonx project needs it. The
application reads its database from local disk and makes no storage calls.

watsonx.ai is on Essentials: pay per use, with no fixed monthly fee. The free
Lite plan stops at a monthly token allowance, which a few evaluation runs can
use up, and the live demo stops answering when it does.

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

Minimum scale is zero because the demo is idle most of the time. The first
request after a quiet period waits a few seconds for a container to start. The
dataset is generated into an early, cached image layer, which keeps the image
small and the start quick.

Maximum scale is 2, so a burst of traffic can't multiply the bill.

## Secrets

Two Code Engine secrets, neither of them in this repository:

- `archer-runtime` (generic) holds the runtime environment variables listed in
  [`.env.example`](../.env.example). The application receives it through
  `--env-from-secret`, so no value appears in the application definition, the
  workflow or the image.
- `icr-pull` (registry) lets Code Engine pull the private image.

## Deployment

Every merge to `main` deploys once CI passes. See [CI](../docs/ci.md) for the
steps and the GitHub secret and variables it needs.

## What it costs

| Service | Plan | Cost |
|---|---|---|
| Code Engine | Standard | £0.00 - inside the free allowance at this traffic |
| Container Registry | Free | £0.00 |
| watsonx.ai Runtime | Essentials | £0.01 per 89 Resource Units (about 89,000 tokens) |

Measured with the evaluation suite against the actual bill:

| Message | Input tokens (median) | Cost |
|---|---|---|
| Data question | about 3,500 | about £0.0004 |
| ... with a written summary | about 3,800 | about £0.0004 |
| ... with a corrected query | about 5,700 | about £0.0006 |
| Data-related chat | about 2,500 | about £0.0003 |
| Off-topic, declined | about 1,400 | about £0.00016 |

Most of a data question's tokens are the SQL generator's worked examples.

The daily ceiling counts messages, and each message is bounded: one planner
call and, for each of at most three parts, two SQL attempts and one summary. At
the default 200 messages a day, that caps spending at about 8p a day in typical
use, and about 35p if every message asked three questions and every query
needed correcting.

## Free-tier limits

- **Container Registry:** 512MB of storage and 5GB of pulls a month. Each image
  is about 130MB, and enough deploys fill the quota. Before each push, the
  deploy workflow runs `ibmcloud cr retention-run --images 2`, keeping the
  running image and one to roll back to. It applies to every repository in the
  namespace, so keep the namespace for this application alone. Deleted images
  stay in the registry trash for 30 days, outside the quota:

  ```bash
  ibmcloud cr images                            # list
  ibmcloud cr trash-list                        # deleted, restorable
  ibmcloud cr image-restore <image>:<old-sha>   # bring one back
  ```

  Publishing the image to `ghcr.io` instead would remove the quota, since
  public images there are free and unlimited, and take Container Registry out
  of the architecture.
- **Code Engine:** the free allowance covers this traffic comfortably. Heavier
  use would be billed per vCPU-second and GB-second while instances run.
