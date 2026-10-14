// Faux navigateur minimal pour tester les vrais modules de frontend/js sous Node, sans dépendance :
// un faux DOM (juste ce qu'utilisent les modules) et un faux fetch dont le flux SSE est piloté par le test.

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.parentNode = null;
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.files = [];
    this.dataset = {};
    this.attributes = {};
    this.style = {};
    this.listeners = {};
  }

  get textContent() {
    return this.children.map((child) => (typeof child === "string" ? child : child.textContent)).join("");
  }

  set textContent(text) {
    this.replaceChildren(String(text));
  }

  append(...children) {
    for (const child of children) {
      if (typeof child !== "string") {
        child.parentNode?.removeChild(child);
        child.parentNode = this;
      }
      this.children.push(child);
    }
  }

  replaceChildren(...children) {
    for (const child of this.children) if (typeof child !== "string") child.parentNode = null;
    this.children = [];
    this.append(...children);
  }

  removeChild(child) {
    this.children = this.children.filter((other) => other !== child);
    child.parentNode = null;
  }

  remove() {
    this.parentNode?.removeChild(this);
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes[name] ?? null;
  }

  removeAttribute(name) {
    delete this.attributes[name];
  }

  addEventListener(type, listener) {
    (this.listeners[type] ??= []).push(listener);
  }

  // Déclenche un événement comme le ferait le navigateur
  dispatch(type, fields = {}) {
    const event = { preventDefault() {}, ...fields };
    for (const listener of this.listeners[type] ?? []) listener(event);
  }

  click() {
    if (!this.disabled) this.dispatch("click");
  }

  scrollIntoView() {}

  focus() {
    globalThis.document.activeElement = this;
  }

  querySelectorAll() {
    return [];
  }
}

// Tous les éléments descendants (profondeur d'abord) qui vérifient la condition
export function findAll(root, predicate) {
  const found = [];
  for (const child of root.children) {
    if (typeof child === "string") continue;
    if (predicate(child)) found.push(child);
    found.push(...findAll(child, predicate));
  }
  return found;
}

const CHAT_IDS = [
  "chat-log", "chat-empty", "chat-announcer", "chat-form",
  "chat-input", "chat-send", "chat-stop", "chat-reset",
];
const CV_IDS = [
  "cv-form", "cv-file", "cv-file-clear", "cv-text", "cv-submit",
  "cv-status", "cv-result", "cv-samples", "cv-samples-block",
];
const CANDIDATES_IDS = [
  "candidates-status", "candidates-summary", "candidates-table",
  "candidates-sort", "candidates-refresh", "candidate-details",
];

// DOM neuf : chaque id de la page correspond à un élément ; un id inconnu donne null, comme le vrai DOM
function installDom(ids) {
  const elements = Object.fromEntries(ids.map((id) => [id, new FakeElement(id)]));
  globalThis.document = {
    activeElement: null,
    getElementById: (id) => elements[id] ?? null,
    createElement: (tagName) => new FakeElement(tagName),
  };
  return elements;
}

// Texte d'un événement SSE tel que l'envoie le serveur
export function sse(name, data) {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

// Faux fetch : chaque appel ouvre un flux que le test remplit (push), ferme (close) ou coupe (fail).
// net.reply(request) permet de renvoyer une autre réponse (erreur HTTP, JSON…).
function installFetch() {
  const net = { requests: [], servers: [], reply: null };
  globalThis.fetch = async (url, options = {}) => {
    const body = typeof options.body === "string" ? JSON.parse(options.body) : options.body;
    const request = { url, method: options.method ?? "GET", body };
    net.requests.push(request);
    if (net.reply) return net.reply(request);
    let source;
    const stream = new ReadableStream({ start(controller) { source = controller; } });
    const encoder = new TextEncoder();
    const server = {
      push: (text) => source.enqueue(encoder.encode(text)),
      close: () => source.close(),
      fail: (error) => source.error(error),
    };
    net.servers.push(server);
    // Comme le vrai fetch : l'arrêt coupe le flux avec la raison donnée
    options.signal?.addEventListener("abort", () => {
      try {
        source.error(options.signal.reason);
      } catch {
        // Flux déjà fermé
      }
    });
    return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
  };
  return net;
}

let instance = 0;

// Charge une instance neuve d'un module de frontend/js (état remis à zéro) sur un DOM et un réseau neufs
async function loadModule(name, ids) {
  const elements = installDom(ids);
  const net = installFetch();
  globalThis.confirm = () => true;
  instance += 1;
  const module = await import(`../../frontend/js/${name}?instance=${instance}`);
  return { module, net, $: elements };
}

export async function loadChat({ wordMs = 1, toolCardMs = 1 } = {}) {
  const { module: chat, net, $: elements } = await loadModule("chat.js", CHAT_IDS);
  elements["chat-stop"].hidden = true;
  chat.timing.wordMs = wordMs;
  chat.timing.toolCardMs = toolCardMs;
  chat.initChat();
  return {
    chat,
    net,
    $: elements,
    submit(text) {
      elements["chat-input"].value = text;
      elements["chat-form"].dispatch("submit");
    },
    // Éléments du fil de discussion : classe et texte
    items: () => elements["chat-log"].children.map((item) => ({ className: item.className, text: item.textContent })),
    busy: () => elements["chat-send"].disabled,
  };
}

// Page « Analyser un CV » : net.reply répond aux exemples (liste vide par défaut) puis à l'analyse
export async function loadCv({ reply = () => Response.json([]) } = {}) {
  const { module: cv, net, $: elements } = await loadModule("cv.js", CV_IDS);
  elements["cv-file-clear"].hidden = true;
  net.reply = reply;
  cv.initCv();
  return {
    cv,
    net,
    $: elements,
    chooseFile(file) {
      elements["cv-file"].files = [file];
      elements["cv-file"].dispatch("change");
    },
    submit() {
      elements["cv-form"].dispatch("submit");
    },
  };
}

// Page « Candidats » (le module importe aussi cv.js pour le rendu de l'analyse)
export async function loadCandidates() {
  const { module: candidates, net, $: elements } = await loadModule("candidates.js", [...CANDIDATES_IDS, ...CV_IDS]);
  elements["candidates-sort"].value = "score-desc";
  elements["candidate-details"].hidden = true;
  candidates.initCandidates();
  const table = elements["candidates-table"];
  return {
    candidates,
    net,
    $: elements,
    // Lignes du tableau : texte de chaque cellule
    rows: () => findAll(table, (node) => node.tagName === "tr" && node.parentNode?.tagName === "tbody")
      .map((row) => row.children.map((cell) => cell.textContent)),
    buttons: (text) => findAll(table, (node) => node.tagName === "button" && node.textContent === text),
  };
}

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Attend qu'une condition devienne vraie, sinon échoue (évite les attentes fixes et longues)
export async function waitFor(condition, { timeoutMs = 1000, message = "condition jamais remplie" } = {}) {
  const start = Date.now();
  while (!condition()) {
    if (Date.now() - start > timeoutMs) throw new Error(`Délai dépassé : ${message}`);
    await sleep(2);
  }
}
