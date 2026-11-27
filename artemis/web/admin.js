/* 4rt3mi5 — script de admin.html (fica fora do HTML para o CSP bloquear qualquer script embutido). */
const SITE = "https://artemishunt.com.br";
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
    + `🔑 Seu código de acesso: ${k.key}\n\n`
    + `SITE: ${SITE}`;
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method, headers: { "X-Admin-Token": TOKEN || "", ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { logout("Senha de administrador inválida."); throw new Error("401"); }
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : (data.detail && data.detail.message) || `Erro ${res.status}`);
  return data;
}

function logout(msg = "") {
  TOKEN = null; store.set("admin_token", null);
  $("#panel").classList.add("hidden"); $("#logout").classList.add("hidden");
  $("#login").classList.remove("hidden"); $("#loginErr").textContent = msg;
  $("#token").value = ""; $("#token").focus();
}
async function enter() {
  try { KEYS = await api("GET", "/api/admin/keys"); } catch (e) {
    if (e.message === "401") return;
    // Falha que não é senha errada (túnel fechado, servidor reiniciando): mostra o login com o erro
    // e a senha já preenchida, senão a tela fica só com o cabeçalho.
    const net = e instanceof TypeError;
    $("#panel").classList.add("hidden"); $("#logout").classList.add("hidden");
    $("#login").classList.remove("hidden");
    $("#token").value = TOKEN || "";
    $("#loginErr").textContent = net
      ? "Não consegui falar com o servidor. O túnel (deploy\\painel-vm.bat) está aberto? Depois clique em Entrar."
      : e.message;
    return;
  }
  $("#login").classList.add("hidden");
  $("#panel").classList.remove("hidden"); $("#logout").classList.remove("hidden");
  render();
  loadStatus();
  loadScreens();
  loadRecovery();
  loadContacts();
  loadReport();
  loadCalendar();
}
async function reload() { KEYS = await api("GET", "/api/admin/keys"); render(); loadStatus(); loadScreens(); loadRecovery(); loadContacts(); loadReport(); loadCalendar(); loadScan(); }

// 0.26.0: tempos da varredura (primeira carga, última e média) e as execuções recentes
const fmtSec = (s) => (s == null ? "–" : s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min` : s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`);
async function loadScan() {
  const el = $("#scan");
  let d;
  try { d = await api("GET", "/api/admin/scan-stats"); } catch { return; }
  const f = d.first_load, l = d.last;
  el.innerHTML = `
    <div class="row" style="flex-wrap:wrap;gap:18px">
      <div><div class="muted">Primeira carga</div><b>${f ? fmtSec(f.seconds) : "ainda não rodou"}</b></div>
      <div><div class="muted">Última atualização</div><b>${l ? fmtSec(l.seconds) : "–"}</b></div>
      <div><div class="muted">Média</div><b>${fmtSec(d.avg_seconds)}</b></div>
      <div><div class="muted">Acompanhados</div><b>${d.tracked_players}</b></div>
      <div><div class="muted">Agenda</div><b>todo dia às ${String(d.schedule.hour).padStart(2, "0")}h (Brasília)</b></div>
    </div>
    ${l ? `<div class="hint">Última: ${esc(l.started_at)} · ${l.requests} consultas · ${l.errors} erros · ${l.worlds} mundos · ${l.matched} encontrados · ${l.changes} mudanças · ${l.world_changes} trocas de mundo</div>` : ""}
    <div class="table-wrap" style="margin-top:10px"><table><tr><th>Dia</th><th>Tempo</th><th>Consultas</th><th>Erros</th><th>Mudanças</th><th>Trocas</th><th>Status</th></tr>
      ${d.runs.map((r) => `<tr><td>${esc(r.started_at)}${r.first_load ? " · 1ª carga" : ""}</td><td>${fmtSec(r.seconds)}</td><td>${r.requests}</td><td>${r.errors}</td><td>${r.changes}</td><td>${r.world_changes}</td><td>${r.ok ? "ok" : esc(r.note || "falhou")}</td></tr>`).join("")}
    </table></div>`;
}

