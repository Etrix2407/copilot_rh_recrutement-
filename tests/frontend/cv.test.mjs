// Tests de frontend/js/cv.js : contrôle du fichier avant l'envoi, bouton « Retirer le fichier », focus.

import assert from "node:assert/strict";
import { test } from "node:test";

import { loadCv, waitFor } from "./fake_browser.mjs";

const ANALYSIS = {
  candidate_name: "Jean Dupont",
  email: "jean.dupont@email.com",
  key_skills: ["Python"],
  years_of_experience: 1,
  education_level: "bac+5",
  match_score: 85,
  score_justifications: ["FastAPI"],
  red_flags: [],
};

// Répond aux exemples (liste vide), puis à l'analyse avec la réponse donnée
const serve = (parse) => (request) => (request.url.endsWith("/samples") ? Response.json([]) : parse(request));
const parsed = () => Response.json({ id: "1", name: "Jean Dupont", analysis: ANALYSIS });

const parseRequests = (page) => page.net.requests.filter((request) => request.url.endsWith("/parse"));

for (const [name, file, message] of [
  ["extension refusée", new File(["x"], "cv.docx"), /ni un PDF ni un fichier \.txt/],
  ["fichier de plus de 2 Mo", new File([new Uint8Array(2_000_001)], "cv.pdf"), /trop lourd \(2 Mo au maximum\)/],
]) {
  test(`contrôle côté client : ${name}, message clair et aucun envoi`, async () => {
    const page = await loadCv();
    page.chooseFile(file);
    // Signalé dès le choix du fichier…
    assert.match(page.$["cv-status"].textContent, message);
    assert.equal(page.$["cv-file"].getAttribute("aria-invalid"), "true");

    // … et à l'envoi, sans appel au serveur
    page.submit();
    assert.match(page.$["cv-status"].textContent, message);
    assert.equal(document.activeElement, page.$["cv-file"]);
    assert.equal(parseRequests(page).length, 0);
  });
}

test("fichier de 2 000 000 octets exactement (extension en majuscules) : accepté et envoyé", async () => {
  const page = await loadCv({ reply: serve(parsed) });
  page.chooseFile(new File([new Uint8Array(2_000_000)], "CV.PDF"));
  assert.equal(page.$["cv-status"].textContent, "");
  page.submit();
  await waitFor(() => !page.$["cv-result"].hidden);
  assert.equal(parseRequests(page).length, 1);
});

test("« Retirer le fichier » apparaît avec un fichier et vide le champ", async () => {
  const page = await loadCv();
  assert.equal(page.$["cv-file-clear"].hidden, true);
  page.chooseFile(new File(["x"], "cv.txt"));
  assert.equal(page.$["cv-file-clear"].hidden, false);

  page.$["cv-file-clear"].click();
  assert.equal(page.$["cv-file"].value, "");
  assert.equal(page.$["cv-file-clear"].hidden, true);
  assert.equal(document.activeElement, page.$["cv-file"]);
});

test("analyse réussie : champ fichier vidé, focus sur le nom, « 1 an » au singulier", async () => {
  const page = await loadCv({ reply: serve(parsed) });
  page.chooseFile(new File(["CV"], "cv.txt"));
  page.$["cv-file"].value = "C:\\fakepath\\cv.txt";
  page.submit();
  await waitFor(() => !page.$["cv-result"].hidden);
  assert.equal(page.$["cv-file"].value, "");
  assert.equal(page.$["cv-file-clear"].hidden, true);
  assert.equal(document.activeElement.textContent, "Jean Dupont");
  assert.match(page.$["cv-result"].textContent, /Expérience1 an(?!s)/);
});

test("erreur d'analyse : message du serveur et focus rendu au bouton d'envoi", async () => {
  const page = await loadCv({
    reply: serve(() => Response.json({ detail: "Le service IA est indisponible." }, { status: 503 })),
  });
  page.$["cv-text"].value = "Jean Dupont, développeur";
  page.submit();
  assert.equal(page.$["cv-submit"].disabled, true);
  await waitFor(() => !page.$["cv-submit"].disabled);
  assert.match(page.$["cv-status"].textContent, /Le service IA est indisponible\./);
  assert.equal(document.activeElement, page.$["cv-submit"]);
});

test("formulaire vide : erreur liée au champ de texte (aria-invalid et focus)", async () => {
  const page = await loadCv();
  page.submit();
  assert.equal(page.$["cv-text"].getAttribute("aria-invalid"), "true");
  assert.equal(document.activeElement, page.$["cv-text"]);
  page.$["cv-text"].dispatch("input");
  assert.equal(page.$["cv-text"].getAttribute("aria-invalid"), null);
});
