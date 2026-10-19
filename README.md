# ExamRoom

**A little less admin. A little more room for learning.**

ExamRoom is a small, full-stack exam platform for teachers and students. Teachers create classes, build timed assessments, review written responses, and release results. Students join with a class code, take an exam in a focused workspace, and get their grades and feedback when the teacher releases them.

Built with **Python, Django, SQLite, and vanilla JavaScript**. No frontend build step is needed to run the app.

> Portfolio learning project developed with AI assistance. The implementation is intentionally small enough to read, test, modify, and explain. It is not an independently audited examination service.

## What you can do

| Teachers                                                | Students                                              |
| ------------------------------------------------------- | ----------------------------------------------------- |
| Create classes and share random join codes              | Register a student account and join a class           |
| Build multiple-choice and written-response questions    | See assigned exams and their availability             |
| Set a duration and optional opening/closing times       | Start one timed attempt with a persistent deadline    |
| Publish an assessment with frozen questions and timing  | Autosave answers and continue after refreshing        |
| Review written answers with bounded points and feedback | Submit once; later see released, fully graded results |
| Release/hide results and export a CSV gradebook         | Review correct choices, explanations, and feedback    |

The server enforces ownership, enrollment, deadlines, revisions, and scores. Correct answer keys are not sent to students before results are available. Multiple-choice answers are graded on submission; written responses require a teacher's review.

Teachers can duplicate an existing exam into a fresh draft. Questions and answer keys are copied, while schedules, publication, released results, and student attempts are reset. Editing the copy leaves the original assessment untouched.

Use the question builder's up/down controls to arrange a draft. The order is saved on the server and frozen when published; keyboard and touch users can use the same controls without drag-and-drop.

Class owners can pause/reopen new joins or replace a shared join code. The old code stops working immediately after replacement. Neither action removes enrolled students or changes their attempts.

The gradebook includes enrolled students who have not started, plus active, unreviewed, and graded attempts. Search by name/username or filter by status. Pages contain 25 students; CSV exports use the same filters and include every matching row across pages. Summary statistics always describe the entire class.

Students can jump between questions, find unanswered items, and mark questions for review. Review marks use the same autosave revision and deadline as answers, survive refresh, and never change the score. Submission confirms the unanswered and marked counts before locking the attempt.

Teacher reviews have a separate grading revision. If two tabs review the same submission, the later stale save receives a conflict and a link to reload the current review instead of replacing newer grades or feedback.

## Run locally

Requires Python **3.12 or 3.13**. These commands use a Unix-like shell:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open **http://127.0.0.1:8000**. On Windows, activate with `.venv\Scripts\activate` instead.

The optional demo command populates an **empty development database** with fictional accounts, three classes, draft/published exams, and sample submissions. Re-running it preserves the existing demo. It refuses to seed when `DJANGO_DEBUG=0`.

| Role           | Username              | Development-only password |
| -------------- | --------------------- | ------------------------- |
| Teacher        | demo.teacher          | DemoRoom!2026             |
| Student        | demo.ahmad            | DemoRoom!2026             |
| Other students | demo.maya / demo.omar | DemoRoom!2026             |

### Try the full workflow

1. Sign in as the teacher. Open **Data Structures**, copy the class code, and inspect its published midterm and draft exam.
2. Create a new exam, add questions, then publish it. Publishing freezes its questions and timing.
3. Open a private window as a student. Join the class, start the exam, answer questions, and wait for **All changes saved**. Refresh to verify persistence.
4. Submit the exam. The student sees a submission receipt while results are private.
5. As the teacher, open the gradebook, review written responses, save points and feedback, and release results.
6. Refresh the student's submission to see the final score and feedback. Export the gradebook as CSV.

For a fresh non-demo installation, skip `seed_demo`. Students can register; a trusted operator provisions teachers:

```sh
python manage.py create_teacher leila --name 'Leila Mansour' --email leila@example.com
```

The command prompts for a password and validates it. An optional `TEACHER_PASSWORD` environment variable supports non-interactive provisioning. Public registration always creates a student, regardless of any posted role or staff flag.

## Tests and checks

```sh
pip install -r requirements-dev.txt
python manage.py test --verbosity 2
python manage.py check
python manage.py makemigrations --check --dry-run
ruff check .
ruff format --check .
```

The backend test suite exercises real database-backed workflows: cross-account access, student role escalation attempts, CSRF, scheduling boundaries, stored deadlines, stale-tab conflicts, invalid answer rollback, late payload rejection, scoring, duplicate submission, manual-grade limits, result privacy, HTML escaping, CSV formula neutralization, and demo safety.

