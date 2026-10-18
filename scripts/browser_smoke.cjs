/* Isolated end-to-end check: build, assign, autosave, submit, grade and release. */
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
  const joinCode = (
    await teacher.locator(".join-code-panel code").innerText()
  ).trim();
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
  await teacher.getByRole("button", { name: "Publish exam" }).click();
  await teacher.getByRole("link", { name: "Gradebook" }).waitFor();

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
    /discards half/,
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
  await teacher.getByLabel("Points for question 2").fill("18");
  await teacher
    .getByLabel(/^Feedback/)
    .fill("Clear reasoning. Mention the sorted-array precondition.");
  await teacher.getByRole("button", { name: "Save review" }).click();
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
    "PASS: teacher builds and publishes; student joins, autosaves, handles a stale tab and a network interruption, reloads and submits; teacher grades and releases; student sees correct results. Mobile dashboard/exam overflow and uncaught browser errors checked.",
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
