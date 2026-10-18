"use strict";
(() => {
  const form = document.querySelector("#exam-form");
  if (!form) return;
  const fields = [...form.querySelectorAll(".answer-field")];
  const status = document.querySelector("#save-status");
  const error = document.querySelector("#save-error");
  const retry = document.querySelector("#retry-save");
  const submitButton = document.querySelector("#submit-exam");
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

  function collect() {
    const answers = {};
    let answered = 0;
    for (const field of fields) {
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
      if (input && (field.dataset.kind === "choice" || input.value.trim()))
        answered++;
    }
    document.querySelector("#answer-progress").textContent =
      `${answered} of ${fields.length} answered`;
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
      // Serialize writes; a submit pressed during an autosave must be sent afterwards.
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
    if (!window.confirm("Submit your exam? Your answers will be locked."))
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
