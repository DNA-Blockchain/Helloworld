// RabbitSoftware UI kit: Web Components with no build step. Import it as a module:
//
//   <link rel="stylesheet" href="/ui/tokens.css">
//   <script type="module" src="/ui/rabbit.js"></script>
//
// Accessibility rules every component follows:
//   - real <button>s and landmarks, so keyboards and screen readers work without extra effort;
//   - every target at least --rabbit-touch tall, with a visible focus ring;
//   - meaning never by colour alone (status shows a symbol and a word);
//   - text is always inserted as text (textContent), never as HTML, so nothing in a message can run.

const BASE = `
  :host { font: inherit; color: inherit; }
  button {
    font: inherit; min-height: var(--rabbit-touch); min-width: var(--rabbit-touch);
    padding: 0.35em 1.1em; border-radius: var(--rabbit-radius); cursor: pointer;
    border: 2px solid var(--rabbit-accent); background: var(--rabbit-surface); color: var(--rabbit-text);
  }
  button:hover { filter: brightness(0.96); }
  button:focus-visible { outline: 4px solid var(--rabbit-focus); outline-offset: 2px; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
`;

function shadow(host, html, options = {}) {
  const root = host.attachShadow({ mode: "open", ...options });
  root.innerHTML = `<style>${BASE}${html.style || ""}</style>${html.body}`;   // fixed markup only, never user text
  return root;
}

// -- display settings, kept per device ---------------------------------------------------------------
const MODES = { text: ["normal", "big"], contrast: ["normal", "high"], theme: ["system", "light", "dark"] };

export const settings = {
  get(name) {
    try {
      const value = localStorage.getItem(`rabbit.${name}`);
      return MODES[name].includes(value) ? value : MODES[name][0];
    } catch {
      return MODES[name][0];
    }
  },
  set(name, value) {
    if (!MODES[name]?.includes(value)) throw new Error(`${name} can be ${MODES[name]?.join(", ")}`);
    try { localStorage.setItem(`rabbit.${name}`, value); } catch { /* private mode: still applies now */ }
    this.apply();
  },
  apply(root = document.documentElement) {
    const text = this.get("text"), contrast = this.get("contrast"), theme = this.get("theme");
    text === "big" ? root.setAttribute("data-text", "big") : root.removeAttribute("data-text");
    contrast === "high" ? root.setAttribute("data-contrast", "high") : root.removeAttribute("data-contrast");
    theme === "system" ? root.removeAttribute("data-theme") : root.setAttribute("data-theme", theme);
  },
};

// -- <rabbit-button variant="primary|secondary|danger"> ------------------------------------------------
class RabbitButton extends HTMLElement {
  static observedAttributes = ["disabled", "variant"];

  constructor() {
    super();
    this.root = shadow(this, {
      style: `
        :host { display: inline-block; }
        :host([variant="primary"]) button { background: var(--rabbit-accent); color: var(--rabbit-accent-text); }
        :host([variant="danger"]) button { border-color: var(--rabbit-problem); color: var(--rabbit-problem); }`,
      body: `<button part="button" type="button"><slot></slot></button>`,
    }, { delegatesFocus: true });
    this.button = this.root.querySelector("button");
  }

  attributeChangedCallback() {
    this.button.disabled = this.hasAttribute("disabled");
  }
}

// -- <rabbit-card heading="..." level="2"> --------------------------------------------------------------
class RabbitCard extends HTMLElement {
  static observedAttributes = ["heading", "level"];

  constructor() {
    super();
    this.root = shadow(this, {
      style: `
        section { background: var(--rabbit-surface); border: 2px solid var(--rabbit-border);
                  border-radius: var(--rabbit-radius); padding: var(--rabbit-space); margin: 0 0 var(--rabbit-space); }
        .h { margin: 0 0 0.5em; font-size: 1.15em; font-weight: 700; }`,
      body: `<section part="card"><div class="h" id="h" role="heading" aria-level="2"></div><slot></slot></section>`,
    });
  }

  connectedCallback() {
    this.attributeChangedCallback();
  }

  attributeChangedCallback() {
    const heading = this.root.getElementById("h");
    heading.textContent = this.getAttribute("heading") || "";
    heading.hidden = !heading.textContent;
    heading.setAttribute("aria-level", String(Math.min(6, Math.max(1, Number(this.getAttribute("level")) || 2))));
    this.root.querySelector("section").setAttribute("aria-labelledby", heading.textContent ? "h" : "");
  }
}

// -- <rabbit-status state="ok|warn|problem|unknown">text</rabbit-status> -------------------------------------
const STATES = { ok: ["✓", "OK"], warn: ["!", "Warning"], problem: ["✕", "Problem"], unknown: ["?", "Unknown"] };

class RabbitStatus extends HTMLElement {
  static observedAttributes = ["state"];

  constructor() {
    super();
    this.root = shadow(this, {
      style: `
        :host { display: inline-flex; align-items: center; gap: 0.5em; }
        .icon { display: inline-grid; place-items: center; width: 1.6em; height: 1.6em; border-radius: 50%;
                font-weight: 800; border: 2px solid currentColor; }
        :host([state="ok"]) .icon { color: var(--rabbit-ok); }
        :host([state="warn"]) .icon { color: var(--rabbit-warn); }
        :host([state="problem"]) .icon { color: var(--rabbit-problem); }`,
      body: `<span class="icon" aria-hidden="true"></span><span class="sr"></span><slot></slot>`,
    });
  }

  connectedCallback() {
    this.attributeChangedCallback();
  }

  attributeChangedCallback() {
    const [icon, word] = STATES[this.getAttribute("state")] || STATES.unknown;
    this.root.querySelector(".icon").textContent = icon;
    this.root.querySelector(".sr").textContent = `${word}: `;
  }
}

