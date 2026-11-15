/* 4rt3mi5 — script de admin.html (fica fora do HTML para o CSP bloquear qualquer script embutido). */
const SITE = "https://quiver-procedure-resolved.ngrok-free.dev";
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const day = (iso) => new Date(iso).toLocaleDateString("pt-BR");
const daysLeft = (iso) => Math.ceil((new Date(iso) - Date.now()) / 86400000);
const store = { get: (k) => { try { return sessionStorage.getItem(k); } catch { return null; } },
                set: (k, v) => { try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch {} } };
let TOKEN = store.get("admin_token");
let KEYS = [];

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2200);
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); } catch {
    const ta = Object.assign(document.createElement("textarea"), { value: text });
    document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  toast("Copiado!");
}
function inviteText(k) {
  return `🏹 Você foi convidado para testar o 4rt3mi5!\n\n`
    + `O app que ajuda na sua hunt de Tibia: lootsplit da PT, Hunt Session Stacker, metas, rotação de bosses e muito mais.\n\n`
    + `Estamos na fase beta, com a versão quase finalizada. Se achar algum erro ou tiver uma ideia, me conta: sua opinião ajuda a deixar o app pronto.\n\n`
    + `🔑 Seu código de acesso: ${k.key}\n(válido até ${day(k.expires_at)})\n\n`
    + `SITE: ${SITE}`;
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method, headers: { "X-Admin-Token": TOKEN || "", ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { logout("Senha de administrador inválida."); throw new Error("401"); }
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Erro ${res.status}`);
  return data;
}

function logout(msg = "") {
  TOKEN = null; store.set("admin_token", null);
  $("#panel").classList.add("hidden"); $("#logout").classList.add("hidden");
  $("#login").classList.remove("hidden"); $("#loginErr").textContent = msg;
  $("#token").value = ""; $("#token").focus();
}
async function enter() {
  try { KEYS = await api("GET", "/api/admin/keys"); } catch (e) { if (e.message !== "401") $("#loginErr").textContent = e.message; return; }
  $("#login").classList.add("hidden");
  $("#panel").classList.remove("hidden"); $("#logout").classList.remove("hidden");
  render();
  loadStatus();
  loadScreens();
  loadRecovery();
}
async function reload() { KEYS = await api("GET", "/api/admin/keys"); render(); loadStatus(); loadScreens(); loadRecovery(); }

/* 0.16.0: quem pediu ajuda para recuperar o código; o botão abre a conversa no WhatsApp (web ou app) */
function waLink(r, reset = null) {
  // 0.17.0: o número já vem com o código do país (a pessoa escolhe pela bandeira)
  const who = r.username ? `, ${r.username}` : "";
  let msg = r.kind === "login"
    ? `Olá${who}! Aqui é o administrador do 4rt3mi5. Recebi seu pedido de ajuda com a conta/senha.`
    : `Olá${who}! Aqui é o administrador do 4rt3mi5. Recebi seu pedido de recuperação do código de acesso`
      + (r.character ? ` (personagem ${r.character})` : "") + ".";
  if (reset) {
    msg = `Olá! Aqui é o administrador do 4rt3mi5. Sua conta é: ${reset.username}\n`
      + `Código para criar uma nova senha: ${reset.code} (vale ${reset.hours} horas, uma vez só).\n`
      + `No app: Entrar → "Esqueceu conta/senha?" → "Já recebi um código para criar nova senha".`;
  }
  return `https://wa.me/${encodeURIComponent(r.whatsapp)}?text=${encodeURIComponent(msg)}`;
}
async function loadRecovery() {
  let list;
  try { list = await api("GET", "/api/admin/recovery"); } catch { return; }
  $("#recCount").textContent = list.length ? `(${list.length})` : "";
  RECS = list;
  $("#recovery").innerHTML = !list.length ? `<span class="muted">Nenhum pedido aberto.</span>` : list.map((r) => `
    <div class="recItem" data-rec="${r.id}">
      <div><span class="badge ${r.kind === "login" ? "login" : "warn"}">${r.kind === "login" ? "🔐" : "🔑"} ${esc(r.reason_label)}</span>
        <b>${esc(r.username || (r.kind === "login" ? "conta não informada" : "—"))}</b>
        <span class="muted">${esc(when(r.created_at))}</span></div>
      <div class="muted">WhatsApp: <b>+${esc(r.whatsapp)}</b>${r.character ? ` · Personagem: <b>${esc(r.character)}</b>` : ""}
        ${r.char_key ? ` · está na chave <span class="key">${esc(r.char_key)}</span>` : ""}
        ${r.account_key ? ` · chave da conta: <span class="key">${esc(r.account_key)}</span>` : ""}</div>
      ${r.kind === "login" ? `<div class="muted" style="margin-top:4px">${r.candidates.length
          ? "Contas que batem com o que a pessoa lembra:" : "Nenhuma conta bate com o que a pessoa informou. Pergunte no WhatsApp."}</div>
        ${r.candidates.map((c) => `<div class="row" style="margin-top:4px"><b>${esc(c.username)}</b>
          ${c.key ? `<span class="key">${esc(c.key)}</span>` : `<span class="muted">sem chave</span>`}
          <button data-reset-for="${c.id}">Gerar código p/ nova senha</button></div>`).join("")}` : ""}
      <div class="row" style="margin-top:6px">
        <a class="wa" data-wa="${r.id}" href="${esc(waLink(r))}" target="_blank" rel="noopener noreferrer">💬 Abrir conversa no WhatsApp</a>
        <button data-rec-done="${r.id}">✔ Resolvido</button>
      </div>
      <div class="muted" data-reset-out></div>
    </div>`).join("");
}
let RECS = [];
$("#recovery").addEventListener("click", async (e) => {
  const rb = e.target.closest("[data-reset-for]");
  if (rb) {  // 0.17.0: código de uso único; o adm nunca vê nem define a senha da pessoa
    const item = rb.closest("[data-rec]"), r = RECS.find((x) => String(x.id) === item.dataset.rec);
    if (!confirm("Gerar um código para essa conta criar nova senha? Só envie se tiver certeza de que a conta é da pessoa.")) return;
    rb.disabled = true;
    try {
      const reset = await api("POST", `/api/admin/accounts/${rb.dataset.resetFor}/reset-code`);
      item.querySelector("[data-wa]").href = waLink(r, reset);
      item.querySelector("[data-reset-out]").innerHTML = `Código gerado para <b>${esc(reset.username)}</b>:
        <span class="key">${esc(reset.code)}</span> (vale ${reset.hours} h). O botão do WhatsApp já leva a mensagem com o código.`;
    } catch (ex) { rb.disabled = false; if (ex.message !== "401") toast(ex.message); }
    return;
  }
  const b = e.target.closest("[data-rec-done]"); if (!b) return;
  if (!confirm("Marcar este pedido como resolvido? Ele sai da lista.")) return;
  b.disabled = true;
  try { await api("POST", `/api/admin/recovery/${b.dataset.recDone}/done`); toast("Pedido resolvido"); loadRecovery(); }
  catch (ex) { b.disabled = false; if (ex.message !== "401") toast(ex.message); }
});
const when = (iso) => iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
async function loadStatus() {
  let s;
  try { s = await api("GET", "/api/admin/status"); } catch { return; }
  const v = s.vigia;
  const vigia = !v ? `<span class="badge">vigia não instalado</span> <span class="muted">rode <code>vigia.bat</code> uma vez para instalar</span>`
    : v.ok ? `<span class="badge ok">site no ar</span> <span class="muted">conferido ${esc(when(v.checked_at))}</span>`
    : `<span class="badge warn">site fora do ar</span> <span class="muted">${esc(v.message || "")} · desde ${esc(when(v.down_since))}</span>`;
  $("#status").innerHTML = `<div class="grid">
      <div><span class="muted">Vigia do site (ngrok)</span><b>${vigia}</b></div>
      <div><span class="muted">Último backup automático</span><b>${esc(when(s.last_backup))}</b></div>
      <div><span class="muted">Backups guardados</span><b>${s.backups.length} de ${s.keep} (data/backups)</b></div>
      <div><span class="muted">Loja: chave grátis</span><b>${s.store_free ? `<span class="badge ok">ligada</span>` : `<span class="badge warn">pausada</span>`}
        <button id="storeToggle" style="margin-left:6px">${s.store_free ? "Pausar" : "Ligar"}</button></b></div>
    </div>`;
  $("#storeToggle").onclick = async () => {
    try { await api("POST", "/api/admin/store", { on: !s.store_free }); toast(s.store_free ? "Chave grátis pausada" : "Chave grátis ligada"); loadStatus(); } catch {}
  };
}
const PAGE_PT = { home: "🏠 Início", loot: "💰 Lootsplit", stack: "📈 Hunt Session Stacker", boss: "👑 Rotação de bosses", hunts: "🗺️ Hunts",
                  rank: "🥇 Ranking", ach: "🏆 Conquistas", chars: "👤 Meus personagens", news: "📰 Novidades" };
let screenDays = 7;
async function loadScreens() {
  let r;
  try { r = await api("GET", `/api/admin/screens?days=${screenDays}`); } catch { return; }
  if (!r.screens.length) { $("#screens").innerHTML = `<span class="muted">Ninguém abriu o app nesse período (ou a versão nova ainda não foi usada).</span>`; return; }
  $("#screens").innerHTML = `<div class="tablewrap"><table><tr><th>Tela</th><th>Visitas</th><th>Fizeram algo</th><th>Só olharam</th></tr>${r.screens.map((s) => {
    const idle = Math.max(0, s.views - s.actions), pct = s.views ? Math.round(idle * 100 / s.views) : 0;
    return `<tr><td>${esc(PAGE_PT[s.page] || s.page)}</td><td>${s.views}</td><td>${s.actions}</td>
      <td><span class="badge ${pct >= 70 ? "warn" : ""}">${pct}%</span></td></tr>`;
  }).join("")}</table></div>
  <div class="muted" style="margin-top:8px">Contagem por tela, sem dizer quem. "Fizeram algo" = tocaram em botão, campo ou colaram texto na tela.</div>`;
}
$("#screenDays").addEventListener("click", (e) => {
  const b = e.target.closest("[data-days]"); if (!b) return;
  screenDays = +b.dataset.days;
  $("#screenDays").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
  loadScreens();
});
/** Códigos que vencem em até 7 dias, para renovar a tempo. */
function expiringBlock() {
  const soon = KEYS.filter((k) => !k.lifetime && daysLeft(k.expires_at) <= 7).sort((a, b) => a.expires_at.localeCompare(b.expires_at));
  if (!soon.length) return "";
  return `<h2>Vencem nesta semana (${soon.length})</h2><div class="card">${soon.map((k) => {
    const left = daysLeft(k.expires_at);
    return `<div class="row" style="padding:4px 0"><span class="key" style="font-size:14px">${esc(k.key)}</span>
      <b>${esc(k.label || k.main_char || "—")}</b>
      <span class="badge ${left <= 3 ? "warn" : ""}">vence em ${left} dia${left === 1 ? "" : "s"} (${day(k.expires_at)})</span>
      <span class="muted">último uso: ${esc(lastUse(k))}</span></div>`;
  }).join("")}</div>`;
}
function lastUse(k) {
  if (!k.last_seen) return "nunca";
  const d = Math.floor((Date.now() - new Date(k.last_seen)) / 86400000);
  return d <= 0 ? "hoje" : d === 1 ? "ontem" : `há ${d} dias`;
}

function keyCard(k) {
  const left = daysLeft(k.expires_at);
  const status = k.trusted ? `<span class="badge trust">contato de confiança</span>`
    : k.main_char ? `<span class="badge ok">verificado</span>` : `<span class="badge">aguardando 1º acesso</span>`;
  const chars = k.chars.map((c) => esc(c.name) + (c.is_main ? " (main)" : "")).join(", ") || "—";
  return `<div class="card" data-key="${esc(k.key)}">
    <div class="row">
      <span class="key">${esc(k.key)}</span>
      <button data-act="copy-key">Copiar código</button>
      <button data-act="copy-invite">Copiar convite</button>
      <span style="margin-left:auto" class="row">${status}
        ${k.lifetime ? `<span class="badge life">⭐ amigo do adm · vitalício</span>`
          : left <= 0 ? `<span class="badge warn">vencida (a conta pode renovar)</span>`
          : `<span class="badge ${left <= 3 ? "warn" : ""}">vence em ${left} dia${left === 1 ? "" : "s"}</span>`}</span>
    </div>
    <div class="grid">
      <div><span class="muted">Para</span><b>${esc(k.label || "—")}</b></div>
      <div><span class="muted">Conta</span><b>${esc(k.account || "—")}</b></div>
      <div><span class="muted">Main</span><b>${esc(k.main_char || "—")}</b></div>
      <div><span class="muted">Personagens</span><b>${chars}</b></div>
      <div><span class="muted">Vence em</span><b>${k.lifetime ? "nunca" : day(k.expires_at)}</b></div>
      <div><span class="muted">Aparelhos liberados</span><b>${k.devices}</b></div>
      <div><span class="muted">Último uso</span><b>${esc(lastUse(k))}</b></div>
      <div><span class="muted">Entradas (7 dias)</span><b>${k.logins_7d} <button data-act="logins" style="padding:2px 8px; font-size:12px">ver histórico</button></b></div>
      <div><span class="muted">Criado em</span><b>${day(k.created_at)}</b></div>
    </div>
    <div class="logins hidden" data-logins></div>
    <div class="actions">
      ${k.lifetime ? "" : `<div class="row"><span class="muted" style="width:150px">Renovar a partir de hoje</span>
        <button data-act="renew" data-days="7">7 dias</button><button data-act="renew" data-days="15">15 dias</button><button data-act="renew" data-days="30">30 dias</button></div>`}
      <div class="row"><span class="muted" style="width:150px">Amigo do adm</span>
        <button data-act="lifetime">${k.lifetime ? "Tirar vitalício" : "⭐ Tornar vitalício"}</button>
        <span class="muted">${k.lifetime ? "Nunca vence; a pessoa não vê data de vencimento." : "O código nunca vence e a data some para a pessoa."}</span></div>
      <div class="row"><span class="muted" style="width:150px">Validar personagem</span>
        <input class="grow" data-input="char" placeholder="Nick do personagem" value="" style="max-width:280px">
        <button data-act="add-char">Adicionar sem verificação</button>
        <span class="muted">${k.chars.length}/50</span></div>
      <div class="row"><span class="muted" style="width:150px">Forçar main (confiança)</span>
        <input class="grow" data-input="main" placeholder="Nick do main character" value="" style="max-width:280px">
        <button data-act="trust">Definir main sem verificação</button>
        ${k.trusted ? `<button data-act="untrust">Remover confiança</button>` : ""}</div>
      <div class="row"><span class="muted" style="width:150px">Outros</span>
        <button data-act="reset">Resetar dono</button><button data-act="revoke" class="danger">Apagar código</button></div>
      <div class="err" data-err></div>
    </div>
  </div>`;
}

function render() {
  const q = $("#filter").value.trim().toLowerCase();
  const shown = KEYS.filter((k) => !q || [k.key, k.label, k.main_char, k.account, ...k.chars.map((c) => c.name)].join(" ").toLowerCase().includes(q));
  $("#count").textContent = `(${KEYS.length})`;
  $("#expiring").innerHTML = expiringBlock();
  $("#list").innerHTML = shown.map(keyCard).join("") || `<p class="muted">Nenhum código ${q ? "encontrado" : "válido no momento"}.</p>`;
}

$("#loginForm").addEventListener("submit", (e) => {
  e.preventDefault();
  TOKEN = $("#token").value.trim(); store.set("admin_token", TOKEN); $("#loginErr").textContent = ""; enter();
});
$("#logout").addEventListener("click", () => logout());
$("#refresh").addEventListener("click", () => reload().then(() => toast("Atualizado")));
$("#filter").addEventListener("input", render);
$("#createForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.currentTarget.querySelector(".primary"); btn.disabled = true; $("#createErr").textContent = "";
  try {
    const k = await api("POST", "/api/admin/keys", { label: $("#label").value });
    $("#label").value = "";
    $("#created").innerHTML = `<div class="card created" style="margin:12px 0 0">
      <div class="muted">Código criado para ${esc(k.label || "—")} · vale até ${day(k.expires_at)}</div>
      <div class="row" style="margin-top:6px"><span class="key">${esc(k.key)}</span>
        <button id="cKey">Copiar código</button><button id="cInv" class="primary">Copiar convite</button></div></div>`;
    $("#cKey").onclick = () => copy(k.key);
    $("#cInv").onclick = () => copy(inviteText(k));
    await reload();
  } catch (err) { if (err.message !== "401") $("#createErr").textContent = err.message; }
  finally { btn.disabled = false; }
});

