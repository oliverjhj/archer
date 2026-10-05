# Make your own

How to fork Archer, point it at your own data and run it on your own IBM Cloud
account. Expect an afternoon for a first version running locally, most of it
rewriting the SQL prompt for your data.

1. [Fork and run it as it is](#1-fork-and-run-it-as-it-is)
2. [Set up watsonx.ai](#2-set-up-watsonxai)
3. [Use your own data](#3-use-your-own-data)
4. [Adapt the prompts](#4-adapt-the-prompts)
5. [Rewrite the evaluation cases](#5-rewrite-the-evaluation-cases)
6. [Deploy to IBM Code Engine](#6-deploy-to-ibm-code-engine)
7. [Before you share it](#7-before-you-share-it)

## 1. Fork and run it as it is

Fork the repository on GitHub, clone your fork, and get the original running
before changing anything. Then any later problem is in your changes.

You need Python 3.12, Node 20 and, for step 6, Docker and the
[IBM Cloud CLI](https://cloud.ibm.com/docs/cli).

```bash
git clone https://github.com/<you>/archer.git
cd archer
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e "backend[test]"
python scripts/generate_dataset.py
cp .env.example .env
npm --prefix frontend install
npm --prefix frontend run build
.venv/Scripts/python.exe -m pytest backend/tests/unit -m unit -q
```

The tests run offline and should all pass. To answer questions, `.env` needs
the watsonx.ai values from the next step.

## 2. Set up watsonx.ai

1. Create an [IBM Cloud account](https://cloud.ibm.com/registration).
2. Create a **watsonx.ai Runtime** service. Choose a region (Archer uses
   London, `eu-gb`) and the **Essentials** plan: pay per use, with no monthly
   fee. The free Lite plan works for trying things out, but it stops at a
   monthly token allowance that a few evaluation runs can use up.
3. Open watsonx.ai in the same region and create a **project**. It asks for a
   Cloud Object Storage instance, which the Lite plan covers. Archer never
   reads from it.
4. In the project's **Manage** tab, under **Services and integrations**,
   associate the Runtime service from step 2. On the **General** page, copy the
   **project ID**.
5. Create an API key under **Manage > Access (IAM) > API keys**. For anything
   long-lived, create a service ID with access to the project and give it the
   key, so it isn't tied to your own login.
6. Fill in `.env`:

   ```bash
   IBM_API_KEY=<the API key>
   PROJECT_ID=<the project ID>
   WATSONX_URL=https://eu-gb.ml.cloud.ibm.com     # your region's endpoint
   WEB_USERNAME=<a login name>
   WEB_PASSWORD=<a password>
   JWT_SECRET_KEY=<32+ random characters>
   CSRF_SECRET_KEY=<32+ random characters>
   WEBHOOK_SECRET=<random characters>
   DEMO_DAILY_QUESTION_LIMIT=0                    # no ceiling locally
   ```

   Generate each secret with
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
7. Start it and sign in at <http://localhost:8080>:

   ```bash
   .venv/Scripts/python.exe -m uvicorn main:app --app-dir backend --port 8080
   ```

The default model is Mistral Small 3.1. To try another from the watsonx.ai
catalogue, set `WATSONX_MODEL_ID`, or `WATSONX_MODEL_ID_PLANNER`, `_SQL`,
`_CHAT` or `_SUMMARY` for one step. Measure any change with the evaluation
suite (step 5).

## 3. Use your own data

Archer queries one table in one SQLite file. If your data is elsewhere, export
the table you want to ask about into SQLite first.

**Point Archer at it:**

- Put the file in the repository root and set `DB_FILE_NAME` in `.env`.
- Set `TABLE_NAME` in `backend/archer/db/database.py` to your table's name.
  The startup check, the schema shown in the app, the date range and the query
  authorizer all use it. The authorizer refuses every other table in the file.
- The date range comes from a `document_date` column, in `database.py` and
  `backend/archer/api/schema_routes.py`. Change it to your date column.

**Describe your columns** in `backend/archer/db/catalogue.py`:

- `COLUMN_DESCRIPTIONS`: one plain-English line per column. The in-app guide
  shows them and the chat prompt's glossary is built from them.
- `COMMON_COLUMNS`: the columns a plain "show me" question returns. Keep it to
  about eight.
- `KNOWN_VALUES`: columns with a small fixed set of values, shown in the guide.

**Update the domain wording in the code:**

- `backend/archer/ai/chat.py`, `_VOCABULARY`: your domain's terms.
- `backend/archer/pipeline.py`:
  - `DECLINE_MESSAGE`, the reply to off-topic requests, names what the data
    covers.
  - `format_cell` and `format_scalar` add a £ to any column whose name contains
    "revenue" and show "quantity" columns as whole numbers. Change them for
    your currency and columns.
  - `_worth_summarising` skips summaries for tables with a `document_number`
    column, which are lists of deal lines. Use your equivalent, or remove it.
- `frontend/src/lib/examples.ts`: the example questions on the empty screen.
  Use ones your evaluation cases cover.
- `frontend/src/components/pages/HowToUse.tsx` and the placeholder in
  `AskInput.tsx`: the help text.

**Build it into the image.** The Dockerfile generates the sample dataset at
build time (`backend/Dockerfile`, the `generate_dataset.py` step). Replace that
step with a `COPY` of your database into `/app`, and remove `*.db` from
`.dockerignore` so Docker can see it. Keep your database out of a public
repository if it holds anything you wouldn't publish, and copy it into the
image at deploy time instead.

**Two tests check the sample dataset** and will fail until you update them:
`backend/tests/unit/test_schema_routes.py` checks that `COLUMN_DESCRIPTIONS`
matches the generated schema, and that the SQL prompt's default columns match
`COMMON_COLUMNS`. Point the first at your schema and keep the second.

## 4. Adapt the prompts

The prompts are in `prompts/`. [Prompts](prompts.md) explains each in detail.

| Prompt | What to change |
|---|---|
| `sql_generator.md` | Almost everything. The table name, the default columns (rule 1, matching `COMMON_COLUMNS`), the vocabulary mapping (rule 2), the column values (rule 3), any counting rules your data needs (rules 4 and 4b), and all fifteen examples, rewritten as real questions about your data with correct SQL |
| `planner.md` | The domain description at the top of the system message, the vocabulary it lists, and the example exchanges, which use the sample dataset's company names |
| `chat.md` | The "sales data assistant" description and the fixed answer to "what can you do" |
| `sql_retry.md` | Nothing, usually. Its hints are generic |
| `summary.md` | The currency instruction, if you don't use pounds |

The SQL prompt matters most. Three things gave the largest gains here:

- **List the values inside columns, not just the column names.** A model that
  doesn't know a flag holds `'Yes'` will guess `'Y'`.
- **Write down what a business word means in SQL.** If an order spans several
  rows, say that "how many orders" means `COUNT(DISTINCT order_id)`.
- **Give a default for every ambiguous word.** If "customer" could mean two
  columns, say which.

Bump the `version` in a prompt's front matter whenever you change it, so
evaluation results can be traced to prompt versions.

## 5. Rewrite the evaluation cases

Without evaluation cases you have no measure of whether your prompts work.
Replace `evals/cases.yaml` with cases for your data. Its header documents every
field. Each data case needs a question and a reference SQL query that you have
checked by hand.

Cover each kind of question your users will ask: totals, counts, rankings,
filters, "is there a...", follow-ups, and a few things that should be
declined. Then write five or so hold-out cases and never change a prompt to
fix them, so you have one honest measure.

```bash
python evals/run_evals.py                     # all cases
python evals/run_evals.py --only <case-id>    # one case, while fixing a prompt
```

A run of about 60 cases costs a few pence on Essentials. See
[evals](evals.md) for how grading works.

## 6. Deploy to IBM Code Engine

Archer's deployment uses Code Engine to run the container and Container
Registry to store images. Set it up once by hand, then let GitHub Actions
deploy every merge. These commands use London; substitute your region.

**1. Log in and install the plugins:**

```bash
ibmcloud login -r eu-gb
ibmcloud target -g Default
ibmcloud plugin install code-engine container-registry
```

**2. Create a registry namespace and push a first image:**

```bash
ibmcloud cr region-set uk-south
ibmcloud cr namespace-add <namespace>
ibmcloud cr login
docker build -f backend/Dockerfile -t uk.icr.io/<namespace>/archer-backend:first .
docker push uk.icr.io/<namespace>/archer-backend:first
```

**3. Create the Code Engine project, its secrets and the application:**

```bash
ibmcloud ce project create --name <project>
ibmcloud ce secret create --name archer-runtime --from-env-file .env
ibmcloud ce registry create --name icr-pull --server private.uk.icr.io \
  --username iamapikey --password <API key>
ibmcloud ce application create --name <app> \
  --image private.uk.icr.io/<namespace>/archer-backend:first \
  --registry-secret icr-pull --env-from-secret archer-runtime \
  --port 8080 --cpu 0.5 --memory 1G --min-scale 0 --max-scale 2
```

Before creating `archer-runtime`, set `DEMO_DAILY_QUESTION_LIMIT` in `.env`
back to a real ceiling such as 200. The command prints the application's URL.

**4. Connect GitHub Actions.** In your fork's settings:

- Create an environment named `staging`.
- Add the repository secret `IBM_CLOUD_API_KEY`, an API key that can push to
  the registry and update the application.
- Add these repository variables:

  | Variable | Example |
  |---|---|
  | `IBM_CLOUD_REGION` | `eu-gb` |
  | `IBM_CLOUD_RESOURCE_GROUP` | `Default` |
  | `IBM_CODE_ENGINE_PROJECT` | your project name |
  | `IBM_CODE_ENGINE_APP` | your application name |
  | `IBM_CONTAINER_REGISTRY_NAMESPACE` | your namespace |
  | `IBM_CONTAINER_REGISTRY_HOSTNAME` | `uk.icr.io` |
  | `IBM_CODE_ENGINE_IMAGE_HOSTNAME` | `private.uk.icr.io` |
  | `IBM_CODE_ENGINE_REGISTRY_SECRET` | `icr-pull` |

From then on, every merge to `main` that passes CI builds a new image and
updates the application. To change a runtime setting, update the
`archer-runtime` secret and restart the application; the workflow never touches
it.

Before each push, the workflow deletes all but the two newest images in the
namespace, to stay inside the free 512MB, so use a namespace for this
application alone.

## 7. Before you share it

- **Change the login.** Set your own `WEB_USERNAME` and `WEB_PASSWORD`, then
  update or remove the demo credentials printed on the login page
  (`backend/templates/login.html`) and in the README.
- **Remove what describes this project.** Two pages are about the original,
  not your fork: *How it was built* states its measured results, and *Make
  your own* invites visitors to fork it. Delete or rewrite them. Each is a file
  in `frontend/src/components/pages/`, wired in by `AppSideNav.tsx`,
  `hooks/useHashRoute.ts` and `App.tsx`. Point `REPO_URL` in `AppSideNav.tsx`
  at your repository, and if you publish your fork, rewrite the README and
  replace its screenshots in `docs/images/`.
- **Set a daily ceiling.** IBM Cloud spending controls only send emails.
  `DEMO_DAILY_QUESTION_LIMIT` is what stops spending. With two instances the
  real ceiling is twice the setting.
- **Use real signing keys.** `JWT_SECRET_KEY` and `CSRF_SECRET_KEY` have
  insecure fallbacks for tests and must be set in production.
- **Keep `WEBHOOK_SECRET` on the server.** Never put it in frontend code or a
  `VITE_*` variable.
- **Check what your data reveals.** Anyone with the login can ask anything the
  table holds.
- **Read [security](security.md)** for what the query controls do and don't
  cover.