// -- <rabbit-choices label="...">: numbered options; click one, or type its number ---------------------------
class RabbitChoices extends HTMLElement {
  constructor() {
    super();
    this.root = shadow(this, {
      style: `
        ol { list-style: none; margin: 0.5em 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: 0.5em; }
        button { text-align: start; }
        .n { font-weight: 800; margin-inline-end: 0.4em; }`,
      body: `<ol role="group"></ol>`,
    });
    this.list = this.root.querySelector("ol");
    this._choices = [];
    this.addEventListener("keydown", (event) => {
      const number = Number(event.key);
      if (Number.isInteger(number) && number >= 1 && number <= this._choices.length) {
        event.preventDefault();
        this.choose(number);
      }
    });
  }

  connectedCallback() {
    this.list.setAttribute("aria-label", this.getAttribute("label") || "Choices");
  }

  get choices() {
    return [...this._choices];
  }

  set choices(labels) {
    this._choices = Array.from(labels || [], String);
    this.list.replaceChildren(...this._choices.map((label, i) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      const number = document.createElement("span");
      number.className = "n";
      number.textContent = `${i + 1}.`;
      button.append(number, document.createTextNode(label));
      button.addEventListener("click", () => this.choose(i + 1));
      item.append(button);
      return item;
    }));
  }

  choose(number) {
    this.dispatchEvent(new CustomEvent("rabbit-choose", {
      detail: { number, label: this._choices[number - 1] }, bubbles: true, composed: true,
    }));
  }
}

// -- <rabbit-dialog>: a yes/no question. await dialog.ask("Send it?") -> true/false ---------------------------
class RabbitDialog extends HTMLElement {
  constructor() {
    super();
    this.root = shadow(this, {
      style: `
        dialog { border: 3px solid var(--rabbit-accent); border-radius: var(--rabbit-radius); max-width: 36em;
                 background: var(--rabbit-surface); color: var(--rabbit-text); padding: calc(var(--rabbit-space) * 1.5); }
        dialog::backdrop { background: rgb(0 0 0 / 0.55); }
        p { margin: 0 0 1em; white-space: pre-wrap; }
        .row { display: flex; gap: 0.75em; justify-content: flex-end; }
        .yes { background: var(--rabbit-accent); color: var(--rabbit-accent-text); }`,
      body: `
        <dialog role="alertdialog" aria-labelledby="q" aria-modal="true">
          <p id="q"></p>
          <div class="row"><button class="no" type="button">No</button><button class="yes" type="button">Yes</button></div>
        </dialog>`,
    });
    this.dialog = this.root.querySelector("dialog");
    this.root.querySelector(".yes").addEventListener("click", () => this._answer(true));
    this.root.querySelector(".no").addEventListener("click", () => this._answer(false));
    this.dialog.addEventListener("cancel", (event) => { event.preventDefault(); this._answer(false); });  // Esc = No
  }

  ask(question) {
    this.root.getElementById("q").textContent = question;
    this.dialog.showModal();
    this.root.querySelector(".no").focus();       // the safe answer has focus first
    return new Promise((resolve) => { this._resolve = resolve; });
  }

  _answer(yes) {
    this.dialog.close();
    this.dispatchEvent(new CustomEvent("rabbit-answer", { detail: { yes }, bubbles: true, composed: true }));
    this._resolve?.(yes);
    this._resolve = null;
  }
}

// -- <rabbit-chat name="RabbitSoftware.inc">: the conversation; chat.add("rabbit", text, {choices}) ------------
class RabbitChat extends HTMLElement {
  constructor() {
    super();
    this.root = shadow(this, {
      style: `
        :host { display: block; }
        .log { display: flex; flex-direction: column; gap: 0.75em; }
        .msg { max-width: 46em; padding: 0.7em 1em; border-radius: var(--rabbit-radius);
               border: 2px solid var(--rabbit-border); background: var(--rabbit-surface); }
        .msg.you { align-self: flex-end; background: var(--rabbit-you); }
        .who { font-weight: 700; font-size: 0.85em; color: var(--rabbit-muted); }
        .text { white-space: pre-wrap; overflow-wrap: anywhere; }`,
      body: `<div class="log" role="log" aria-live="polite" aria-relevant="additions"></div>`,
    });
    this.log = this.root.querySelector(".log");
  }

  connectedCallback() {
    this.log.setAttribute("aria-label", `Conversation with ${this.getAttribute("name") || "RabbitSoftware.inc"}`);
  }

  add(who, text, { choices = [] } = {}) {
    const message = document.createElement("div");
    message.className = `msg ${who === "you" ? "you" : "rabbit"}`;
    const label = document.createElement("div");
    label.className = "who";
    label.textContent = who === "you" ? "You" : (this.getAttribute("name") || "RabbitSoftware.inc");
    const body = document.createElement("div");
    body.className = "text";
    body.textContent = String(text);
    message.append(label, body);
    if (choices.length) {
      const options = document.createElement("rabbit-choices");
      options.setAttribute("label", "Options for this answer");
      options.choices = choices;
      message.append(options);
    }
    this.log.append(message);
    message.scrollIntoView({ block: "end", behavior: "smooth" });
    return message;
  }

  clear() {
    this.log.replaceChildren();
  }
}

const COMPONENTS = {
  "rabbit-button": RabbitButton, "rabbit-card": RabbitCard, "rabbit-status": RabbitStatus,
  "rabbit-choices": RabbitChoices, "rabbit-dialog": RabbitDialog, "rabbit-chat": RabbitChat,
};
for (const [name, component] of Object.entries(COMPONENTS)) {
  if (!customElements.get(name)) customElements.define(name, component);
}
settings.apply();

export { COMPONENTS, MODES };
