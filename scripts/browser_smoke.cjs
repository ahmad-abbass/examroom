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
  await teacher.getByRole("link", { name: "Preview as student" }).click();
  await teacher
    .getByText("Preview only. Answers are not saved or submitted.")
    .waitFor();
  assert.equal(await teacher.locator("#exam-form").count(), 0);
  assert.equal(
    await teacher.getByText("✓ Correct", { exact: true }).count(),
    0,
  );
  const previewSaves = [];
  const trackPreviewSave = (request) => {
    if (request.method() === "POST" && request.url().includes("/attempts/")) {
      previewSaves.push(request.url());
    }
  };
  teacher.on("request", trackPreviewSave);
  await teacher.getByRole("button", { name: "Find unanswered" }).click();
  assert(
    await teacher
      .locator(".answer-field")
      .first()
      .evaluate((field) => field === document.activeElement),
  );
  await teacher.getByLabel("Logarithmic", { exact: true }).check();
  await teacher.getByRole("button", { name: "Clear selection" }).click();
  assert.equal(
    await teacher.getByLabel("Logarithmic", { exact: true }).isChecked(),
    false,
  );
  await teacher.getByLabel("Logarithmic", { exact: true }).check();
  await teacher
    .getByLabel("Your written response")
    .fill("A temporary preview response.");
  await teacher
    .getByRole("status")
    .filter({ hasText: "2 of 2 answered" })
    .waitFor();
  assert(
    await teacher.getByRole("button", { name: "Find unanswered" }).isDisabled(),
  );
  await teacher.screenshot({
    path: path.join(root, "test-results/teacher-preview.png"),
    fullPage: true,
  });
  await teacher.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await teacher.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "Mobile preview overflows",
  );
  await teacher.screenshot({
    path: path.join(root, "test-results/teacher-preview-mobile.png"),
    fullPage: true,
  });
  await teacher.getByRole("button", { name: "Reset preview" }).click();
  await teacher
    .getByRole("status")
    .filter({ hasText: "0 of 2 answered" })
    .waitFor();
  assert.equal(
    await teacher.getByLabel("Your written response").inputValue(),
    "",
  );
  assert.equal(
    await teacher.getByLabel("Logarithmic", { exact: true }).isChecked(),
    false,
  );
  await teacher
    .getByLabel("Your written response")
    .fill("Reload should discard this.");
  await teacher.reload();
  await teacher
    .getByRole("status")
    .filter({ hasText: "0 of 2 answered" })
    .waitFor();
  assert.equal(
    await teacher.getByLabel("Your written response").inputValue(),
    "",
  );
  assert.equal(previewSaves.length, 0, "Preview wrote to an attempt endpoint");
  teacher.off("request", trackPreviewSave);
  await teacher.setViewportSize({ width: 1440, height: 1100 });
  await teacher
    .getByRole("link", { name: "Back to exam builder", exact: false })
    .click();
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
  const draftBuilder = teacher.url();
  await teacher
    .getByRole("button", { name: "Save to bank", exact: true })
    .first()
    .click();
  await teacher
    .getByLabel("Title", { exact: false })
    .fill("Binary search / reusable");
  await teacher.getByLabel("Topic", { exact: false }).fill("Searching");
  await teacher
    .getByRole("button", { name: "Save to bank", exact: false })
    .click();
  await teacher
    .getByRole("link", { name: "Create question", exact: false })
    .click();
  await teacher.getByLabel("Title", { exact: false }).fill("DFS reasoning");
  await teacher.getByLabel("Topic", { exact: false }).fill("Graphs");
  await teacher.locator("#id_kind").selectOption("text");
  await teacher
    .getByLabel("Prompt", { exact: false })
    .fill("Explain why DFS discovery and finish intervals are nested.");
  await teacher.getByLabel("Points", { exact: false }).fill("15");
  await teacher
    .getByRole("button", { name: "Save to bank", exact: false })
    .click();
  await teacher.getByLabel("Find a question").fill("Searching");
  await teacher.getByLabel("Question type").selectOption("choice");
  await teacher.getByRole("button", { name: "Search bank" }).click();
  assert.equal(await teacher.locator(".bank-question").count(), 1);
  await teacher.getByRole("link", { name: "Clear filters" }).click();
  assert.equal(await teacher.locator(".bank-question").count(), 2);
  const reusable = teacher
    .locator(".bank-question")
    .filter({ hasText: "Binary search / reusable" });
  await reusable.locator("summary").click();
  assert.match(
    await reusable.locator(".preview-option.correct").innerText(),
    /Logarithmic/,
  );
  await teacher.screenshot({
    path: path.join(root, "test-results/question-bank.png"),
    fullPage: true,
  });
  await teacher.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await teacher.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "Mobile question bank overflows",
  );
  await teacher.screenshot({
    path: path.join(root, "test-results/question-bank-mobile.png"),
    fullPage: true,
  });
  await teacher.setViewportSize({ width: 1440, height: 1100 });
  for (const title of ["Binary search / reusable", "DFS reasoning"]) {
    await teacher.goto(draftBuilder);
    await teacher.getByRole("link", { name: "Browse question bank" }).click();
    await teacher
      .locator(".bank-question")
      .filter({ hasText: title })
      .getByRole("button", { name: "Add to exam" })
      .click();
  }
  assert.equal(await teacher.locator(".question-preview").count(), 4);
  await teacher
    .getByRole("link", { name: "Question bank", exact: true })
    .click();
  await reusable
    .getByRole("link", { name: "Edit question", exact: false })
    .click();
  await teacher
    .getByLabel("Prompt", { exact: false })
    .fill("A changed bank question");
  await teacher.locator("#id_correct_option").selectOption("0");
  await teacher
    .getByRole("button", { name: "Save to bank", exact: false })
    .click();
  await reusable.getByRole("button", { name: "Delete from bank" }).click();
  assert.equal(await teacher.locator(".bank-question").count(), 1);
  await teacher.goto(draftBuilder);
  const imported = teacher.locator(".question-preview").nth(2);
  assert.match(
    await imported.locator("h3").innerText(),
    /binary-search complexity/,
  );
  assert.match(
    await imported.locator(".preview-option.correct").innerText(),
    /Logarithmic/,
  );
  await teacher.goto(base + examPath + "gradebook/");

  await signIn(student, "demo.ahmad");
  assert.equal(
    await student
      .getByRole("link", { name: "Question bank", exact: true })
      .count(),
    0,
  );
  assert.equal(
    (await studentContext.request.get(base + "/question-bank/")).status(),
    403,
  );
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
  const sortedExamID = Number(examPath.split("/").filter(Boolean).at(-1));
  assert(Number.isSafeInteger(sortedExamID));
  manage([
    "shell",
    "-c",
    [
      "from datetime import timedelta",
      "from django.contrib.auth.models import User",
      "from django.utils import timezone",
      "from classroom.models import Attempt, Enrollment, Exam",
      "from classroom.services import grade_submission, save_answers, start_attempt",
      `exam = Exam.objects.get(pk=${sortedExamID})`,
      "choice = exam.questions.get(kind='choice')",
      "written = exam.questions.get(kind='text')",
      "now = timezone.now()",
      "for username, name, points in [('ranked-low', 'Ben', 0), ('ranked-high', 'Zoe', 20), ('ranked-missing', 'Amy', None)]:",
      "    student = User.objects.create_user(username=username, first_name=name)",
      "    Enrollment.objects.create(course=exam.course, student=student)",
      "    if points is not None:",
      "        attempt = start_attempt(exam.pk, student)",
      "        save_answers(attempt.pk, student, {str(choice.pk): choice.correct_option, str(written.pk): 'Sorting fixture'}, 0, submit=True)",
      "        answer = attempt.answers.get(question=written)",
      "        grade_submission(attempt.pk, exam.course.teacher, {answer.pk: (points, '')}, 0)",
      "        Attempt.objects.filter(pk=attempt.pk).update(started_at=now - timedelta(minutes=2), submitted_at=now - timedelta(seconds=30 - points))",
    ].join("\n"),
  ]);
  await teacher.goto(base + examPath + "gradebook/");
  await teacher.getByLabel("Find a student").fill("ranked-");
  await teacher
    .getByLabel("Sort by", { exact: true })
    .selectOption("score_desc");
  await teacher.getByRole("button", { name: "Apply filters" }).click();
  const rosterNames = teacher.locator("tbody tr td:first-child small");
  assert.deepEqual(await rosterNames.allTextContents(), [
    "ranked-high",
    "ranked-low",
    "ranked-missing",
  ]);
  assert.equal(
    await teacher.getByLabel("Sort by", { exact: true }).inputValue(),
    "score_desc",
  );
  const sortedExport = await teacherContext.request.get(
    new URL(
      await teacher
        .getByRole("link", { name: "Export CSV", exact: false })
        .getAttribute("href"),
      base,
    ).href,
  );
  assert.equal(sortedExport.status(), 200);
  assert.deepEqual(
    (await sortedExport.text())
      .trim()
      .split(/\r?\n/)
      .slice(1)
      .map((line) => line.split(",")[1]),
    ["ranked-high", "ranked-low", "ranked-missing"],
  );
  await teacher
    .getByLabel("Sort by", { exact: true })
    .selectOption("score_asc");
  await teacher.getByRole("button", { name: "Apply filters" }).click();
  assert.deepEqual(await rosterNames.allTextContents(), [
    "ranked-low",
    "ranked-high",
    "ranked-missing",
  ]);
  await teacher
    .getByLabel("Sort by", { exact: true })
    .selectOption("submitted_desc");
  await teacher.getByRole("button", { name: "Apply filters" }).click();
  assert.deepEqual(await rosterNames.allTextContents(), [
    "ranked-high",
    "ranked-low",
    "ranked-missing",
  ]);
  await teacher.screenshot({
    path: path.join(root, "test-results/sorted-gradebook.png"),
    fullPage: true,
  });
  await teacher.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await teacher.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "Mobile gradebook overflows",
  );
  await teacher.screenshot({
    path: path.join(root, "test-results/sorted-gradebook-mobile.png"),
    fullPage: true,
  });
  await teacher.setViewportSize({ width: 1440, height: 1100 });
  const largeExam = JSON.parse(
    manage([
      "shell",
      "-c",
      [
        "import json",
        "from django.contrib.auth.models import User",
        "from classroom.models import Course, Enrollment, Exam, Question",
        "teacher = User.objects.get(username='demo.teacher')",
        "student = User.objects.get(username='demo.ahmad')",
        "course = Course.objects.create(teacher=teacher, name='Written assessments', code='WRITE')",
        "Enrollment.objects.create(course=course, student=student)",
        "exam = Exam.objects.create(course=course, title='Long written answers', duration_minutes=5, published=True)",
        "Question.objects.bulk_create([Question(exam=exam, position=i, kind='text', prompt=f'Written response {i + 1}') for i in range(4)])",
        "print(json.dumps({'id': exam.pk}))",
      ].join("\n"),
    ])
      .toString()
      .trim()
      .split("\n")
      .at(-1),
  );
  await student.goto(`${base}/exams/${largeExam.id}/`);
  await student
    .getByRole("button", { name: "Start exam", exact: false })
    .click();
  const longResponse = "ن".repeat(10000);
  const writtenFields = student.getByLabel("Your written response", {
    exact: true,
  });
  assert.equal(await writtenFields.count(), 4);
  for (const field of await writtenFields.all()) await field.fill(longResponse);
  await student
    .getByRole("status")
    .filter({ hasText: "All changes saved" })
    .waitFor({ timeout: 10000 });
  await student.reload();
  for (const field of await writtenFields.all())
    assert.equal(await field.inputValue(), longResponse);
  await student.getByRole("button", { name: "Submit exam" }).click();
  await student.getByRole("heading", { name: "All handed in" }).waitFor();
  assert.equal(errors.length, 0, `Browser errors: ${errors.join("; ")}`);
  console.log(
    "PASS: teacher controls invites, reorders, previews without saving, copies exams, saves and creates bank questions, searches and reuses them in a draft, and edits/deletes bank entries without changing exam copies; bank access rejects students. Teacher filters and sorts the roster, exports CSV, grades with stale-review protection, and releases results. Student navigation, review marks, autosave, network retry, reload, stale edits, submission, and an 80 KB UTF-8 payload pass. Mobile dashboard, builder, bank, preview, gradebook, and exam overflow and browser errors checked.",
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
