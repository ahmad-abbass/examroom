"use strict";
(() => {
  const form = document.querySelector("#exam-form");
  if (!form) return;
  const fields = [...form.querySelectorAll(".answer-field")];
  const status = document.querySelector("#save-status");
  const error = document.querySelector("#save-error");
  const retry = document.querySelector("#retry-save");
  const submitButton = document.querySelector("#submit-exam");
  const questionLinks = new Map(
    [...form.querySelectorAll("[data-question-link]")].map((link) => [
      link.dataset.questionLink,
      link,
    ]),
  );
  const flagButtons = new Map(
    [...form.querySelectorAll("[data-flag]")].map((button) => [
      button.dataset.flag,
      button,
    ]),
  );
  let revision = Number(form.dataset.revision),
    dirty = false,
    saving = false,
    submitting = false,
    finished = false,
    conflict = false;
  let generation = 0,
    debounce;
  const remaining = Math.max(
    0,
    (Number(form.dataset.deadline) - Number(form.dataset.serverNow)) * 1000,
  );
  const timerStarted = performance.now();

  function isAnswered(field) {
    return field.dataset.kind === "choice"
      ? Boolean(field.querySelector("input:checked"))
      : Boolean(field.querySelector("textarea").value.trim());
  }

  function isFlagged(field) {
    return (
      flagButtons.get(field.dataset.question).getAttribute("aria-pressed") ===
      "true"
    );
  }

  function collectFlags() {
    return Object.fromEntries(
      fields.map((field) => [field.dataset.question, isFlagged(field)]),
    );
  }

  function navigateTo(field) {
    if (!field) return;
    field.scrollIntoView({ block: "center" });
    field.focus({ preventScroll: true });
  }

  function collect() {
    const answers = {};
    let answered = 0;
    let marked = 0;
    for (const [index, field] of fields.entries()) {
      const input =
        field.dataset.kind === "choice"
          ? field.querySelector("input:checked")
          : field.querySelector("textarea");
      answers[field.dataset.question] =
        field.dataset.kind === "choice"
          ? input
            ? Number(input.value)
            : null
          : input.value;
      const hasAnswer = isAnswered(field);
      const flagged = isFlagged(field);
      if (hasAnswer) answered++;
      if (flagged) marked++;
      const link = questionLinks.get(field.dataset.question);
      link.classList.toggle("answered", hasAnswer);
      link.classList.toggle("marked", flagged);
      link.setAttribute(
        "aria-label",
        `Question ${index + 1}: ${hasAnswer ? "answered" : "unanswered"}${flagged ? ", marked for review" : ""}`,
      );
    }
    document.querySelector("#answer-progress").textContent =
      `${answered} of ${fields.length} answered`;
    document.querySelector("#flag-progress").textContent =
      `${marked} marked for review`;
    document.querySelector("#find-unanswered").disabled =
      answered === fields.length;
    document.querySelector("#find-flagged").disabled = marked === 0;
    return answers;
  }

  async function save() {
    if (saving || finished || conflict || (!dirty && !submitting)) return;
    saving = true;
    const requestGeneration = generation;
    const submitThisRequest = submitting;
    status.textContent = submitThisRequest
      ? "Submitting your exam…"
      : "Saving your answers…";
    try {
      const response = await fetch(form.dataset.saveUrl, {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
        },
        body: JSON.stringify({
          answers: collect(),
          flags: collectFlags(),
          revision,
          submit: submitThisRequest,
        }),
      });
      if (response.status === 409) {
        conflict = true;
        fields.forEach((field) => {
          field.disabled = true;
        });
        submitButton.disabled = true;
        throw new Error(
          "Another tab changed this attempt. Reload this page to load the saved answers before continuing.",
        );
      }
      if (response.redirected || response.status === 403)
        throw new Error(
          "Your session needs attention. Open the sign-in page in another tab, then retry saving.",
        );
      const data = await response.json();
      if (!response.ok)
        throw new Error(
          data.error || "Your answers could not be saved. Please retry.",
        );
      revision = data.revision;
      dirty = generation !== requestGeneration;
      error.hidden = true;
      retry.hidden = true;
      status.textContent = "All changes saved ✓";
      if (data.submitted) {
        finished = true;
        location.assign(data.url);
      }
    } catch (failure) {
      dirty = true;
      status.textContent = "Not saved — action needed";
      error.textContent =
        failure.message ||
        "You appear to be offline. Keep this page open and retry saving.";
      error.hidden = false;
      retry.hidden = conflict;
      if (!conflict) {
        submitButton.disabled = false;
        if (remaining > performance.now() - timerStarted)
          fields.forEach((field) => {
            field.disabled = false;
          });
      }
    } finally {
      saving = false;
      if (
        !finished &&
        !conflict &&
        error.hidden &&
        (dirty || (submitting && !submitThisRequest))
      )
        save();
    }
  }

  function changed() {
    dirty = true;
    generation++;
    status.textContent = "Unsaved changes…";
    collect();
    clearTimeout(debounce);
    debounce = setTimeout(save, 650);
  }
  form.addEventListener("input", changed);
  flagButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const pressed = button.getAttribute("aria-pressed") === "true";
      button.setAttribute("aria-pressed", String(!pressed));
      changed();
    });
  });
  questionLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      navigateTo(
        fields.find(
          (field) => field.dataset.question === link.dataset.questionLink,
        ),
      );
    });
  });
  document
    .querySelector("#find-unanswered")
    .addEventListener("click", () =>
      navigateTo(fields.find((field) => !isAnswered(field))),
    );
  document
    .querySelector("#find-flagged")
    .addEventListener("click", () => navigateTo(fields.find(isFlagged)));
  form.querySelectorAll("[data-clear]").forEach((button) =>
    button.addEventListener("click", () => {
      const field = fields.find(
        (f) => f.dataset.question === button.dataset.clear,
      );
      field.querySelectorAll("input[type=radio]").forEach((input) => {
        input.checked = false;
      });
      changed();
    }),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const unanswered = fields.filter((field) => !isAnswered(field)).length;
    const marked = fields.filter(isFlagged).length;
    if (
      !window.confirm(
        `Submit your exam? ${unanswered} unanswered; ${marked} marked for review. Your answers will be locked.`,
      )
    )
      return;
    submitting = true;
    submitButton.disabled = true;
    fields.forEach((field) => {
      field.disabled = true;
    });
    save();
  });
  retry.addEventListener("click", save);
  window.addEventListener("online", save);
  window.addEventListener("beforeunload", (event) => {
    if (dirty && !finished) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) save();
  });
  setInterval(save, 10000);
  function tick() {
    const seconds = Math.max(
      0,
      Math.ceil((remaining - (performance.now() - timerStarted)) / 1000),
    );
    document.querySelector("#timer").textContent =
      `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    document
      .querySelector(".timer-box")
      .classList.toggle("urgent", seconds < 120);
    if (seconds === 0 && !finished && !submitting) {
      submitting = true;
      submitButton.disabled = true;
      fields.forEach((field) => {
        field.disabled = true;
      });
      save();
    }
  }
  collect();
  tick();
  setInterval(tick, 1000);
})();
