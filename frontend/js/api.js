// Appels à l'API, avec des messages d'erreur compréhensibles par tous.

export class ApiError extends Error {}

const NETWORK_ERROR = "Impossible de joindre le serveur. Vérifiez qu'il est bien lancé, puis réessayez.";

async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    // Arrêt demandé par l'utilisateur : ce n'est pas une panne réseau
    if (options?.signal?.aborted) throw error;
    throw new ApiError(NETWORK_ERROR);
  }
  if (!response.ok) throw new ApiError(await errorMessage(response));
  return response;
}

async function errorMessage(response) {
  if (response.status === 502) {
    return "Le service d'intelligence artificielle est momentanément indisponible. Réessayez dans quelques instants.";
  }
  try {
    const body = await response.json();
    // FastAPI renvoie un texte pour nos erreurs, une liste pour les erreurs de validation
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Corps illisible : message générique ci-dessous
  }
  if (response.status === 422) return "Les informations envoyées sont incomplètes ou invalides.";
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
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replaceAll("\r\n", "\n");
    // Un événement se termine par une ligne vide ; la fin incomplète attend la suite
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop();
    for (const block of blocks) {
      const event = parseEvent(block);
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