See the [local verification record](docs/verification.md) for executed checks and their limits.

### Browser workflow check

Node **24** is optional, for development checks only:

```sh
npm ci
npx playwright install --with-deps chromium
npm run test:e2e
```

In a restricted test environment, `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` can point to an installed Chromium binary. The default uses the browser matched to the pinned Playwright version.

The browser check starts its own temporary database and Django server. It signs in as a teacher, creates and publishes a mixed-question exam, joins as a student, verifies autosave across refresh, tests stale-tab conflicts and a network interruption/retry, submits, grades, releases, and checks the final result. It also checks mobile dashboard/exam overflow and uncaught browser errors. It does **not** modify your normal development database. Screenshots are written to the ignored `test-results/` directory.

GitHub Actions runs backend checks on Python 3.12/3.13 and a Chromium workflow check. A configured workflow is not a claim that a particular remote run has passed; inspect the repository's Actions tab for results.

## Design notes

The app uses server-rendered Django templates and a small JavaScript autosave controller. Domain rules live in `classroom/services.py`; forms validate teacher input; views scope every object lookup to its owner or enrolled student. See [architecture and invariants](docs/architecture.md) and the [learning guide](docs/learning-guide.md).

- **One attempt, one deadline.** A unique database constraint prevents duplicate attempts. The stored deadline is the earlier of the duration limit and the exam closing time.
- **Time is authoritative on the server.** Late answer payloads are ignored. The countdown is a visual aid, not a security boundary.
- **Safe autosave.** Writes are serialized in the browser and checked against an attempt revision. A stale tab receives HTTP 409 instead of silently replacing newer work.
- **Predictable assessment content.** Published questions and timing cannot be changed through the app.
- **Controlled results.** A student sees a score, explanations, and answer keys only when the attempt is fully graded and results are released.

Expired attempts are finalized when the app next reads or writes them, or when this idempotent command runs:

```sh
python manage.py expire_attempts
```

An operator can schedule it once a minute. Late answers remain rejected even if the command has not run yet. In a network interruption, only answers successfully saved before the deadline can be graded; the interface reports save failures and offers retry.

## Deployment configuration

Development defaults intentionally make local setup easy. For an HTTPS deployment, set:

| Variable                    | Purpose                                                                                         |
| --------------------------- | ----------------------------------------------------------------------------------------------- |
| DJANGO_DEBUG=0              | Disable development mode; enable secure cookies, HTTPS redirect and HSTS                        |
| DJANGO_SECRET_KEY           | A unique random secret of at least 50 characters; startup refuses the development key           |
| DJANGO_ALLOWED_HOSTS        | Comma-separated real hostnames                                                                  |
| DJANGO_CSRF_TRUSTED_ORIGINS | Comma-separated HTTPS origins, when required by your proxy setup                                |
| DATABASE_PATH               | Absolute SQLite path on persistent storage                                                      |
| DJANGO_TRUST_PROXY=1        | Trust the forwarded HTTPS header **only** behind a proxy that strips untrusted incoming headers |

Environment variables are read directly. The `.env.example` file is a reference; Django does not automatically load it.

```sh
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2
```

A Dockerfile provides the same migration/Gunicorn startup and stores its database under `/data`; mount that directory as a persistent volume and supply the production variables. Terminate TLS at a trusted reverse proxy. Browser HSTS preload enrollment is intentionally left off; Django reports W021 for that optional choice. Do not use the demo accounts on a public deployment.

### Scope

This is a classroom-scale, single-host application. SQLite uses `IMMEDIATE` transactions and a 20-second busy timeout so writes are serialized; move to PostgreSQL and revisit load/concurrency behavior before a larger deployment. Teacher provisioning is trusted, sign-in throttling is basic (per username and source address), and production operations still need backups, monitoring, stronger abuse controls, and an account recovery policy. There is no proctoring, SSO, email delivery, rich-text uploads, or high-stakes exam certification.

## References and authorship

Implementation is original to this repository. The [Django authentication](https://docs.djangoproject.com/en/5.2/topics/auth/default/), [transaction](https://docs.djangoproject.com/en/5.2/topics/db/transactions/), and [security](https://docs.djangoproject.com/en/5.2/topics/security/) documentation informed framework usage. [Moodle's quiz timing documentation](https://docs.moodle.org/502/en/Quiz_settings) was consulted for common assessment concepts; no Moodle code or assets were copied.

Created for Ahmad Abbas as a portfolio learning project with AI assistance. Released under the [MIT license](LICENSE).