/* 0.22.1: 📅 calendário do Tibia (HTML do Event Schedule colado daqui; o servidor guarda só os dados) */
async function loadCalendar() {
  let rows;
  try { rows = await api("GET", "/api/admin/calendar"); } catch { return; }
  $("#calMonths").innerHTML = rows.length
    ? `<table><tr><th>Mês</th><th>Colagens</th><th>Última</th><th></th></tr>${rows.map((r) => `<tr><td>${esc(r.month)}</td><td>${r.versions}</td>
        <td>${esc(new Date(r.updated_at).toLocaleString("pt-BR"))}</td><td><button class="danger" data-cal-undo="${esc(r.month)}">Desfazer última</button></td></tr>`).join("")}</table>`
    : `<span class="muted">Nenhum calendário publicado ainda.</span>`;
}
$("#calSave").addEventListener("click", async () => {
  const raw = $("#calHtml").value.trim(), btn = $("#calSave");
  $("#calErr").textContent = ""; $("#calMsg").textContent = "";
  if (!raw) { $("#calErr").textContent = "Cole o HTML do Event Schedule primeiro."; return; }
  btn.disabled = true;
  try {
    const r = await api("POST", "/api/admin/calendar", { raw_html: raw });
    $("#calHtml").value = "";
    $("#calMsg").textContent = `✔ ${r.month} publicado: ${r.events.length} eventos (${r.events.join(", ")}), ${r.days_with_events} dias com evento.`;
    loadCalendar();
  } catch (e) { if (e.message !== "401") $("#calErr").textContent = e.message; }
  finally { btn.disabled = false; }
});
$("#calMonths").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-cal-undo]");
  if (!b || !confirm(`Desfazer a última colagem de ${b.dataset.calUndo}? Volta a valer a anterior (se houver).`)) return;
  try { await api("DELETE", `/api/admin/calendar/${b.dataset.calUndo}`); toast("Última colagem desfeita"); loadCalendar(); }
  catch (err) { if (err.message !== "401") toast(err.message); }
});

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
                  rank: "🥇 Ranking", ach: "🏆 Conquistas", chars: "👤 Meus personagens", news: "📰 Novidades", settings: "⚙️ Configurações",
                  download: "💻 App para Windows", subs: "🤝 Substituições", parties: "🛡️ Minhas parties e cofre", gear: "⚔️ Equipamentos",
                  reports: "📑 Relatórios", vip: "⭐ VIP List", tnews: "📰 Novidades do Tibia", cms: "💬 CMs", cal: "📅 Calendário" };

/* ---------- 0.21.0: mensagens da tela de contato ---------- */
async function loadContacts() {
  let r;
  try { r = await api("GET", "/api/admin/contacts"); } catch { return; }
  $("#contactCount").textContent = r.unread ? `(${r.unread} nova${r.unread > 1 ? "s" : ""})` : "";
  const head = `<div class="muted" style="margin-bottom:6px">Endereço na tela: <b>${esc(r.to)}</b> ·
    ${r.email_on ? `<span class="badge ok">e-mail ligado</span>` : `<span class="badge warn">e-mail desligado</span> (faltam ARTEMIS_SMTP_USER e ARTEMIS_SMTP_PASSWORD no .env; as mensagens ficam só aqui)`}
    · robôs barrados pelo campo escondido: <b>${r.robots}</b></div>`;
  if (!r.messages.length) { $("#contacts").innerHTML = head + `<span class="muted">Nenhuma mensagem ainda.</span>`; return; }
  $("#contacts").innerHTML = head + r.messages.map((m) => `<div class="msg ${m.read_at ? "" : "unread"}">
      <div class="row"><b>${esc(m.subject || "(sem assunto)")}</b>
        <span class="muted">${esc(new Date(m.created_at).toLocaleString("pt-BR"))} · ${esc(m.lang)}</span>
        ${m.sent ? `<span class="badge ok">enviado por e-mail</span>` : `<span class="badge">só no painel</span>`}</div>
      <div class="muted">De: <a href="mailto:${esc(m.email)}" style="color:var(--accent)">${esc(m.email)}</a></div>
      <pre>${esc(m.message)}</pre>
      <div class="row"><button data-copy-mail="${esc(m.email)}">Copiar e-mail</button>
        <button data-read="${m.id}" data-on="${m.read_at ? "0" : "1"}">${m.read_at ? "Marcar como não lida" : "Marcar como lida"}</button></div>
    </div>`).join("");
}
$("#contacts").addEventListener("click", async (e) => {
  const c = e.target.closest("[data-copy-mail]");
  if (c) return copy(c.dataset.copyMail);
  const b = e.target.closest("[data-read]");
  if (!b) return;
  try { await api("POST", `/api/admin/contacts/${b.dataset.read}/read`, { on: b.dataset.on === "1" }); loadContacts(); }
  catch (err) { toast(err.message); }
});

