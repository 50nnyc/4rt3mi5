/* 4rt3mi5 — idiomas (0.19.0).
   O app é escrito em português do Brasil. Este arquivo traduz o que aparece na tela usando os
   dicionários i18n-<idioma>.json: { "texto em português": "tradução" }. Onde o texto tem valor
   dinâmico (número, nome, data) a chave usa {0}, {1}…: "Sessões enviadas ({0})".
   Traduz também o que o app desenha depois (MutationObserver), os avisos alert/confirm/prompt,
   o card de compartilhar (canvas) e os números/datas formatados com "pt-BR".
   Fica de fora: elementos com data-i18n-skip ou translate="no", caixas de texto e o que a pessoa digita. */
const I18N = (() => {
  const LANGS = [
    // tag curta no lugar da bandeira: o Windows não desenha bandeiras em emoji
    { code: "pt-BR", name: "Português (Brasil)", tag: "PT", locale: "pt-BR" },
    { code: "en", name: "English", tag: "EN", locale: "en-US" },
    { code: "es", name: "Español", tag: "ES", locale: "es-ES" },
    { code: "ja", name: "日本語", tag: "JA", locale: "ja-JP" },
    // 0.20.0
    { code: "de", name: "Deutsch", tag: "DE", locale: "de-DE" },
    { code: "pl", name: "Polski", tag: "PL", locale: "pl-PL" },
    { code: "fr", name: "Français", tag: "FR", locale: "fr-FR" },
    { code: "ru", name: "Русский", tag: "RU", locale: "ru-RU" },
  ];
  const ATTRS = ["placeholder", "title", "aria-label", "alt"];
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT", "CODE", "PRE", "NOSCRIPT", "CANVAS", "SVG"]);
  // só a escolha feita pela pessoa fica salva (0.19.1); "lang" era gravado até sem escolher
  const STORE = "idioma";
  try { localStorage.removeItem("lang"); } catch {}
  const PH = /\{(\d+)\}/g;

  let lang = "pt-BR";
  let exact = new Map();
  let patterns = [];
  const textMem = new WeakMap(); // nó de texto -> { pt, out }
  const attrMem = new WeakMap(); // elemento -> { atributo: { pt, out } }
  const cache = {};              // dicionários já baixados
  const listeners = [];

  const norm = (s) => s.replace(/\s+/g, " ").trim();
  const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const info = (code) => LANGS.find((l) => l.code === code) || LANGS[0];

  function compile(dict) {
    exact = new Map();
    patterns = [];
    for (const [k, v] of Object.entries(dict || {})) {
      if (typeof v !== "string" || !v || k.startsWith("//")) continue;
      if (!/\{\d+\}/.test(k)) { exact.set(k, v); continue; }
      const order = [...k.matchAll(PH)].map((m) => m[1]);
      const re = new RegExp("^" + k.split(/\{\d+\}/).map(escRe).join("([\\s\\S]+?)") + "$");
      const weight = k.replace(PH, "").replace(/\s/g, "").length;
      patterns.push({ re, v, order, weight, numeric: weight < 6 });
    }
    patterns.sort((a, b) => b.weight - a.weight); // o mais específico primeiro
  }

  // Valor que entra no lugar de {n}: padrão curto ("{0} dias") só aceita número; os outros
  // nunca atravessam frase ("… por dezenas de antivírus" não é "{0} de {1}").
  const NUMERIC = /^[~+−\-]?[\d\s.,:%hk~+−\-]+$/;
  const okValue = (v, numeric) => v.length <= 90 && !/[.!?…]\s/.test(v) && (!numeric || NUMERIC.test(v));

  /** Traduz um texto inteiro; devolve o mesmo texto se não houver tradução. */
  function t(s, depth = 0) {
    if (lang === "pt-BR" || s == null) return s;
    s = String(s);
    const n = norm(s);
    if (!n) return s;
    let out = exact.get(n);
    if (out === undefined && depth < 3) {
      for (const p of patterns) {
        const m = p.re.exec(n);
        if (!m) continue;
        const caps = m.slice(1);
        if (!caps.every((c) => okValue(c, p.numeric))) continue;
        const vals = {};
        p.order.forEach((id, i) => { vals[id] = caps[i]; });
        out = p.v.replace(PH, (_, id) => (vals[id] === undefined ? "" : t(vals[id], depth + 1)));
        break;
      }
    }
    if (out === undefined) return s;
    return s.match(/^\s*/)[0] + out + s.match(/\s*$/)[0];
  }

  function skipEl(el) {
    return SKIP_TAGS.has(el.tagName) || el.isContentEditable || el.hasAttribute("data-i18n-skip") || el.getAttribute("translate") === "no";
  }

  function doText(node) {
    const cur = node.nodeValue;
    let mem = textMem.get(node);
    if (!mem || cur !== mem.out) mem = { pt: cur, out: cur }; // o app trocou o texto: esse é o novo original
    const out = t(mem.pt);
    mem.out = out;
    textMem.set(node, mem);
    if (cur !== out) node.nodeValue = out;
  }

  function doAttrs(el) {
    let mem = attrMem.get(el);
    for (const a of ATTRS) {
      if (!el.hasAttribute(a)) continue;
      const cur = el.getAttribute(a);
      mem = mem || {};
      let m = mem[a];
      if (!m || cur !== m.out) m = { pt: cur, out: cur };
      m.out = t(m.pt);
      mem[a] = m;
      if (cur !== m.out) el.setAttribute(a, m.out);
    }
    if (mem) attrMem.set(el, mem);
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) {
      const p = root.parentElement;
      if (p && !p.closest("[data-i18n-skip],[translate=no]") && !skipEl(p)) doText(root);
      return;
    }
    if (root.nodeType !== 1 && root.nodeType !== 9) return;
    if (root.nodeType === 1) {
      if (root.closest("[data-i18n-skip],[translate=no]")) return;
      if (skipEl(root)) { doAttrs(root); return; } // input/textarea: só o placeholder
      doAttrs(root);
    }
    const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        if (n.nodeType === 1) {
          if (n.hasAttribute("data-i18n-skip") || n.getAttribute("translate") === "no") return NodeFilter.FILTER_REJECT;
          if (skipEl(n)) { doAttrs(n); return NodeFilter.FILTER_REJECT; }
          return NodeFilter.FILTER_ACCEPT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    let n;
    while ((n = w.nextNode())) {
      if (n.nodeType === 3) doText(n); else doAttrs(n);
    }
  }

  const observer = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === "characterData") walk(r.target);
      else if (r.type === "attributes") { if (r.target.nodeType === 1 && !r.target.closest("[data-i18n-skip],[translate=no]")) doAttrs(r.target); }
      else r.addedNodes.forEach(walk);
    }
  });

  function applyAll() {
    document.documentElement.lang = lang;
    if (!applyAll.title) applyAll.title = document.title;
    document.title = t(applyAll.title);
    walk(document.body);
  }

  async function load(code) {
    if (code === "pt-BR") return {};
    if (cache[code]) return cache[code];
    const r = await fetch(`i18n-${code}.json`, { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    cache[code] = await r.json();
    return cache[code];
  }

  /** Troca o idioma do app inteiro, na hora. */
  async function use(code) {
    code = info(code).code;
    try {
      compile(await load(code));
    } catch {
      code = "pt-BR"; compile({}); // sem dicionário (offline?): fica em português
    }
    lang = code;
    if (document.body) applyAll();
    listeners.forEach((fn) => { try { fn(code); } catch {} });
    return code;
  }

  /** Idioma inicial: o que a pessoa escolheu neste aparelho; sem escolha, sempre português (Brasil). */
  function guess() {
    try { const s = localStorage.getItem(STORE); if (s && LANGS.some((l) => l.code === s)) return s; } catch {}
    return "pt-BR";
  }
  /** Guarda a escolha feita nos botões de idioma. */
  function save(code) {
    try { localStorage.setItem(STORE, code); } catch {}
  }

  // ---------- fora do DOM: avisos, canvas, números e datas ----------
  const _alert = window.alert.bind(window), _confirm = window.confirm.bind(window), _prompt = window.prompt.bind(window);
  window.alert = (m) => _alert(t(m == null ? "" : String(m)));
  window.confirm = (m) => _confirm(t(m == null ? "" : String(m)));
  window.prompt = (m, d) => _prompt(t(m == null ? "" : String(m)), d);
  const C2D = window.CanvasRenderingContext2D && CanvasRenderingContext2D.prototype;
  if (C2D) {
    const _fill = C2D.fillText, _measure = C2D.measureText;
    C2D.fillText = function (s, ...rest) { return _fill.call(this, t(String(s)), ...rest); };
    C2D.measureText = function (s) { return _measure.call(this, t(String(s))); };
  }
  // o app formata com "pt-BR"; em outro idioma vira o formato de lá (1,234 / 1.234 / 1/2/2026…)
  const loc = (l) => (l === "pt-BR" && lang !== "pt-BR" ? info(lang).locale : l);
  for (const [proto, names] of [[Number.prototype, ["toLocaleString"]], [Date.prototype, ["toLocaleString", "toLocaleDateString", "toLocaleTimeString"]]]) {
    for (const nm of names) {
      const orig = proto[nm];
      proto[nm] = function (l, o) { return orig.call(this, loc(l), o); };
    }
  }

  function start() {
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    use(guess());
  }
  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);

  /** Botões de idioma (bandeira + nome no próprio idioma). */
  function picker(el, onPick) {
    el.setAttribute("data-i18n-skip", "");
    el.innerHTML = LANGS.map((l) => `<button type="button" data-lang="${l.code}" class="${l.code === lang ? "on" : ""}">`
      + `<span class="tag" aria-hidden="true">${l.tag}</span><span lang="${l.code}">${l.name}</span></button>`).join("");
    el.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", async () => {
      const code = await use(b.dataset.lang);
      save(code);
      el.querySelectorAll("[data-lang]").forEach((x) => x.classList.toggle("on", x.dataset.lang === code));
      if (onPick) onPick(code);
    }));
    onChange((code) => el.querySelectorAll("[data-lang]").forEach((x) => x.classList.toggle("on", x.dataset.lang === code)));
  }
  function onChange(fn) { listeners.push(fn); }

  return { LANGS, STORE, t, use, guess, save, picker, onChange, get lang() { return lang; }, get locale() { return info(lang).locale; } };
})();
