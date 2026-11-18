/* 4rt3mi5 — página do link de envio (0.23.0).
   Quem recebe o link cola o analyser e o servidor salva para o dono do personagem.
   O código do link fica depois do "#": nunca vai para o servidor no endereço, só no corpo do envio. */
(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => Number(n || 0).toLocaleString("pt-BR");
  const dur = (s) => `${Math.floor((s || 0) / 3600)}h${String(Math.floor(((s || 0) % 3600) / 60)).padStart(2, "0")}`;
  const token = decodeURIComponent((location.hash || "").slice(1)).trim();
  const SCOPE = { solo: "Hunt solo (Stacker)", party: "Lootsplit e sessão da PT", boss: "Bosses" };
  let kind = "hunt", info = null;

  I18N.picker($("#lang"));

  async function post(path, body) {
    let res;
    try {
      res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
    } catch { throw Object.assign(new Error("Sem conexão. Tente de novo."), { status: 0 }); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail;
      throw Object.assign(new Error(typeof d === "object" && d ? d.message : (d || `Erro ${res.status}`)), { status: res.status });
    }
    return data;
  }

  function closed(msg) {
    $("#loading").classList.add("hidden");
    $("#form").classList.add("hidden");
    $("#closed").classList.remove("hidden");
    $("#closedMsg").textContent = msg;
  }

  function paintInfo(info) {
    $("#charName").textContent = info.character;
    const until = new Date(info.expires_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    $("#linkInfo").textContent = `Vale até ${until} · ${info.uses_left} ${info.uses_left === 1 ? "envio restante" : "envios restantes"}`;
    $("#linkScopes").innerHTML = info.scopes.map((s) => `<span class="chip">${esc(SCOPE[s] || s)}</span>`).join("");
    // Hunt x Bosses: só pergunta quando o link aceita os dois
    const both = info.scopes.includes("boss") && (info.scopes.includes("solo") || info.scopes.includes("party"));
    $("#kindSeg").classList.toggle("hidden", !both);
    if (!both) kind = info.scopes.includes("boss") ? "boss" : "hunt";
  }

  async function start() {
    if (!token) return closed("Link de envio incompleto. Copie o link inteiro de novo.");
    try {
      info = await post("/api/link/info", { token });
      $("#loading").classList.add("hidden");
      $("#form").classList.remove("hidden");
      paintInfo(info);
    } catch (e) { closed(e.message); }
  }

  $("#kindSeg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-kind]");
    if (!b) return;
    kind = b.dataset.kind;
    document.querySelectorAll("[data-kind]").forEach((x) => x.classList.toggle("on", x === b));
  });

  $("#pasteBtn").addEventListener("click", async () => {
    try { $("#raw").value = await navigator.clipboard.readText(); }
    catch { $("#err").textContent = "Não deu para ler a área de transferência. Cole com Ctrl+V."; }
  });

  /** Prova de trabalho (o mesmo "não sou um robô" do contato). */
  async function solve(ch) {
    const enc = new TextEncoder();
    const target = ch.challenge;
    for (let n = 0; n <= ch.maxnumber; n++) {
      const h = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(ch.salt + n))))
        .map((b) => b.toString(16).padStart(2, "0")).join("");
      if (h === target) return n;
      if (n % 1500 === 0) $("#capFill").style.width = `${Math.round((n / ch.maxnumber) * 100)}%`;
    }
    return null;
  }

  function savedText(r) {
    const s = r.summary || {};
    // frase inteira por destino: o nome do personagem pode ter espaço (a tradução precisa achar onde ele termina)
    const where = {
      stacker: `Salvo para ${r.character} no Hunt Session Stacker.`, lootsplit: `Salvo para ${r.character} nos lootsplits.`,
      party_session: `Salvo para ${r.character} junto ao lootsplit da PT.`, boss_session: `Salvo para ${r.character} nos bosses.`,
      boss_lootsplit: `Salvo para ${r.character} no lootsplit de bosses.`,
    }[r.saved] || "";
    const nums = s.players ? `${s.players} jogadores · ${fmt(s.profit_each)} gp para cada um`
      : `${dur(s.duration_seconds)} · ${fmt(s.xp)} XP · balance ${fmt(s.balance)} gp`;
    return `<div class="banner ok"><b>${r.created ? "Enviado ✔" : "Isso já estava salvo ✔"}</b>
      <div class="muted" style="margin-top:4px">${esc(where)}</div>
      <div class="muted">${esc(nums)}</div>
      <div class="hint">${r.uses_left === 1 ? "Resta 1 envio neste link." : r.uses_left ? `Restam ${r.uses_left} envios neste link.` : "Este link não tem mais envios."}</div></div>`;
  }

  $("#sendBtn").addEventListener("click", async () => {
    const raw = $("#raw").value.trim();
    $("#err").textContent = "";
    if (!raw) { $("#err").textContent = "Cole o analyser primeiro."; return; }
    if (!(window.crypto && crypto.subtle)) { $("#err").textContent = "Abra este link num navegador atualizado (com https)."; return; }
    const btn = $("#sendBtn");
    btn.disabled = true;
    $("#capBar").classList.remove("hidden"); $("#capMsg").classList.remove("hidden"); $("#capFill").style.width = "0";
    try {
      const ch = await fetch("/api/contact/challenge", { cache: "no-store" }).then((r) => r.json());
      const number = await solve(ch);
      if (number === null) throw new Error("A confirmação de que você não é um robô expirou. Envie de novo.");
      const r = await post("/api/link/send", { token, raw_text: raw, kind,
        captcha: { salt: ch.salt, challenge: ch.challenge, signature: ch.signature, number } });
      $("#result").innerHTML = savedText(r);
      $("#raw").value = "";
      info.uses_left = r.uses_left;
      paintInfo(info);
      if (!r.uses_left) ["#raw", "#pasteBtn", "#sendBtn", "#kindSeg"].forEach((s) => $(s).classList.add("hidden"));
    } catch (e) {
      if (e.status === 410 || e.status === 404) closed(e.message);
      else $("#err").textContent = e.message;
    } finally {
      btn.disabled = false;
      $("#capBar").classList.add("hidden"); $("#capMsg").classList.add("hidden");
    }
  });

  start();
})();
