/* 0.29.0: página do link público de um lootsplit. Tudo entra na tela por textContent (nada de HTML vindo do servidor). */
(function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n) => Number(n || 0).toLocaleString("pt-BR");
  const token = location.pathname.split("/").filter(Boolean).pop() || "";
  let data = null, who = null;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function copyBtn(text) {
    const b = el("button", "btn2", "Copiar");
    b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(text); b.textContent = "Copiado ✔"; setTimeout(() => (b.textContent = "Copiar"), 1500); }
      catch { b.textContent = "Não deu para copiar"; }
    });
    return b;
  }
  function dur(s) { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? `${h}h${String(m).padStart(2, "0")}` : `${m}min`; }

  function paintTxs() {
    const box = $("txs"); box.replaceChildren();
    if (!data.transfers.length) { box.appendChild(el("p", "muted", `Ninguém precisa transferir: todos ficaram com ${fmt(data.profit_each)} gp.`)); }
    for (const t of data.transfers) {
      const tx = el("div", "tx" + (who && (t.payer === who || t.receiver === who) ? " me" : ""));
      const top = el("div", "row");
      const names = el("span"); names.append(el("b", null, t.payer), document.createTextNode(" → "), el("b", null, t.receiver));
      top.append(names, el("b", "gold", fmt(t.amount) + " gp"));
      const bottom = el("div", "row");
      bottom.append(el("code", null, t.command), copyBtn(t.command));
      tx.append(top, bottom, el("div", t.paid ? "pos muted" : "muted", t.paid ? "✔ pago" : "⏳ falta pagar"));
      box.appendChild(tx);
    }
    const pending = data.transfers.filter((t) => !t.paid).length;
    $("paidSummary").textContent = data.transfers.length ? (pending ? `⏳ ${pending} de ${data.transfers.length} transferências ainda não foram pagas.` : "✔ Todas as transferências foram pagas.") : "";
  }
  function paintMine() {
    const box = $("mine");
    if (!who) { box.classList.add("hidden"); return; }
    const pays = data.transfers.filter((t) => t.payer === who), gets = data.transfers.filter((t) => t.receiver === who);
    box.replaceChildren();
    if (pays.length) {
      const pend = pays.filter((t) => !t.paid).reduce((a, t) => a + t.amount, 0);
      box.appendChild(el("b", null, pend ? `Você deve transferir ${fmt(pend)} gp` : "Você já pagou tudo ✔"));
      for (const t of pays) {
        const r = el("div", "row"); r.style.marginTop = "6px";
        r.append(el("span", null, `para ${t.receiver} · ${fmt(t.amount)} gp ${t.paid ? "✔" : ""}`), copyBtn(t.command));
        box.appendChild(r);
      }
    }
    if (gets.length) {
      const pend = gets.filter((t) => !t.paid).reduce((a, t) => a + t.amount, 0);
      box.appendChild(el("b", null, pend ? `Você vai receber ${fmt(pend)} gp` : "Você já recebeu tudo ✔"));
      for (const t of gets) { const r = el("div", "muted", `de ${t.payer} · ${fmt(t.amount)} gp ${t.paid ? "✔" : ""}`); r.style.marginTop = "6px"; box.appendChild(r); }
    }
    if (!pays.length && !gets.length) box.appendChild(el("b", null, "Nada a transferir para você nesta hunt."));
    box.classList.remove("hidden");
  }
  function paintWho() {
    const names = [...new Set(data.transfers.flatMap((t) => [t.payer, t.receiver]))];
    const box = $("who"); box.replaceChildren();
    if (!names.length) { box.parentElement.classList.add("hidden"); return; }
    for (const n of names) {
      const b = el("button", "chip" + (n === who ? " on" : ""), n);
      b.addEventListener("click", () => { who = who === n ? null : n; paintWho(); paintMine(); paintTxs(); });
      box.appendChild(b);
    }
  }

  async function load() {
    try {
      const r = await fetch("/api/public/split/" + encodeURIComponent(token), { headers: { Accept: "application/json" } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((j && (j.detail || j.message)) || "Não foi possível abrir o link.");
      data = j;
    } catch (err) {
      $("loading").classList.add("hidden");
      $("closedMsg").textContent = String(err.message || err);
      $("closed").classList.remove("hidden");
      return;
    }
    $("loading").classList.add("hidden");
    if (data.kind === "boss") $("title").textContent = "👑 Lootsplit de bosses compartilhado";
    $("meta").textContent = [data.place, new Date(data.started_at).toLocaleDateString("pt-BR"), dur(data.duration_seconds), `${data.players_count} jogadores`].filter(Boolean).join(" · ");
    $("each").textContent = fmt(data.profit_each) + " gp";
    $("perHour").textContent = `${fmt(data.profit_each_per_hour)} gp/h por pessoa`;
    paintWho(); paintTxs();
    $("view").classList.remove("hidden");
  }
  load();
})();