$("#renewAll").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-days]"); if (!b) return;
  const days = +b.dataset.days; $("#renewAllErr").textContent = "";
  const fewer = KEYS.filter((k) => !k.lifetime && new Date(k.expires_at) < Date.now() + days * 86400000).length;
  if (!fewer) { toast(`Todos já têm ${days} dias ou mais`); return; }
  if (!confirm(`Completar para ${days} dias os ${fewer} código${fewer === 1 ? "" : "s"} que têm menos que isso?\n\nQuem já tem mais dias (e os vitalícios) não muda.`)) return;
  b.disabled = true;
  try { const r = await api("POST", "/api/admin/keys/renew-all", { days }); toast(`${r.renewed} código${r.renewed === 1 ? "" : "s"} renovado${r.renewed === 1 ? "" : "s"}`); await reload(); }
  catch (ex) { if (ex.message !== "401") $("#renewAllErr").textContent = ex.message; }
  finally { b.disabled = false; }
});

$("#list").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  const card = b.closest("[data-key]"), key = card.dataset.key, k = KEYS.find((x) => x.key === key);
  const err = $("[data-err]", card); err.textContent = "";
  const act = b.dataset.act;
  try {
    if (act === "copy-key") return copy(key);
    if (act === "copy-invite") return copy(inviteText(k));
    if (act === "logins") {
      const box = $("[data-logins]", card);
      if (!box.classList.contains("hidden")) { box.classList.add("hidden"); return; }
      const list = await api("GET", `/api/admin/keys/${key}/logins`);
      box.innerHTML = list.length ? `<b>Últimas entradas</b> (aberturas com 30 min de intervalo contam uma vez):<br>`
        + list.map((x) => `${esc(when(x.at))} · ${x.client === "app" ? "app Windows" : "site"}`).join("<br>")
        : "Nenhuma entrada registrada ainda (o histórico começou na versão 0.13.0).";
      box.classList.remove("hidden");
      return;
    }
    b.disabled = true;
    if (act === "lifetime") {
      const on = !k.lifetime;
      if (!confirm(on ? `Tornar ${key} vitalício (amigo do adm)? Ele nunca mais vence.`
                      : `Tirar o vitalício de ${key}? Ele volta a ter vencimento (se já passou, ganha 7 dias).`)) return;
      await api("POST", `/api/admin/keys/${key}/lifetime`, { on }); toast(on ? "⭐ Agora é vitalício" : "Vitalício removido");
    }
    if (act === "renew") { const r = await api("POST", `/api/admin/keys/${key}/renew`, { days: +b.dataset.days }); toast(`Renovado até ${day(r.expires_at)}`); }
    if (act === "trust") {
      const name = $("[data-input=main]", card).value.trim();
      if (!name) { err.textContent = "Digite o nick do main character."; return; }
      const r = await api("POST", `/api/admin/keys/${key}/trust`, { character: name });
      toast(`${r.main_char} definido como main (confiança)`);
    }
    if (act === "add-char") {
      const name = $("[data-input=char]", card).value.trim();
      if (!name) { err.textContent = "Digite o nick do personagem."; return; }
      const r = await api("POST", `/api/admin/keys/${key}/chars`, { character: name });
      toast(`${r.character} adicionado à chave`);
    }
    if (act === "untrust") { await api("POST", `/api/admin/keys/${key}/untrust`); toast("Confiança removida"); }
    if (act === "reset" && confirm(`Resetar o dono de ${key}? Personagens e aparelhos serão desvinculados e a pessoa precisará verificar de novo.`)) {
      await api("POST", `/api/admin/keys/${key}/reset`); toast("Dono resetado");
    }
    if (act === "revoke" && confirm(`Apagar o código ${key}? Quem usa este código perde o acesso na hora.`)) {
      await api("DELETE", `/api/admin/keys/${key}`); toast("Código apagado");
    }
    await reload();
  } catch (ex) { if (ex.message !== "401") err.textContent = ex.message; }
  finally { b.disabled = false; }
});

if (TOKEN) enter(); else logout();
