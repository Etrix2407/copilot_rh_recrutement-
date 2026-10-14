// Faux navigateur minimal pour tester les vrais modules de frontend/js sous Node, sans dépendance :
// un faux DOM (juste ce qu'utilisent les modules) et un faux fetch dont le flux SSE est piloté par le test.

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
  }

  get textContent() {
    return this.children.map((child) => (typeof child === "string" ? child : child.textContent)).join("");
  }

  set textContent(text) {
    this.children = [String(text)];
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
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
    this.dispatch("click");
  }

  scrollIntoView() {}

  focus() {}

  querySelectorAll() {
    return [];
  }
}

const CHAT_IDS = [
  "chat-log", "chat-empty", "chat-announcer", "chat-form",
  "chat-input", "chat-send", "chat-stop", "chat-reset",
];

function installDom() {
  const elements = Object.fromEntries(CHAT_IDS.map((id) => [id, new FakeElement(id)]));
  elements["chat-stop"].hidden = true;
  globalThis.document = {
    getElementById: (id) => elements[id],
    createElement: (tagName) => new FakeElement(tagName),
  };
  return elements;
}

// Texte d'un événement SSE tel que l'envoie le serveur
export function sse(name, data) {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

// Faux fetch : chaque appel ouvre un flux que le test remplit (push), ferme (close) ou coupe (fail).
// net.reply(request) permet de renvoyer une autre réponse (erreur HTTP…).
function installFetch() {
  const net = { requests: [], servers: [], reply: null };
  globalThis.fetch = async (url, options = {}) => {
    const request = { url, body: JSON.parse(options.body) };
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

// Charge une instance neuve de chat.js (état remis à zéro) sur un DOM et un réseau neufs
export async function loadChat({ wordMs = 1, toolCardMs = 1 } = {}) {
  const elements = installDom();
  const net = installFetch();
  instance += 1;
  const chat = await import(`../../frontend/js/chat.js?instance=${instance}`);
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

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Attend qu'une condition devienne vraie, sinon échoue (évite les attentes fixes et longues)
export async function waitFor(condition, { timeoutMs = 1000, message = "condition jamais remplie" } = {}) {
  const start = Date.now();
  while (!condition()) {
    if (Date.now() - start > timeoutMs) throw new Error(`Délai dépassé : ${message}`);
    await sleep(2);
  }
}
