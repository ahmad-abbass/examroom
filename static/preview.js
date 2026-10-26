(() => {
  "use strict";

  const preview = document.querySelector("#exam-preview");
  if (!preview) return;
  const fields = [...preview.querySelectorAll(".answer-field")];
  if (!fields.length) return;
  const links = new Map(
    [...preview.querySelectorAll("[data-question-link]")].map((link) => [
      link.dataset.questionLink,
      link,
    ]),
  );
  const unanswered = preview.querySelector("#preview-unanswered");
  const progress = preview.querySelector("#preview-progress");
  const isAnswered = (field) =>
    field.dataset.kind === "choice"
      ? !!field.querySelector("input:checked")
      : !!field.querySelector("textarea").value.trim();

  function update() {
    let answered = 0;
    fields.forEach((field, index) => {
      const complete = isAnswered(field);
      if (complete) answered++;
      const link = links.get(field.dataset.question);
      link.classList.toggle("answered", complete);
      link.setAttribute(
        "aria-label",
        `Question ${index + 1}, ${complete ? "answered" : "unanswered"}`,
      );
    });
    progress.textContent = `${answered} of ${fields.length} answered`;
    unanswered.disabled = answered === fields.length;
  }

  function navigate(field) {
    field.scrollIntoView({ block: "center" });
    field.focus({ preventScroll: true });
  }

  preview.addEventListener("input", update);
  preview.querySelectorAll(".clear-answer").forEach((button) => {
    button.addEventListener("click", () => {
      button
        .closest(".answer-field")
        .querySelectorAll("input")
        .forEach((input) => {
          input.checked = false;
        });
      update();
    });
  });
  preview.querySelector("#reset-preview").addEventListener("click", () => {
    preview.querySelectorAll("input").forEach((input) => {
      input.checked = false;
    });
    preview.querySelectorAll("textarea").forEach((input) => {
      input.value = "";
    });
    update();
  });
  links.forEach((link, id) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      navigate(fields.find((field) => field.dataset.question === id));
    });
  });
  unanswered.addEventListener("click", () => {
    const field = fields.find((item) => !isAnswered(item));
    if (field) navigate(field);
  });
  update();
})();
