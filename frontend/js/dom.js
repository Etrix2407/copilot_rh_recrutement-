// Création d'éléments sans innerHTML : le texte venant des CVs ou du LLM est
// toujours inséré avec textContent, il ne peut donc pas injecter de code (XSS).

export function el(tag, options = {}, children = []) {
  const element = document.createElement(tag);
  const { className, text, attrs } = options;
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  for (const [name, value] of Object.entries(attrs ?? {})) element.setAttribute(name, value);
  element.append(...children);
  return element;
}

// Emoji décoratif : ignoré par les lecteurs d'écran, le texte qui suit suffit
export function icon(symbol) {
  return el("span", { text: symbol, attrs: { "aria-hidden": "true" } });
}

// Affiche un message d'état (chargement, erreur) avec un éventuel bouton « Réessayer ».
// retryAfter : secondes pendant lesquelles le bouton reste désactivé (trop de demandes).
export function showStatus(container, message, { kind = "info", onRetry, retryAfter = 0 } = {}) {
  container.className = `status ${kind === "loading" ? "loading" : ""} ${kind === "error" ? "error" : ""}`;
  container.replaceChildren(message);
  if (onRetry) {
    const retry = el("button", { className: "button", text: "Réessayer", attrs: { type: "button" } });
    retry.addEventListener("click", onRetry);
    if (retryAfter > 0) waitBeforeRetry(retry, retryAfter);
    container.append(retry);
  }
}

// Compte à rebours visible sur le bouton, réactivé à la fin du délai
function waitBeforeRetry(button, seconds) {
  let left = seconds;
  button.disabled = true;
  button.textContent = `Réessayer (dans ${left} s)`;
  const timer = setInterval(() => {
    left -= 1;
    if (left > 0) {
      button.textContent = `Réessayer (dans ${left} s)`;
      return;
    }
    clearInterval(timer);
    button.disabled = false;
    button.textContent = "Réessayer";
  }, 1000);
}

export function clearStatus(container) {
  container.className = "status";
  container.replaceChildren();
}

// Signale un champ en erreur (lu par les lecteurs d'écran) et y place le curseur
export function markInvalid(field) {
  field.setAttribute("aria-invalid", "true");
  field.focus();
}

export function clearInvalid(...fields) {
  for (const field of fields) field.removeAttribute("aria-invalid");
}
