// Appels à l'API, avec des messages d'erreur compréhensibles par tous.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    // Code HTTP, ou 0 si la réponse n'a pas pu être lue (serveur injoignable, flux coupé ou illisible)
    this.status = status;
  }
}

export const NETWORK_ERROR = "Impossible de joindre le serveur. Vérifiez qu'il est bien lancé, puis réessayez.";
export const UNREADABLE_RESPONSE = "Réponse illisible du serveur.";

async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    // Arrêt demandé par l'utilisateur : ce n'est pas une panne réseau
    if (options?.signal?.aborted) throw error;
    throw new ApiError(NETWORK_ERROR, 0);
  }
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
  return response;
}

async function errorMessage(response) {
  try {
    // L'API renvoie toujours {"detail": "<message en français>"}
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Corps illisible (proxy, serveur arrêté…) : message générique ci-dessous
  }
  return `Une erreur est survenue (code ${response.status}). Réessayez.`;
}

export async function getJson(url) {
  return (await request(url)).json();
}

export async function postJson(url, body) {
  const response = await request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}

export async function deleteResource(url) {
  await request(url, { method: "DELETE" });
}

export async function postForm(url, formData) {
  return (await request(url, { method: "POST", body: formData })).json();
}

// Lit un flux SSE envoyé en réponse à un POST (EventSource ne gère que GET).
// onEvent(nom, données) est appelé pour chaque événement, dans l'ordre d'arrivée.
export async function postSse(url, body, onEvent, signal) {
  const response = await request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    let chunk;
    try {
      chunk = await reader.read();
    } catch (error) {
      // Arrêt demandé par l'utilisateur : ce n'est pas une panne réseau
      if (signal?.aborted) throw error;
      throw new ApiError(NETWORK_ERROR, 0);
    }
    if (chunk.done) break;
    // Normalisé sur le tampon entier : un \r\n peut être coupé entre deux morceaux
    buffer = (buffer + chunk.value).replaceAll("\r\n", "\n");
    // Un événement se termine par une ligne vide ; la fin incomplète attend la suite
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop();
    for (const block of blocks) {
      let event;
      try {
        event = parseEvent(block);
      } catch {
        // Données qui ne sont pas du JSON : la suite du flux n'est pas lue
        await reader.cancel().catch(() => {});
        throw new ApiError(UNREADABLE_RESPONSE, 0);
      }
      if (event) onEvent(event.name, event.data);
    }
  }
}

function parseEvent(block) {
  let name = "message";
  const dataLines = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // commentaire de maintien de la connexion
    if (line.startsWith("event:")) name = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  return dataLines.length ? { name, data: JSON.parse(dataLines.join("\n")) } : null;
}
