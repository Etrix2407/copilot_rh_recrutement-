// Appels à l'API, avec des messages d'erreur compréhensibles par tous.

export class ApiError extends Error {
  constructor(message, status, retryAfter = null) {
    super(message);
    // Code HTTP, ou 0 si la réponse n'a pas pu être lue (serveur injoignable, flux coupé ou illisible)
    this.status = status;
    // Délai d'attente conseillé par le serveur (en-tête Retry-After), en secondes, ou null
    this.retryAfter = retryAfter;
  }
}

export const NETWORK_ERROR = "Le serveur ne répond pas. Réessayez dans quelques instants.";
export const UNREADABLE_RESPONSE = "Réponse illisible du serveur.";
export const GENERIC_ERROR = "Une erreur est survenue. Réessayez dans quelques instants.";

// Attente par défaut avant de réessayer après « trop de demandes » (429) sans délai indiqué
const DEFAULT_RETRY_SECONDS = 10;

// Nombre de secondes pendant lesquelles « Réessayer » reste désactivé (0 : tout de suite)
export function retryDelay(error) {
  if (error?.status !== 429) return 0;
  return error.retryAfter ?? DEFAULT_RETRY_SECONDS;
}

async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    // Arrêt demandé par l'utilisateur : ce n'est pas une panne réseau
    if (options?.signal?.aborted) throw error;
    throw new ApiError(NETWORK_ERROR, 0);
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status, retryAfterSeconds(response));
  }
  return response;
}

// En-tête Retry-After en secondes (la forme « date HTTP » n'est pas utilisée par l'API)
function retryAfterSeconds(response) {
  const seconds = Number.parseInt(response.headers.get("Retry-After") ?? "", 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

// Corps JSON d'une réponse réussie : un corps illisible donne un message français, pas une SyntaxError
async function readJson(response) {
  try {
    return await response.json();
  } catch {
    throw new ApiError(UNREADABLE_RESPONSE, 0);
  }
}

async function errorMessage(response) {
  try {
    // L'API renvoie toujours {"detail": "<message en français>"}
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Corps illisible (proxy, serveur arrêté…) : message générique ci-dessous
  }
  return GENERIC_ERROR;
}

export async function getJson(url) {
  return readJson(await request(url));
}

export async function postJson(url, body) {
  const response = await request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson(response);
}

export async function deleteResource(url) {
  await request(url, { method: "DELETE" });
}

export async function postForm(url, formData) {
  return readJson(await request(url, { method: "POST", body: formData }));
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