/* ---------- 0.21.0: relatório mensal de visitas para a CipSoft (fansites@tibia.com, até o dia 3) ---------- */
const MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
function reportText(r) {
  const [y, m] = r.month.split("-").map(Number);
  const n = (v) => Number(v || 0).toLocaleString("en-US");
  const busiest = r.busiest_day ? `${r.busiest_day.day} (${n(r.busiest_day.views)} page views)` : "-";
  const app = r.active_by_client || {};
  return `Subject: 4rt3mi5 - traffic statistics for ${MONTHS_EN[m - 1]} ${y}\n\n`
    + `Hello Tibia Community Management,\n\n`
    + `here are the traffic statistics of 4rt3mi5 (${SITE}) for ${MONTHS_EN[m - 1]} ${y}:\n\n`
    + `- Unique visitors (website): ${n(r.unique_visitors)}\n`
    + `- Page views (website): ${n(r.page_views)}\n`
    + `- Busiest day: ${busiest}\n`
    + `- Active users (logged in): ${n(r.active_users)}${Object.keys(app).length ? ` (website: ${n(app.site)}, Windows app: ${n(app.app)})` : ""}\n`
    + `- New accounts: ${n(r.new_accounts)}\n`
    + `- Screens opened inside the app: ${n(r.screen_views)}\n`
    + `- Hunt sessions submitted: ${n(r.sessions)}\n`
    + `- Party loot splits submitted: ${n(r.lootsplits)}\n\n`
    + `Unique visitors are counted without cookies and without storing IP addresses.\n\n`
    + `Best regards,\nHilay\n4rt3mi5 - ${SITE}\n`;
}
async function loadReport() {
  const input = $("#reportMonth");
  let r;
  try { r = await api("GET", `/api/admin/report${input.value ? `?month=${input.value}` : ""}`); } catch (err) { $("#report").innerHTML = `<span class="err">${esc(err.message)}</span>`; return; }
  if (!input.value) input.value = r.month;
  const n = (v) => Number(v || 0).toLocaleString("pt-BR");
  $("#report").innerHTML = `<div class="grid">
      <div><span class="muted">Visitantes únicos</span><b>${n(r.unique_visitors)}</b></div>
      <div><span class="muted">Páginas vistas</span><b>${n(r.page_views)}</b></div>
      <div><span class="muted">Usuários ativos</span><b>${n(r.active_users)}</b></div>
      <div><span class="muted">Contas novas</span><b>${n(r.new_accounts)}</b></div>
      <div><span class="muted">Sessões enviadas</span><b>${n(r.sessions)}</b></div>
      <div><span class="muted">Lootsplits</span><b>${n(r.lootsplits)}</b></div>
      <div><span class="muted">Mensagens de contato</span><b>${n(r.contacts)}</b></div>
    </div>
    <textarea class="report" id="reportText" readonly>${esc(reportText(r))}</textarea>
    <div class="row" style="margin-top:8px"><button class="primary" id="reportCopy">Copiar relatório em inglês</button>
      <span class="muted">Mande para <b>fansites@tibia.com</b> até o dia 3 de cada mês (quando o 4rt3mi5 estiver no programa de fansites).</span></div>`;
  $("#reportCopy").addEventListener("click", () => copy($("#reportText").value));
}
$("#reportMonth").addEventListener("change", loadReport);
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
/** 0.20.0: os códigos não vencem mais, então não há lista de "vencem nesta semana". */
function expiringBlock() { return ""; }
const PTYPE_LABEL = { hardcore: "🔥 Player Hardcore", comum: "⚔️ Player Comum", novato: "🌱 Player Novato" };
function lastUse(k) {
  if (!k.last_seen) return "nunca";
  const d = Math.floor((Date.now() - new Date(k.last_seen)) / 86400000);
  return d <= 0 ? "hoje" : d === 1 ? "ontem" : `há ${d} dias`;
}

