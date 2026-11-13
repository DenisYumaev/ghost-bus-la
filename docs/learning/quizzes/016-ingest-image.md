# Quiz 016 · PR #18 · The ingest Docker image and its CI build

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

The Dockerfile has two stages, `build` and runtime. What happens in each, and why are the dependencies installed in a separate step *before* `services/ingest/src` is copied?

**Your answer:**

>

<details>
<summary>Model answer</summary>

- **`build` stage:** a Python image plus the `uv` binary. It copies the lockfile and the workspace `pyproject.toml` files, runs `uv sync --no-install-workspace` (installs **only the locked dependencies** into `/app/.venv`), then copies ingest's source and runs `uv sync --no-editable` (installs ingest itself as a normal package).
- **Runtime stage:** a fresh slim Python image. It creates a non-root user, copies **only** `/app/.venv` and `config/feeds.toml`, sets environment defaults, a health check, and the `python -m ghostbus_ingest` command. No `uv`, no source tree, no build tools: smaller, and less to attack.

**Why dependencies first:** Docker caches each layer and rebuilds from the first layer whose inputs changed. Dependencies change rarely; code changes often. Copying only `pyproject.toml` and `uv.lock` first means a code-only change reuses the cached dependency layer, so builds take seconds instead of reinstalling boto3 and the rest.

**Must mention for full credit:** build installs dependencies and then ingest into a venv; runtime copies just the venv and config onto a clean base (smaller, non-root, no tools); dependency-first ordering for layer caching.

</details>

---

## 2. What does this do?

How does the container's `HEALTHCHECK` decide healthy versus unhealthy, and why is `--start-period` only 30 s when a feed may need up to 180 s to be judged unhealthy?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Every 30 s, Docker runs a tiny Python command *inside* the container that GETs `http://127.0.0.1:8081/healthz` and exits 0 on 200, otherwise 1 (including timeouts and connection refused). After 3 consecutive failures, Docker marks the container `unhealthy`.

`/healthz` applies the **service's own rule**: every feed must have succeeded within 3 of its intervals, and the service start time stands in for a feed that hasn't succeeded yet. So the service already gives each feed a **built-in startup grace** (90 s for vehicle positions, 180 s for trip updates). Docker's `--start-period` (failures in this window don't count) only needs to cover the seconds before the HTTP server is listening. A longer start period would just duplicate, and delay, a judgment the service already makes correctly.

**Must mention for full credit:** a check every 30 s via `/healthz`, unhealthy after 3 failures; the service's own grace covers startup, so `start_period` only covers boot.

</details>

---

## 3. What breaks if…

`websockets` was only in the root dev dependency group, not in `services/ingest/pyproject.toml`. All 150 tests passed. What happened when the image ran, why didn't the tests catch it, and what now prevents it?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**What happened:** the container crashed at startup with `ModuleNotFoundError: No module named 'websockets'`. The image installs only ingest's declared dependencies (`uv sync --package ghostbus-ingest --no-dev`), and websockets wasn't one of them. Docker restarts would have looped forever with **zero archiving**.

**Why tests missed it:** tests run in the **development environment** (`uv sync --all-packages` plus the dev group), which *did* contain websockets, added for the recording script. The code worked there. The tests checked behavior, not packaging.

**What prevents it now:**

1. `test_every_third_party_import_is_declared_as_a_dependency` parses every import in ingest's source (with `ast`) and fails if any non-standard-library module isn't declared in ingest's `pyproject.toml`. It immediately flagged `websockets` *and* `botocore`, which was imported directly but only arrived through boto3.
2. CI's image workflow now **builds the image and imports the service inside it** on every PR that touches ingest. It's a packaging test that runs in the same environment as production.

**The lesson:** "works on my machine" includes "works in my dev environment." Test the artifact you ship.

**Must mention for full credit:** the startup crash (a restart loop with no archive); tests ran in the dev environment, which had the package; the import-declaration test and the in-image smoke test now catch it.

</details>

---

## 4. What breaks if…

The workflow tags each image with the commit SHA *and* `:main`. Suppose the VM's deploy pulled `:main` instead of the SHA. Describe a concrete way that goes wrong.

**Your answer:**

>

<details>
<summary>Model answer</summary>

`:main` is a **moving tag**: every push to `main` repoints it. Some ways that bites:

- **Unreviewed or accidental upgrades:** a routine `docker compose pull` (or a VM reboot followed by a pull) silently runs a *newer* build than the one you deployed and tested. A bug introduced by an unrelated merge reaches production without a deploy.
- **Rollback doesn't roll back:** "redeploy the previous version" (infra spec, section 6) is meaningless if the name you redeploy now points to the broken build.
- **You can't tell what's running:** incident investigation needs "which code was live at 03:12?" With a SHA tag the answer is in the deploy record; with `:main` it depends on when the last pull happened.
- **Races:** a deploy that starts pulling while CI is pushing could get either build.

An immutable SHA tag means **a deploy names exactly one build**, and rollback is "deploy the previous SHA." `:main` is only a convenience for humans.

**Must mention for full credit:** `:main` moves; at least one concrete failure (silent upgrade, broken rollback, no record of what's running); SHA tags make deploys and rollbacks exact.

</details>

---

## 5. How would you change it to…

The image is 272 MB, mostly boto3 and botocore. How could you make it smaller, and is it worth doing for this project?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Options:**

- **Trim botocore's data:** botocore ships JSON models for every AWS service (most of its size). A build step can delete the models for services other than S3 and SSM. It's fragile: a botocore upgrade can change the layout, and a missing model breaks at runtime.
- **A smaller S3 client:** replace boto3 with a minimal SigV4-signing HTTP client (httpx plus a small signer). It saves the most, but it means hand-rolling AWS signing and credential retrieval from instance metadata: security-sensitive code, more tests, and a new dependency or ADR.
- **A smaller base:** a distroless or Alpine Python base. Distroless removes the shell (which makes debugging harder); Alpine uses musl, which some wheels don't support.
- **Compile with less:** `UV_COMPILE_BYTECODE=0` saves a little disk but slows startup.

**Worth it?** Mostly **no, not now.** The image is pulled once per deploy over AWS's network. 272 MB costs nothing at this scale, startup is seconds, and the VM disk has 23 GB free. Under ADR-003 decision 4 ("adopt on evidence"), size isn't a measured problem. It would become one with frequent deploys on slow links, a container registry bill, or a scale-to-zero platform where cold-start pull time matters.

**Must mention for full credit:** at least two concrete techniques with their costs; a justified judgment (not worth it now, no measured problem) and what would change it.

</details>
