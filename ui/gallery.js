// The gallery page's examples (kept out of the HTML so the page needs no inline script).
import { settings } from "/ui/rabbit.js";

for (const button of document.querySelectorAll("[data-mode]")) {
  button.addEventListener("click", () => settings.set(button.dataset.mode, button.dataset.value));
}

const choices = document.getElementById("choices");
choices.choices = ['Search for "sickle cell"', 'Search for "sickle cell disease gene therapy"', 'Search for "Sickle cell CRISPR"'];
choices.addEventListener("rabbit-choose", (event) => {
  document.getElementById("picked").textContent = `You picked ${event.detail.number}: ${event.detail.label}`;
});

document.getElementById("ask").addEventListener("click", async () => {
  const yes = await document.getElementById("dialog").ask(
    'This sends the words "sickle cell" to PubMed, ClinicalTrials.gov, NIH RePORTER and Europe PMC. Send it?');
  document.getElementById("answer").textContent = yes ? "You said yes." : "You said no. Nothing was sent.";
});

const chat = document.getElementById("chat");
chat.add("you", "can gene editing cure sickle cell");
chat.add("rabbit", "Gene editing can correct the change in the HBB gene behind sickle cell disease [4]. "
  + "In one study, sickle hemoglobin fell from 89% to 22% [4].\n\nSources:\n[4] Development of CRISPR_SCD001 (pubmed, 2026)",
  { choices: ["Explain that more simply", "Search public sources for newer records", "Share this answer for training"] });
chat.add("rabbit", "<b>This text stays plain text</b>: nothing in a message can run as code.");