function keyCard(k) {
  const status = k.trusted ? `<span class="badge trust">contato de confiança</span>`
    : k.main_char ? `<span class="badge ok">verificado</span>` : `<span class="badge">aguardando 1º acesso</span>`;
  // 0.20.0: tocar no personagem mostra as hunts dele (local e trocas)
  const chars = k.chars.map((c) => `<button class="charbtn" data-act="char-hunts" data-char="${esc(c.name)}" title="Ver as hunts de ${esc(c.name)}">${esc(c.name)}${c.is_main ? " (main)" : ""}</button>`).join("") || "—";
  return `<div class="card" data-key="${esc(k.key)}">
    <div class="row">
      <span class="key">${esc(k.key)}</span>
      <button data-act="copy-key">Copiar código</button>
      <button data-act="copy-invite">Copiar convite</button>
      <span style="margin-left:auto" class="row">${status}</span>
    </div>
    <div class="grid">
      <div><span class="muted">Para</span><b>${esc(k.label || "—")}</b></div>
      <div><span class="muted">Conta</span><b>${esc(k.account || "—")}</b></div>
      <div><span class="muted">Main</span><b>${esc(k.main_char || "—")}</b></div>
      <div><span class="muted">Tipo de player</span><b>${esc(PTYPE_LABEL[k.player_type] || "ainda não escolheu")}</b></div>
      <div style="grid-column:1/-1"><span class="muted">Personagens (toque para ver as hunts)</span><div>${chars}</div></div>
      <div><span class="muted">Aparelhos liberados</span><b>${k.devices}</b></div>
      <div><span class="muted">Último uso</span><b>${esc(lastUse(k))}</b></div>
      <div><span class="muted">Entradas (7 dias)</span><b>${k.logins_7d} <button data-act="logins" style="padding:2px 8px; font-size:12px">ver histórico</button></b></div>
      <div><span class="muted">Criado em</span><b>${day(k.created_at)}</b></div>
    </div>
    <div class="logins hidden" data-logins></div>
    <div class="hunts hidden" data-hunts></div>
    <div class="actions">
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
      <div class="muted">Código criado para ${esc(k.label || "—")} · não vence</div>
      <div class="row" style="margin-top:6px"><span class="key">${esc(k.key)}</span>
        <button id="cKey">Copiar código</button><button id="cInv" class="primary">Copiar convite</button></div></div>`;
    $("#cKey").onclick = () => copy(k.key);
    $("#cInv").onclick = () => copy(inviteText(k));
    await reload();
  } catch (err) { if (err.message !== "401") $("#createErr").textContent = err.message; }
  finally { btn.disabled = false; }
});

