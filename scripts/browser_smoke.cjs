const { chromium } = require("playwright");
const { spawn, execFileSync } = require("node:child_process");
const { mkdtempSync, mkdirSync, rmSync, existsSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const assert = require("node:assert/strict");

const root = path.resolve(__dirname, "..");
const scratch = mkdtempSync(path.join(tmpdir(), "examroom-e2e-"));
const python =
  process.env.EXAMROOM_PYTHON ||
  (existsSync(path.join(root, ".venv/bin/python"))
    ? path.join(root, ".venv/bin/python")
    : "python");
const port = process.env.E2E_PORT || "8765";
const base = `http://127.0.0.1:${port}`;
const env = {
  ...process.env,
  DJANGO_DEBUG: "1",
  DJANGO_ALLOWED_HOSTS: "127.0.0.1,localhost",
  DATABASE_PATH: path.join(scratch, "test.sqlite3"),
};
const manage = (args) =>
  execFileSync(python, ["manage.py", ...args], {
    cwd: root,
    env,
    stdio: "pipe",
  });
let server, browser;
const errors = [];
async function signIn(page, username) {
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto(`${base}/login/`);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill("DemoRoom!2026");
  await Promise.all([
    page.waitForURL(base + "/"),
    page.getByRole("button", { name: "Sign in" }).click(),
  ]);
}
async function run() {
  manage(["migrate", "--noinput"]);
  manage(["seed_demo"]);
  server = spawn(
    python,
    ["manage.py", "runserver", `127.0.0.1:${port}`, "--noreload"],
    { cwd: root, env, stdio: "ignore" },
  );
  let ready = false;
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(base + "/login/")).ok) {
        ready = true;
        break;
      }
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  assert(ready, "Django test server did not start");
  browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {}),
  });
  const teacherContext = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
  });
  const studentContext = await browser.newContext({
    viewport: { width: 1360, height: 1000 },
  });
  const teacher = await teacherContext.newPage();
  const student = await studentContext.newPage();
  await signIn(teacher, "demo.teacher");
  mkdirSync(path.join(root, "test-results"), { recursive: true });
  await teacher.screenshot({
    path: path.join(root, "test-results/teacher-dashboard.png"),
    fullPage: true,
  });
  assert(
    await teacher
      .getByRole("heading", { name: /Good to see you, Leila/ })
      .count(),
  );
  await teacher
    .getByRole("link", { name: "Create class", exact: false })
    .click();
  await teacher.getByLabel(/^Name/).fill("Algorithms Studio");
  await teacher.getByLabel(/^Code/).fill("CS301");
  await teacher
    .getByLabel("Description")
    .fill("An end-to-end classroom workflow.");
  await teacher
    .getByRole("button", { name: "Create class", exact: false })
    .click();
  let joinCode = (
    await teacher.locator(".join-code-panel code").innerText()
  ).trim();
  await teacher.getByRole("button", { name: "Pause new joins" }).click();
  await teacher.getByRole("button", { name: "Reopen invitations" }).waitFor();
  await teacher.getByRole("button", { name: "Replace join code" }).click();
  const replacementCode = (
    await teacher.locator(".join-code-panel code").innerText()
  ).trim();
  assert.notEqual(replacementCode, joinCode);
  joinCode = replacementCode;
  await teacher.getByRole("button", { name: "Reopen invitations" }).click();
  await teacher
    .getByRole("link", { name: "Create exam", exact: false })
    .click();
  await teacher.getByLabel(/^Title/).fill("Algorithms check-in");
  await teacher.getByLabel("Duration minutes").fill("5");
  await teacher.getByRole("button", { name: "Continue to questions" }).click();
  const examPath = new URL(teacher.url()).pathname.replace("edit/", "");
  await teacher
    .getByRole("link", { name: "Add question", exact: false })
    .first()
    .click();
  await teacher
    .getByLabel("Prompt", { exact: false })
    .fill("What is the binary-search complexity?");
  await teacher.getByLabel("Points", { exact: false }).fill("10");
  for (const [letter, text] of [
    ["a", "Constant"],
    ["b", "Logarithmic"],
    ["c", "Linear"],
    ["d", "Quadratic"],
  ]) {
    await teacher.locator(`#id_option_${letter}`).fill(text);
  }
  await teacher.locator("#id_correct_option").selectOption("1");
  await teacher.getByRole("button", { name: "Save question" }).click();
  await teacher
    .getByRole("link", { name: "Add question", exact: false })
    .first()
    .click();
  await teacher.locator("#id_kind").selectOption("text");
  await teacher
    .getByLabel("Prompt", { exact: false })
    .fill("Explain why the search space shrinks.");
  await teacher.getByLabel("Points", { exact: false }).fill("20");
  await teacher.getByRole("button", { name: "Save question" }).click();
  await teacher
    .getByRole("button", { name: "Move question 2 up", exact: true })
    .click();
  assert.match(
    await teacher.locator(".question-preview h3").first().innerText(),
    /search space shrinks/,
  );
  await teacher
    .getByRole("button", { name: "Move question 1 down", exact: true })
    .click();
  assert.match(
    await teacher.locator(".question-preview h3").first().innerText(),
    /binary-search complexity/,
  );
  await teacher.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await teacher.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "Mobile builder overflows",
  );
  await teacher.setViewportSize({ width: 1440, height: 1100 });
  await teacher.getByRole("button", { name: "Publish exam" }).click();
  await teacher.getByRole("link", { name: "Gradebook" }).waitFor();
  await teacher.getByRole("button", { name: "Duplicate exam" }).click();
  await teacher
    .getByRole("heading", { name: "Algorithms check-in (copy).", exact: true })
    .waitFor();
  assert.equal(await teacher.locator(".question-preview").count(), 2);
  assert(
    await teacher.getByRole("button", { name: "Publish exam" }).isVisible(),
  );
  await teacher.goto(base + examPath + "gradebook/");

  await signIn(student, "demo.ahmad");
  await student.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await student.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "Mobile dashboard overflows",
  );
  await student.screenshot({
    path: path.join(root, "test-results/student-mobile.png"),
    fullPage: true,
  });
  await student.getByLabel("Class join code").fill(joinCode);
  await student.getByRole("button", { name: "Join class" }).click();
  await teacher.reload();
  await teacher
    .getByRole("cell", { name: "Not started", exact: true })
    .waitFor();
  await teacher.getByLabel("Find a student").fill("no matching name");
  await teacher.getByRole("button", { name: "Apply filters" }).click();
  await teacher
    .getByRole("heading", { name: "No students match this view." })
    .waitFor();
  await teacher.getByRole("link", { name: "Clear filters" }).click();
  const csv = await teacherContext.request.get(
    base + examPath + "export/?status=not_started",
  );
  assert.equal(csv.status(), 200);
  assert.match(await csv.text(), /demo\.ahmad,Not started,,30,/);
  await student.goto(base + examPath);
  assert.equal(
    await student.getByText("Logarithmic", { exact: true }).count(),
    0,
    "Questions leaked before start",
  );
  await student
    .getByRole("button", { name: "Start exam", exact: false })
    .click();
  assert.equal(
    await student.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "Mobile exam overflows",
  );
  const staleTab = await studentContext.newPage();
  await staleTab.goto(student.url());
  await student.getByRole("button", { name: "Find unanswered" }).click();
  assert(
    await student
      .locator(".answer-field")
      .first()
      .evaluate((field) => field === document.activeElement),
  );
  await student
    .getByRole("button", { name: "Mark question 2 for review", exact: true })
    .click();
  await student.getByRole("button", { name: "Review marked" }).click();
  assert(
    await student
      .locator(".answer-field")
      .nth(1)
      .evaluate((field) => field === document.activeElement),
  );
  await student.getByLabel("Logarithmic", { exact: true }).check();
  await student
    .getByLabel("Your written response")
    .fill("Each comparison discards half of the remaining sorted range.");
  await student
    .getByRole("status")
    .filter({ hasText: "All changes saved" })
    .waitFor();
  await staleTab
    .getByLabel("Your written response")
    .fill("An older tab must not replace the answer.");
  await staleTab
    .getByRole("alert")
    .filter({ hasText: "Another tab changed" })
    .waitFor();
  assert(
    await staleTab.getByLabel("Your written response").isDisabled(),
    "A stale tab should stop edits",
  );
  await staleTab.close();
  await studentContext.setOffline(true);
  await student
    .getByLabel("Your written response")
    .fill(
      "Each comparison discards half of the remaining sorted range. Network retry verified.",
    );
  await student.getByRole("status").filter({ hasText: "Not saved" }).waitFor();
  await studentContext.setOffline(false);
  await student
    .getByRole("status")
    .filter({ hasText: "All changes saved" })
    .waitFor();
  await student.reload();
  assert(
    await student.getByLabel("Logarithmic", { exact: true }).isChecked(),
    "Saved choice did not survive reload",
  );
  assert.match(
    await student.getByLabel("Your written response").inputValue(),
    /discards half.*Network retry verified\./,
  );
  assert.equal(
    await student
      .getByRole("button", { name: "Mark question 2 for review", exact: true })
      .getAttribute("aria-pressed"),
    "true",
  );
  assert.match(await student.locator("#flag-progress").innerText(), /1 marked/);
  assert(
    await student.getByRole("button", { name: "Find unanswered" }).isDisabled(),
  );
  await student.setViewportSize({ width: 1360, height: 1000 });
  await student.evaluate(() => {
    document.activeElement.blur();
    window.scrollTo(0, 0);
  });
  await student.screenshot({
    path: path.join(root, "test-results/student-exam.png"),
    fullPage: true,
  });
  await student.getByRole("button", { name: "Submit exam" }).click();
  await student.getByRole("heading", { name: "All handed in" }).waitFor();
  assert.equal(
    await student.getByText("Correct", { exact: true }).count(),
    0,
    "Answer keys leaked before release",
  );

  await teacher.goto(base + examPath + "gradebook/");
  await teacher.getByRole("link", { name: "Review", exact: false }).click();
  const reviewURL = teacher.url();
  const staleReview = await teacherContext.newPage();
  staleReview.on("pageerror", (error) => errors.push(error.message));
  await staleReview.goto(reviewURL);
  await teacher.getByLabel("Points for question 2").fill("18");
  await teacher
    .getByLabel(/^Feedback/)
    .fill("Clear reasoning. Mention the sorted-array precondition.");
  await teacher.getByRole("button", { name: "Save review" }).click();
  await staleReview.getByLabel("Points for question 2").fill("1");
  const [conflictResponse] = await Promise.all([
    staleReview.waitForResponse(
      (response) =>
        response.url() === reviewURL && response.request().method() === "POST",
    ),
    staleReview.getByRole("button", { name: "Save review" }).click(),
  ]);
  assert.equal(conflictResponse.status(), 409);
  assert(
    await staleReview.getByRole("button", { name: "Save review" }).isDisabled(),
  );
  await staleReview.getByRole("link", { name: "Reload latest review" }).click();
  assert.equal(
    await staleReview.getByLabel("Points for question 2").inputValue(),
    "18",
  );
  await staleReview.close();
  await teacher.getByRole("button", { name: "Release results" }).click();
  await student.reload();
  await student.getByRole("heading", { name: "A moment to reflect" }).waitFor();
  await student.evaluate(() => {
    document.activeElement.blur();
    window.scrollTo(0, 0);
  });
  assert(
    await student
      .getByText("Clear reasoning. Mention the sorted-array precondition.", {
        exact: true,
      })
      .count(),
  );
  assert.equal(
    (await student.locator(".score-panel strong").innerText()).replace(
      /\s/g,
      "",
    ),
    "28/30",
  );
  await student.screenshot({
    path: path.join(root, "test-results/student-results.png"),
    fullPage: true,
  });
  assert.equal(errors.length, 0, `Browser errors: ${errors.join("; ")}`);
  console.log(
    "PASS: teacher controls invites, reorders and copies exams, filters the complete roster, and exports CSV; student navigates and marks questions, autosaves across network retry and reload, rejects stale edits, and submits; teacher grades with stale-review protection and releases the correct results. Mobile dashboard, builder, and exam overflow and uncaught browser errors checked.",
  );
}
run()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    if (browser) await browser.close();
    if (server && server.exitCode === null) {
      server.kill("SIGTERM");
      await new Promise((resolve) => server.once("exit", resolve));
    }
    rmSync(scratch, { recursive: true, force: true });
  });
