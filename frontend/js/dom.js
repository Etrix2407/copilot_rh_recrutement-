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

// Affiche un message d'état (chargement, erreur) avec un éventuel bouton « Réessayer »
export function showStatus(container, message, { kind = "info", onRetry } = {}) {
  container.className = `status ${kind === "loading" ? "loading" : ""} ${kind === "error" ? "error" : ""}`;
  container.replaceChildren(message);
  if (onRetry) {
    const retry = el("button", { className: "button", text: "Réessayer", attrs: { type: "button" } });
    retry.addEventListener("click", onRetry);
    container.append(retry);
  }
}

export function clearStatus(container) {
  container.className = "status";
  container.replaceChildren();
}