/* ---------- 0.20.0: hunts do personagem (local da hunt e trocas usadas) ---------- */
let PLACES = null;
const durTxt = (s) => `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`;
async function placeOptions() {
  if (!PLACES) PLACES = await api("GET", "/api/admin/places");
  return PLACES.map((p) => `<option value="${p.id}">${esc(p.name)}${p.city ? " · " + esc(p.city) : ""}</option>`).join("");
}
function huntRow(kind, x, limit, opts) {
  const used = `${x.place_edits}/${limit}`;
  const who = kind === "hunt" ? `<div class="muted">${esc(x.players.join(", "))}</div>` : `<div class="muted">${(x.xp || 0).toLocaleString("pt-BR")} XP</div>`;
  return `<tr data-row="${kind}:${x.id}"><td>${kind === "hunt" ? "💰 Lootsplit" : "📈 Stacker"} · ${esc(when(x.started_at))} · ${durTxt(x.duration_seconds)}${who}</td>
    <td>${x.place ? esc(x.place.name) : `<span class="badge warn">sem local</span>`}</td>
    <td><span class="badge ${x.place_edits >= limit ? "warn" : ""}">${used}</span></td>
    <td><div class="row"><select data-place-select aria-label="Nova hunt"><option value="">Trocar hunt…</option>${opts}</select>
      <button data-place-save>Salvar</button>
      <button data-place-reset ${x.place_edits ? "" : "disabled"} title="A pessoa volta a poder trocar o local ${limit} vezes">Liberar trocas</button></div></td></tr>`;
}
async function showCharHunts(card, name, btn) {
  const box = $("[data-hunts]", card);
  if (box.dataset.char === name && !box.classList.contains("hidden")) { box.classList.add("hidden"); btn.classList.remove("on"); return; }
  card.querySelectorAll(".charbtn").forEach((b) => b.classList.toggle("on", b === btn));
  box.dataset.char = name; box.classList.remove("hidden");
  box.innerHTML = `<span class="muted">Carregando as hunts de ${esc(name)}…</span>`;
  const [d, opts] = await Promise.all([api("GET", `/api/admin/chars/${encodeURIComponent(name)}/hunts`), placeOptions()]);
  const rows = [...d.sessions.map((s) => huntRow("solo", s, d.edit_limit, opts)), ...d.hunts.map((h) => huntRow("hunt", h, d.edit_limit, opts))];
  box.innerHTML = `<b>Hunts de ${esc(d.name)}</b> <span class="muted">(${d.sessions.length} sessões do Stacker · ${d.hunts.length} lootsplits)</span>
    ${rows.length ? `<div class="tablewrap" style="margin-top:6px"><table><tr><th>Hunt</th><th>Local</th><th>Trocas usadas</th><th></th></tr>${rows.join("")}</table></div>
      <div class="muted" style="margin-top:6px">A pessoa troca o local sozinha ${d.edit_limit} vezes. Aqui você troca sem gastar as trocas dela, ou libera as ${d.edit_limit} trocas de novo.</div>`
      : `<div class="muted" style="margin-top:6px">Nenhuma sessão ou lootsplit ainda.</div>`}`;
}
$("#list").addEventListener("click", async (e) => {
  const save = e.target.closest("[data-place-save]"), reset = e.target.closest("[data-place-reset]");
  if (!save && !reset) return;
  e.stopPropagation();
  const tr = e.target.closest("[data-row]"), [kind, id] = tr.dataset.row.split(":");
  const card = tr.closest("[data-key]"), err = $("[data-err]", card), box = $("[data-hunts]", card);
  const placeId = +$("[data-place-select]", tr).value || null;
  if (save && !placeId) { toast("Escolha a hunt na lista"); return; }
  if (reset && !confirm("Liberar de novo as trocas de local para essa hunt?")) return;
  (save || reset).disabled = true;
  try {
    await api("POST", "/api/admin/place", { kind, id: +id, place_id: save ? placeId : null, reset_edits: !!reset });
    toast(save ? "Local trocado" : "Trocas liberadas");
    const btn = [...card.querySelectorAll(".charbtn")].find((b) => b.dataset.char === box.dataset.char);
    box.dataset.char = ""; await showCharHunts(card, btn.dataset.char, btn);
  } catch (ex) { (save || reset).disabled = false; if (ex.message !== "401") err.textContent = ex.message; }
}, true);

$("#list").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  const card = b.closest("[data-key]"), key = card.dataset.key, k = KEYS.find((x) => x.key === key);
  const err = $("[data-err]", card); err.textContent = "";
  const act = b.dataset.act;
  try {
    if (act === "copy-key") return copy(key);
    if (act === "copy-invite") return copy(inviteText(k));
    if (act === "char-hunts") return showCharHunts(card, b.dataset.char, b);
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
