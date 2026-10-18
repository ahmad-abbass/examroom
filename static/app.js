"use strict";
document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
const search = document.querySelector("#exam-search");
if (search)
  search.addEventListener("input", () => {
    let count = 0;
    document.querySelectorAll("[data-search]").forEach((row) => {
      row.hidden = !row.dataset.search
        .toLowerCase()
        .includes(search.value.trim().toLowerCase());
      if (!row.hidden) count++;
    });
    document.querySelector("#search-empty").hidden = count > 0 || !search.value;
  });
const questionForm = document.querySelector("[data-question-form]");
if (questionForm) {
  const kind = questionForm.querySelector("#id_kind");
  const update = () =>
    questionForm.querySelectorAll("[data-choice-only]").forEach((row) => {
      row.hidden = kind.value !== "choice";
    });
  kind.addEventListener("change", update);
  update();
}
