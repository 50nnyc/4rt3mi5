/* 4rt3mi5 — script de index.html (fica fora do HTML para o CSP bloquear qualquer script embutido). */
// Imagem que não carregou: some (data-err="hide") ou sai da página (data-err="remove"). Substitui o atributo
// de evento de erro embutido na tag, que o CSP sem 'unsafe-inline' não deixa rodar.
document.addEventListener("error", (e) => {
  const img = e.target;
  if (!(img instanceof HTMLImageElement) || !img.dataset.err) return;
  if (img.dataset.err === "hide") img.style.visibility = "hidden";
  else img.remove();
}, true);
const MSG_INVALID_KEY = "Chave de acesso inválida, envie mensagem ao criador.";
const MSG_NO_INTERNET = "Sem conexão com a internet, conecte-se novamente.";
const MSG_NO_SERVER = "Servidor do 4rt3mi5 indisponível. Tentando de novo a cada 10 segundos…";
const RETRY_MS = 10000;

const $ = (s) => document.querySelector(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmt = (n) => Number(n || 0).toLocaleString("pt-BR");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const kk = (n) => Math.abs(n) >= 1e6 ? (n / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 2 }) + "kk"
                : Math.abs(n) >= 1e3 ? (n / 1e3).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + "k" : String(n || 0);
const dur = (s) => `${Math.floor((s || 0) / 3600)}h${String(Math.floor(((s || 0) % 3600) / 60)).padStart(2, "0")}`;
const when = (iso) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
const dayLabel = (d) => d ? d.split("-").reverse().join("/") : "—";

const S = { api: "", desktop: false, acct: null, storeClaimed: false, key: null, token: null, keyExpires: null, me: null, nick: null, char: null, page: "home", offline: false };

/* ---------- armazenamento (navegador ou app desktop) ---------- */
const kv = {
  async get(k) {
    if (S.desktop) return await window.pywebview.api.kv_get(k);
    try { return localStorage.getItem(k); } catch { return null; }
  },
  async set(k, v) {
    if (S.desktop) return await window.pywebview.api.kv_set(k, v);
    try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {}
  },
};

function detectDesktop(ms) {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve(true);
    let done = false;
    window.addEventListener("pywebviewready", () => { if (!done) { done = true; resolve(true); } });
    setTimeout(() => { if (!done) { done = true; resolve(!!(window.pywebview && window.pywebview.api)); } }, ms);
  });
}

/* ---------- abertura ---------- */
$("#logo").innerHTML = [..."4rt3mi5"].map((c, i) => `<span style="animation-delay:${i * 70}ms">${c}</span>`).join("");
function splashShow(msg = "") {
  const sp = $("#splash");
  setSplashMsg(msg);
  sp.classList.remove("hidden", "fade", "play");
  void sp.offsetWidth; // reinicia a animação
  sp.classList.add("play");
  if (typeof Embers !== "undefined") Embers.start();
}
function setSplashMsg(msg) { $("#splashMsg").innerHTML = msg ? `<span class="dot"></span>${esc(msg)}` : ""; }
async function splashHide() {
  const sp = $("#splash");
  sp.classList.add("fade");
  await sleep(450);
  sp.classList.add("hidden");
  Embers.stop();
}
async function presentation(ms = 1800) { splashShow(); await sleep(ms); }

/* ---------- conexão ---------- */
async function timedFetch(url, opts = {}, ms = 7000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try { return await fetch(url, { ...opts, signal: ctl.signal, cache: "no-store" }); }
  finally { clearTimeout(t); }
}
async function serverOk() {
  try { return (await timedFetch(S.api + "/api/health", { headers: { "ngrok-skip-browser-warning": "1" } })).ok; } catch { return false; }
}
async function internetOk() {
  if (navigator.onLine === false) return false;
  try { await timedFetch("https://api.tibiadata.com/", { mode: "no-cors" }, 6000); return true; } catch { return false; }
}
/** Fica na tela de abertura, em loop a cada 10 s, até a conexão voltar. */
async function waitOnline(splashAlreadyVisible) {
  if (await serverOk()) return;
  if (S.offline) { while (S.offline) await sleep(500); return; }
  S.offline = true;
  if (!splashAlreadyVisible) splashShow();
  while (true) {
    setSplashMsg((await internetOk()) ? MSG_NO_SERVER : MSG_NO_INTERNET);
    await sleep(RETRY_MS);
    if (await serverOk()) break;
  }
  S.offline = false;
  if (!splashAlreadyVisible) await splashHide();
  else setSplashMsg("");
  setTimeout(flushDrafts, 1000);  // 📤 manda os rascunhos guardados enquanto estava sem conexão
}
function startMonitor() {
  setInterval(() => { if (!S.offline) waitOnline(false); }, RETRY_MS);
  window.addEventListener("offline", () => { if (!S.offline) waitOnline(false); });
}

/* ---------- API ---------- */
class ApiError extends Error { constructor(msg, status, hint, reason) { super(msg); this.status = status; this.hint = hint; this.reason = reason; } }
async function api(method, path, body) {
  let res;
  try {
    res = await timedFetch(S.api + path, {
      method, headers: authHeaders(body ? { "Content-Type": "application/json" } : {}),
      body: body ? JSON.stringify(body) : undefined,
    }, 30000);
  } catch {
    waitOnline(false);
    throw new ApiError("Sem conexão. Tente de novo quando voltar.", 0);
  }
  const data = await res.json().catch(() => ({}));
  const d = data.detail;
  if (res.status === 401) {
    if (d && d.reason === "device") { await needVerification(d.message); throw new ApiError(d.message, 401); }
    if (d && d.reason === "account") { await accountOut(MSG_SESSION_ENDED); throw new ApiError(MSG_SESSION_ENDED, 401); }
    await lockOut(MSG_INVALID_KEY); throw new ApiError(MSG_INVALID_KEY, 401);
  }
  if (!res.ok) throw new ApiError(typeof d === "object" && d ? d.message : (d || `Erro ${res.status}`), res.status, d && d.hint, d && d.reason);
  return data;
}
// O ngrok (plano grátis) mostra uma página de aviso para navegadores; este cabeçalho pula o aviso.
const NGROK = { "ngrok-skip-browser-warning": "1" };
function authHeaders(extra = {}) {
  return { ...NGROK, "X-Access-Key": S.key || "", "X-Device-Token": S.token || "", "X-Account-Token": S.acct || "", ...extra };
}
const MSG_SESSION_ENDED = "Sua sessão terminou. Entre na sua conta de novo.";

/* ---------- 0.16.0: conta (login com senha, antes da chave) ---------- */
const USER_RE = /^[A-Za-z0-9]{3,20}$/, PASS_RE = /^[A-Za-z0-9_!@-]{6,64}$/;
/** POST das rotas de conta. Não usa api(): aqui 401 é "senha incorreta", não chave inválida. */
async function acctPost(path, body, headers = {}) {
  const res = await timedFetch(S.api + path, {
    method: "POST", headers: { ...NGROK, "X-Account-Token": S.acct || "", ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  }, 30000).catch(() => null);
  if (!res) return { ok: false, status: 0, message: "Sem conexão com o servidor." };
  const data = await res.json().catch(() => ({}));
  const d = data.detail;
  return { ok: res.ok, status: res.status, data, reason: d && d.reason,
           message: typeof d === "object" && d ? d.message : (d || `Erro ${res.status}`) };
}
function showLogin(mode = "") {
  showOnly("loginScreen");
  $("#loginBox").classList.toggle("hidden", mode !== "login");
  $("#registerBox").classList.toggle("hidden", mode !== "register");
  $("#showLogin").classList.toggle("on", mode === "login");
  $("#showRegister").classList.toggle("on", mode === "register");
  $("#loginErr").textContent = ""; $("#registerErr").textContent = "";
  $("#resetBox").classList.add("hidden"); $("#forgotBox").innerHTML = "";
  $("#forgotBtn").classList.remove("hidden"); $("#haveResetBtn").classList.add("hidden");
  if (mode) setTimeout(() => $(mode === "login" ? "#loginUser" : "#regUser").focus(), 50);
  loadGuestNews();  // 0.22.3: as 2 notícias de quem ainda não tem conta
}
$("#showLogin").addEventListener("click", () => showLogin("login"));
$("#showRegister").addEventListener("click", () => showLogin("register"));

/* ---------- 0.22.3: sem conta — Lootsplit (só calcula; nada fica salvo) e as 2 notícias mais novas ---------- */
async function publicFetch(method, path, body) {
  const res = await timedFetch(S.api + path, {
    method, headers: { ...NGROK, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  }, 30000).catch(() => null);
  if (!res) throw new ApiError("Sem conexão com o servidor.", 0);
  const data = await res.json().catch(() => ({}));
  const d = data.detail;
  if (!res.ok) throw new ApiError(typeof d === "object" && d ? d.message : (d || `Erro ${res.status}`), res.status);
  return data;
}
$("#guestLootBtn").addEventListener("click", async () => {
  const raw = $("#guestLootText").value.trim(), err = $("#guestLootErr"), out = $("#guestLootResult");
  if (!raw) { err.textContent = "Cole o Party Hunt Analyser primeiro."; return; }
  const btn = $("#guestLootBtn"); btn.disabled = true; err.textContent = ""; out.innerHTML = "";
  try {
    const h = await publicFetch("POST", "/api/public/lootsplit", { raw_text: raw });
    out.innerHTML = `${quickTransfers(h)}${partyMessages(h)}<h2>Detalhes</h2>${huntCard(h, "", "Resultado")}`;
    countUp(out);
    out.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
  } catch (e) {
    err.textContent = e.message;
  } finally { btn.disabled = false; }
});
document.addEventListener("click", (e) => {
  if (!e.target.closest("[data-go-register]")) return;
  e.preventDefault();
  showLogin("register");
  window.scrollTo({ top: 0, behavior: reduceMotion() ? "auto" : "smooth" });
});
let guestNewsLang = null;
async function loadGuestNews() {
  if (guestNewsLang === I18N.lang) return;
  const el = $("#guestNews");
  guestNewsLang = I18N.lang;
  el.innerHTML = skeleton("list");
  try {
    const d = await publicFetch("GET", "/api/public/news?lang=" + encodeURIComponent(I18N.lang));
    el.innerHTML = d.news.length
      ? d.news.map((n) => tnCard(n)).join("") + `<p class="hint">${TN_CREDIT}</p>`
      : `<div class="card muted">As notícias ainda estão sendo buscadas pela primeira vez. Volte em alguns minutos.</div>`;
  } catch {
    guestNewsLang = null;
    el.innerHTML = `<div class="card muted">Não consegui carregar as notícias agora. Tente de novo mais tarde.</div>`;
  }
}
I18N.onChange(() => { if (!$("#loginScreen").classList.contains("hidden")) loadGuestNews(); });

/* 0.23.0: o app para Windows foi descontinuado (sem download; o 4rt3mi5 é só o site). */

/* 0.17.0: "Esqueceu conta/senha?" → pedido ao adm pelo WhatsApp; o adm manda um código para criar nova senha */
$("#forgotBtn").addEventListener("click", () => {
  $("#forgotBtn").classList.add("hidden");
  $("#haveResetBtn").classList.remove("hidden");
  recoveryForm($("#forgotBox"), { reason: "lost_login", lostLogin: true });
});
$("#haveResetBtn").addEventListener("click", () => {
  $("#loginBox").classList.add("hidden");
  $("#resetBox").classList.remove("hidden");
  $("#resetErr").textContent = "";
  $("#resetUser").value = $("#loginUser").value.trim();
  setTimeout(() => $($("#resetUser").value ? "#resetCode" : "#resetUser").focus(), 50);
});
$("#resetBack").addEventListener("click", () => showLogin("login"));
$("#resetForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const user = $("#resetUser").value.trim(), code = $("#resetCode").value.replace(/\s+/g, "").toUpperCase();
  const pass = $("#resetPass").value, pass2 = $("#resetPass2").value, err = $("#resetErr");
  if (!user || !code) { err.textContent = "Preencha a conta e o código."; return; }
  if (!PASS_RE.test(pass)) { err.textContent = "A senha aceita apenas números, letras e os caracteres especiais _ ! @ - (mínimo de 6)."; return; }
  if (pass !== pass2) { err.textContent = "As senhas não são iguais."; return; }
  const btn = e.currentTarget.querySelector("button[type=submit]"); btn.disabled = true; err.textContent = "";
  const r = await acctPost("/api/account/reset", { username: user, code, password: pass, confirm: pass2 });
  btn.disabled = false;
  if (!r.ok) { err.textContent = r.message; if (r.status === 0) waitOnline(false); return; }
  $("#resetPass").value = ""; $("#resetPass2").value = ""; $("#resetCode").value = "";
  await presentation(1200);
  await enterAccount(r.data);
  await splashHide();
});

/* 0.17.0: chave vencida — renova grátis e volta de onde parou */
function showExpired() {
  showOnly("expiredScreen");
  $("#expiredErr").textContent = "";
}
$("#expiredRenew").addEventListener("click", async (e) => {
  const btn = e.currentTarget; btn.disabled = true; $("#expiredErr").textContent = "";
  const r = await acctPost("/api/account/renew", {});
  btn.disabled = false;
  if (!r.ok) {
    if (r.reason === "account") return accountOut(MSG_SESSION_ENDED);
    $("#expiredErr").textContent = r.message;
    return;
  }
  await presentation(1200);
  await enterAccount(r.data);
  await splashHide();
});
$("#expiredOut").addEventListener("click", () => accountOut(""));
async function accountOut(msg = "") {
  if (S.acct) acctPost("/api/account/logout");
  S.acct = null; S.key = null; S.token = null; S.me = null; S.char = null;
  await kv.set("acct", null); await kv.set("key", null); await kv.set("token", null);
  closeDrawer();
  showLogin("login");
  $("#loginErr").textContent = msg;
}
$("#acctOut").addEventListener("click", () => accountOut(""));

/** Depois da senha (ou ao reabrir): conta com chave e personagem entra direto; sem chave, vai para o 1º acesso. */
async function enterAccount(r) {
  S.acct = r.token; await kv.set("acct", r.token);
  S.storeClaimed = r.store_claimed;
  if (r.key && r.key_expired) {
    S.key = null; S.token = null; S.keyExpires = r.expires_at;
    showExpired();
    return;
  }
  if (r.key) {
    S.key = r.key; S.keyExpires = r.expires_at; S.token = r.device_token || null;
    await kv.set("key", r.key); await kv.set("token", S.token);
    if (S.token) { S.me = await api("GET", "/api/me").catch(() => null); await showNick(); }
    else showVerify();
    return;
  }
  // quem já usava o app só com o código (antes da 0.16.0): a chave deste aparelho passa para a conta sozinha
  const oldKey = await kv.get("key"), oldToken = await kv.get("token");
  if (oldKey && oldToken) {
    const auth = await checkKey(oldKey, oldToken);
    if (auth && auth.device_verified && !auth.other_account) {
      S.key = oldKey; S.token = oldToken; S.keyExpires = auth.expires_at;
      if ((await acctPost("/api/account/link", {}, authHeaders())).ok) {
        S.me = await api("GET", "/api/me").catch(() => null);
        await showNick();
        return;
      }
    }
    S.key = null; S.token = null;
    await kv.set("key", null); await kv.set("token", null);
  }
  await showFirstAccess();
}

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const user = $("#loginUser").value.trim(), pass = $("#loginPass").value;
  if (!user || !pass) { $("#loginErr").textContent = "Preencha a conta e a senha."; return; }
  const btn = e.currentTarget.querySelector("button"); btn.disabled = true; $("#loginErr").textContent = "";
  const r = await acctPost("/api/account/login", { username: user, password: pass, device_token: (await kv.get("token")) || "" });
  btn.disabled = false;
  if (!r.ok) {
    $("#loginErr").textContent = r.message;
    $("#loginPass").value = ""; $("#loginPass").focus();
    if (r.status === 0) waitOnline(false);
    return;
  }
  $("#loginPass").value = "";
  await presentation(1200);
  await enterAccount(r.data);
  await splashHide();
});
$("#registerForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const user = $("#regUser").value.trim(), pass = $("#regPass").value, pass2 = $("#regPass2").value;
  const err = $("#registerErr");
  if (!USER_RE.test(user)) { err.textContent = "A conta deve ter de 3 a 20 letras ou números, sem espaços nem caracteres especiais."; return; }
  if (!PASS_RE.test(pass)) { err.textContent = "A senha aceita apenas números, letras e os caracteres especiais _ ! @ - (mínimo de 6)."; return; }
  if (pass !== pass2) { err.textContent = "As senhas não são iguais."; return; }
  const btn = e.currentTarget.querySelector("button"); btn.disabled = true; err.textContent = "";
  const r = await acctPost("/api/account/register", { username: user, password: pass, confirm: pass2 });
  btn.disabled = false;
  if (!r.ok) { err.textContent = r.message; if (r.status === 0) waitOnline(false); return; }
  $("#regPass").value = ""; $("#regPass2").value = "";
  await presentation(1200);
  await enterAccount(r.data);
  await splashHide();
});

/* ---------- chave de acesso ---------- */
/** null = sem conexão; false = chave inválida; objeto = {expires_at, claimed, device_verified, other_account} */
async function checkKey(key, token) {
  const res = await timedFetch(S.api + "/api/auth", { method: "POST", headers: { ...NGROK, "X-Access-Key": key, "X-Device-Token": token || "", "X-Account-Token": S.acct || "" } }).catch(() => null);
  if (!res) return null;
  if (!res.ok) return false;
  return res.json();
}
async function lockOut(msg, toFirstAccess = false) {
  S.key = null; S.token = null; S.me = null;
  await kv.set("key", null);
  await kv.set("token", null);
  closeDrawer();
  if (!S.acct) { showLogin("login"); $("#loginErr").textContent = msg || ""; return; }
  // 0.17.0: com conta, a chave pode só ter vencido (ela continua na conta): pergunta ao servidor o que mostrar
  const r = toFirstAccess ? { ok: false } : await acctPost("/api/account/resume", {});
  if (r.ok && r.data.key) return enterAccount(r.data);
  if (r.reason === "account") return accountOut(MSG_SESSION_ENDED);
  await showFirstAccess(msg);
}

/* 1º acesso da conta: chave grátis ou "já tenho um código" */
async function showFirstAccess(msg = "") {
  showOnly("keyScreen");
  $("#keyErr").textContent = msg || "";
  $("#keyWrong").classList.add("hidden"); $("#keyRecovery").innerHTML = "";
  $("#storeErr").textContent = ""; $("#storeGot").innerHTML = "";
  $("#storeFree").classList.remove("hidden");
  try {
    const s = await (await timedFetch(S.api + "/api/store", { headers: NGROK })).json();
   $("#storeFree").classList.toggle("hidden", !s.free || !!S.storeClaimed);
    if (S.storeClaimed) $("#storeErr").textContent = "Sua conta já gerou a chave gratuita. Se perdeu o acesso, use \"Já tenho um código\".";
    else if (!s.free) $("#storeErr").textContent = "A chave gratuita está pausada no momento. Peça um código para quem te indicou o 4rt3mi5.";
  } catch { $("#storeErr").textContent = "Sem conexão com o servidor."; }
}
$("#keyForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const key = $("#keyInput").value.replace(/\s+/g, "").toUpperCase();
  if (!key) return;
  const btn = e.currentTarget.querySelector("button"); btn.disabled = true;
  $("#keyErr").textContent = ""; $("#keyWrong").classList.add("hidden"); $("#keyRecovery").innerHTML = "";
  const auth = await checkKey(key, null);
  btn.disabled = false;
  if (auth === null) { $("#keyErr").textContent = "Sem conexão com o servidor."; return waitOnline(false); }
  if (!auth) { $("#keyWrong").classList.remove("hidden"); return; }
  if (auth.other_account) {
    recoveryForm($("#keyRecovery"), { reason: "key_taken", intro: "Esse código de acesso já está ligado a outra conta." });
    return;
  }
  S.key = key; S.keyExpires = auth.expires_at; S.token = null;
  await kv.set("key", key);
  await kv.set("token", null);
  $("#keyInput").value = "";
  await presentation(1400);
  askPlayerType(async (t) => { await kv.set("ptype_pending", t); showVerify(); });  // 0.20.0
  await splashHide();
});
$("#wrongYes").addEventListener("click", () => {
  $("#keyWrong").classList.add("hidden");
  recoveryForm($("#keyRecovery"), { reason: "lost_code" });
});
$("#wrongNo").addEventListener("click", () => {
  $("#keyWrong").classList.add("hidden");
  const card = $("#storeFreeCard");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash");
});

/* ---------- 0.17.0: WhatsApp com país (bandeira + DDI) e busca por qualquer parte do nome ---------- */
const COUNTRIES = ("AF|Afeganistão|93;ZA|África do Sul|27;AL|Albânia|355;DE|Alemanha|49;AD|Andorra|376;AO|Angola|244;"
  + "AI|Anguila|1264;AG|Antígua e Barbuda|1268;SA|Arábia Saudita|966;DZ|Argélia|213;AR|Argentina|54;AM|Armênia|374;"
  + "AW|Aruba|297;AU|Austrália|61;AT|Áustria|43;AZ|Azerbaijão|994;BS|Bahamas|1242;BH|Bahrein|973;BD|Bangladesh|880;"
  + "BB|Barbados|1246;BE|Bélgica|32;BZ|Belize|501;BJ|Benin|229;BM|Bermudas|1441;BY|Bielorrússia|375;BO|Bolívia|591;"
  + "BA|Bósnia e Herzegovina|387;BW|Botsuana|267;BR|Brasil|55;BN|Brunei|673;BG|Bulgária|359;BF|Burkina Faso|226;"
  + "BI|Burundi|257;BT|Butão|975;CV|Cabo Verde|238;CM|Camarões|237;KH|Camboja|855;CA|Canadá|1;BQ|Caribe Neerlandês|599;"
  + "QA|Catar|974;KZ|Cazaquistão|7;TD|Chade|235;CL|Chile|56;CN|China|86;CY|Chipre|357;CO|Colômbia|57;KM|Comores|269;"
  + "CG|Congo|242;CD|Congo (Rep. Democrática)|243;KP|Coreia do Norte|850;KR|Coreia do Sul|82;CI|Costa do Marfim|225;"
  + "CR|Costa Rica|506;HR|Croácia|385;CU|Cuba|53;CW|Curaçao|599;DK|Dinamarca|45;DJ|Djibuti|253;DM|Dominica|1767;"
  + "EG|Egito|20;SV|El Salvador|503;AE|Emirados Árabes Unidos|971;EC|Equador|593;ER|Eritreia|291;SK|Eslováquia|421;"
  + "SI|Eslovênia|386;ES|Espanha|34;SZ|Essuatíni|268;US|Estados Unidos|1;EE|Estônia|372;ET|Etiópia|251;FJ|Fiji|679;"
  + "PH|Filipinas|63;FI|Finlândia|358;FR|França|33;GA|Gabão|241;GM|Gâmbia|220;GH|Gana|233;GE|Geórgia|995;"
  + "GI|Gibraltar|350;GD|Granada|1473;GR|Grécia|30;GL|Groenlândia|299;GP|Guadalupe|590;GU|Guam|1671;GT|Guatemala|502;"
  + "GG|Guernsey|44;GY|Guiana|592;GF|Guiana Francesa|594;GN|Guiné|224;GQ|Guiné Equatorial|240;GW|Guiné-Bissau|245;"
  + "HT|Haiti|509;HN|Honduras|504;HK|Hong Kong|852;HU|Hungria|36;YE|Iêmen|967;IM|Ilha de Man|44;KY|Ilhas Cayman|1345;"
  + "CK|Ilhas Cook|682;FO|Ilhas Faroé|298;FK|Ilhas Malvinas|500;MP|Ilhas Marianas do Norte|1670;MH|Ilhas Marshall|692;"
  + "SB|Ilhas Salomão|677;TC|Ilhas Turks e Caicos|1649;VI|Ilhas Virgens Americanas|1340;VG|Ilhas Virgens Britânicas|1284;"
  + "IN|Índia|91;ID|Indonésia|62;IR|Irã|98;IQ|Iraque|964;IE|Irlanda|353;IS|Islândia|354;IL|Israel|972;IT|Itália|39;"
  + "JM|Jamaica|1876;JP|Japão|81;JE|Jersey|44;JO|Jordânia|962;KI|Kiribati|686;XK|Kosovo|383;KW|Kuwait|965;LA|Laos|856;"
  + "LS|Lesoto|266;LV|Letônia|371;LB|Líbano|961;LR|Libéria|231;LY|Líbia|218;LI|Liechtenstein|423;LT|Lituânia|370;"
  + "LU|Luxemburgo|352;MO|Macau|853;MK|Macedônia do Norte|389;MG|Madagascar|261;MY|Malásia|60;MW|Malawi|265;"
  + "MV|Maldivas|960;ML|Mali|223;MT|Malta|356;MA|Marrocos|212;MQ|Martinica|596;MU|Maurício|230;MR|Mauritânia|222;"
  + "YT|Mayotte|262;MX|México|52;MM|Mianmar|95;FM|Micronésia|691;MZ|Moçambique|258;MD|Moldávia|373;MC|Mônaco|377;"
  + "MN|Mongólia|976;ME|Montenegro|382;MS|Montserrat|1664;NA|Namíbia|264;NR|Nauru|674;NP|Nepal|977;NI|Nicarágua|505;"
  + "NE|Níger|227;NG|Nigéria|234;NU|Niue|683;NO|Noruega|47;NC|Nova Caledônia|687;NZ|Nova Zelândia|64;OM|Omã|968;"
  + "NL|Países Baixos (Holanda)|31;PW|Palau|680;PS|Palestina|970;PA|Panamá|507;PG|Papua-Nova Guiné|675;PK|Paquistão|92;"
  + "PY|Paraguai|595;PE|Peru|51;PF|Polinésia Francesa|689;PL|Polônia|48;PR|Porto Rico|1787;PT|Portugal|351;"
  + "KE|Quênia|254;KG|Quirguistão|996;GB|Reino Unido|44;CF|República Centro-Africana|236;DO|República Dominicana|1809;"
  + "CZ|República Tcheca|420;RE|Reunião|262;RO|Romênia|40;RW|Ruanda|250;RU|Rússia|7;WS|Samoa|685;AS|Samoa Americana|1684;"
  + "SM|San Marino|378;SH|Santa Helena|290;LC|Santa Lúcia|1758;BL|São Bartolomeu|590;KN|São Cristóvão e Névis|1869;"
  + "MF|São Martinho|590;PM|São Pedro e Miquelão|508;ST|São Tomé e Príncipe|239;VC|São Vicente e Granadinas|1784;"
  + "SC|Seicheles|248;SN|Senegal|221;SL|Serra Leoa|232;RS|Sérvia|381;SG|Singapura|65;SX|Sint Maarten|1721;SY|Síria|963;"
  + "SO|Somália|252;LK|Sri Lanka|94;SD|Sudão|249;SS|Sudão do Sul|211;SE|Suécia|46;CH|Suíça|41;SR|Suriname|597;"
  + "TJ|Tajiquistão|992;TH|Tailândia|66;TW|Taiwan|886;TZ|Tanzânia|255;TL|Timor-Leste|670;TG|Togo|228;TO|Tonga|676;"
  + "TT|Trinidad e Tobago|1868;TN|Tunísia|216;TM|Turcomenistão|993;TR|Turquia|90;TV|Tuvalu|688;UA|Ucrânia|380;"
  + "UG|Uganda|256;UY|Uruguai|598;UZ|Uzbequistão|998;VU|Vanuatu|678;VA|Vaticano|379;VE|Venezuela|58;VN|Vietnã|84;"
  + "WF|Wallis e Futuna|681;ZM|Zâmbia|260;ZW|Zimbábue|263")
  .split(";").map((s) => { const [iso, name, dial] = s.split("|"); return { iso, name, dial }; })
  .sort((a, b) => a.name.localeCompare(b.name, "pt"));
const flagOf = (iso) => String.fromCodePoint(...[...iso].map((c) => 0x1F1E6 + c.charCodeAt(0) - 65));
const plain = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** 0.23.0: nome do país no idioma escolhido (o navegador já sabe todos); em português, a lista acima. */
const _regionNames = {};
function countryName(c) {
  if (I18N.lang === "pt-BR") return c.name;
  try {
    _regionNames[I18N.lang] = _regionNames[I18N.lang] || new Intl.DisplayNames([I18N.locale], { type: "region" });
    return _regionNames[I18N.lang].of(c.iso) || c.name;
  } catch { return c.name; }
}
/** Campo de WhatsApp: botão com a bandeira (abre a busca de país) + o resto do número. */
function phoneField(el) {
  let cur = COUNTRIES.find((c) => c.iso === "BR");
  el.innerHTML = `<div class="phone">
      <button type="button" class="cc" aria-haspopup="listbox" aria-label="Escolher país"></button>
      <input class="rphone" type="tel" inputmode="tel" placeholder="DDD + número" autocomplete="tel-national" maxlength="20">
      <div class="ccPop hidden">
        <input class="ccSearch" placeholder="Pesquisar país (ex.: chile)" autocomplete="off" spellcheck="false">
        <div class="ccList" role="listbox"></div>
      </div>
    </div>`;
  const btn = el.querySelector(".cc"), pop = el.querySelector(".ccPop"), search = el.querySelector(".ccSearch"),
        list = el.querySelector(".ccList"), input = el.querySelector(".rphone");
  const label = () => { btn.innerHTML = `<span class="flag">${flagOf(cur.iso)}</span> +${esc(cur.dial)} <span class="muted">▾</span>`; btn.title = countryName(cur); };
  let shown = [];
  const draw = () => {
    const q = plain(search.value.trim()), digits = q.replace(/\D/g, "");
    // procura em QUALQUER parte do nome ("ile" acha Chile, Brasil não), na sigla e no código do país;
    // 0.23.0: vale o nome em português e o do idioma escolhido, e a lista segue a ordem do idioma
    const named = COUNTRIES.map((c) => ({ c, n: countryName(c) })).sort((a, b) => a.n.localeCompare(b.n, I18N.locale));
    shown = named.filter(({ c, n }) => !q || plain(n).includes(q) || plain(c.name).includes(q) || c.iso.toLowerCase() === q
      || (digits && c.dial.startsWith(digits)));
    list.innerHTML = shown.length ? shown.map(({ c, n }, i) => `<button type="button" role="option" data-cc="${i}" class="${c === cur ? "on" : ""}">
        <span class="flag">${flagOf(c.iso)}</span> <span class="ccName" data-i18n-skip>${esc(n)}</span> <span class="muted">+${esc(c.dial)}</span></button>`).join("")
      : `<div class="muted" style="padding:8px">Nenhum país encontrado.</div>`;
  };
  const close = () => pop.classList.add("hidden");
  const pick = (c) => { cur = c; label(); close(); input.focus(); };
  btn.addEventListener("click", () => {
    if (!pop.classList.contains("hidden")) return close();
    search.value = ""; draw(); pop.classList.remove("hidden"); search.focus();
  });
  search.addEventListener("input", draw);
  search.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); if (shown[0]) pick(shown[0].c); }
    if (e.key === "Escape") { close(); btn.focus(); }
  });
  list.addEventListener("click", (e) => { const b = e.target.closest("[data-cc]"); if (b) pick(shown[+b.dataset.cc].c); });
  document.addEventListener("click", (e) => { if (!el.contains(e.target)) close(); });
  label();
  return {
    focus: () => input.focus(),
    // número completo com o código do país (sem o 0 de longa distância do começo)
    value: () => cur.dial + input.value.replace(/\D/g, "").replace(/^0+/, ""),
    nationalOk: () => input.value.replace(/\D/g, "").replace(/^0+/, "").length >= 6,
  };
}

/** Pedido de recuperação: a pessoa deixa o WhatsApp e o adm entra em contato (painel do criador).
 *  lostLogin = "Esqueceu conta/senha?" (sem estar logado; pergunta o que a pessoa lembra). */
function recoveryForm(el, { reason, character = null, intro = "", lostLogin = false }) {
  el.innerHTML = `<div class="banner bad" style="margin-top:10px">${intro ? `<b>${esc(intro)}</b><br>` : ""}
      Vamos avisar o administrador para que ele entre em contato com você e ajude a recuperar ${lostLogin ? "a sua conta" : "o seu código"}.
      Por favor, informe o seu número de WhatsApp.
      <form class="rf" style="margin-top:8px">
        ${lostLogin ? `<input class="ruser" placeholder="Conta (se lembrar)" autocomplete="username" autocapitalize="off" spellcheck="false" maxlength="20">
          <input class="rchar" placeholder="Nick de um personagem seu (se lembrar)" autocomplete="off" autocapitalize="words" spellcheck="false" maxlength="40" style="margin-top:8px">` : ""}
        <label class="muted" style="display:block; margin-top:8px">País e WhatsApp:</label>
        <div class="rphoneBox"></div>
        <button class="btn" type="submit">Enviar</button>
      </form>
      <div class="err rerr"></div>
    </div>`;
  const f = el.querySelector(".rf"), err = el.querySelector(".rerr");
  const phone = phoneField(f.querySelector(".rphoneBox"));
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!phone.nationalOk()) { err.textContent = "Escolha o país pela bandeira e digite o WhatsApp com DDD, só números."; return; }
    const btn = f.querySelector("button[type=submit]"); btn.disabled = true; err.textContent = "";
    const r = lostLogin
      ? await acctPost("/api/recovery/login", { whatsapp: "+" + phone.value(), username: f.querySelector(".ruser").value.trim(),
                                                character: f.querySelector(".rchar").value.trim().replace(/\s+/g, " ") || null })
      : await acctPost("/api/recovery", { whatsapp: "+" + phone.value(), reason, character });
    btn.disabled = false;
    if (r.ok) {
      el.innerHTML = `<div class="banner ok" style="margin-top:10px"><b>✔ Pedido enviado!</b>
        <div>O administrador vai te chamar no WhatsApp para recuperar ${lostLogin ? "a sua conta" : "o seu código"}.</div></div>`;
    } else if (r.reason === "account") accountOut(MSG_SESSION_ENDED);
    else err.textContent = r.message;
  });
  setTimeout(() => (lostLogin ? f.querySelector(".ruser") : phone).focus(), 50);
}

/* ---------- loja: chave grátis (uma vez por conta) ---------- */
$("#storeFree").addEventListener("click", async (e) => {
  const btn = e.currentTarget; btn.disabled = true; $("#storeErr").textContent = "";
  const r = await acctPost("/api/store/free", {});
  btn.disabled = false;
  if (!r.ok) {
    if (r.reason === "account") return accountOut(MSG_SESSION_ENDED);
    $("#storeErr").textContent = r.message;
    return;
  }
  const d = r.data;
  btn.classList.add("hidden");
  S.storeClaimed = true;
  $("#storeGot").innerHTML = `<div class="banner ok" style="margin-top:12px"><b>Pronto! Sua chave:</b>
    <div class="codebox" style="margin:8px 0">${esc(d.key)}</div>
    <div class="hint">Ela não vence e já está guardada na sua conta. Agora diga que tipo de player você é e confirme o seu personagem.</div>
    <button class="btn" id="storeUse" type="button">Continuar</button></div>`;
  $("#storeUse").onclick = async () => {
    S.key = d.key; S.keyExpires = d.expires_at; S.token = null;
    await kv.set("key", d.key); await kv.set("token", null);
    askPlayerType(async (t) => { await kv.set("ptype_pending", t); showVerify(); });  // 0.20.0
  };
});

/* ---------- 0.14.0: renovação grátis de 7 dias (menu ☰) ---------- */
const fmtDay = (iso) => new Date(iso).toLocaleDateString("pt-BR");
function renewSheet(html) { const sh = $("#sheet"); sh.innerHTML = html; sh.classList.remove("hidden"); }
const RENEW_WINDOW_MS = 3 * 86400000;  // 0.15.0: o item só aparece quando faltam menos de 3 dias
function canRenew() {
  const exp = (S.me && S.me.expires_at) || S.keyExpires;
  return !!exp && !!(S.me && S.me.main_char) && new Date(exp) - Date.now() < RENEW_WINDOW_MS;
}
$("#renewItem").addEventListener("click", () => {
  closeDrawer();
  const exp = (S.me && S.me.expires_at) || S.keyExpires;
  const open = canRenew();
  renewSheet(`<b>🔑 Renove 7 dias grátis da sua chave</b>
    <div class="muted" style="font-size:14px; margin-top:2px">Sua chave ${exp ? `vale até <b>${esc(fmtDay(exp))}</b>` : "está ativa"}.
      ${open ? "Renove agora e ela passa a valer por 7 dias a partir de hoje, com os mesmos personagens."
             : "A renovação grátis fica disponível quando faltarem menos de 3 dias."}</div>
    <div class="actions">${open ? `<button class="btn" id="renewGo">Renovar 7 dias grátis</button>` : ""}
      <button class="btn2" data-paste-cancel>${open ? "Agora não" : "Ok"}</button></div>`);
  const b = $("#renewGo");
  if (b) b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await api("POST", "/api/key/renew-free");
      S.me = r.me; if (r.me.expires_at) S.keyExpires = r.me.expires_at;
      updateDrawerFoot();
      renewSheet(`<b>${r.renewed ? "✔ Chave renovada!" : "Sua chave já está em dia"}</b>
        <div class="muted" style="font-size:14px; margin-top:2px">${r.me.expires_at ? `Agora ela vale até <b>${esc(fmtDay(r.me.expires_at))}</b>.` : ""}</div>
        <div class="actions"><button class="btn2" data-paste-cancel>Ok</button></div>`);
      if (S.page === "home") loadHome();
    } catch (e) {
      b.disabled = false;
      if (!$("#renewErr")) b.parentElement.insertAdjacentHTML("afterend", `<div class="err" id="renewErr"></div>`);
      $("#renewErr").textContent = e.message;
    }
  };
});

/* ---------- 0.13.0: uso das telas (só contadores por tela, sem dizer quem) ---------- */
const Track = {
  acted: true,
  send(page, action) {
    if (!S.key || !S.token) return;
    timedFetch(S.api + "/api/track", { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ page, action }) }).catch(() => {});
  },
  view(page) { this.acted = false; this.send(page, false); },
  act() { if (this.acted || !S.page) return; this.acted = true; this.send(S.page, true); },
};
// "fez algo" = tocou em botão/campo/link dentro da tela (navegar para outra tela não conta) ou colou texto
$("main").addEventListener("click", (e) => {
  const el = e.target.closest("button, a, input, select, textarea, summary, [data-price-item], [data-view]");
  if (el && !el.closest("[data-page], [data-page-link]")) Track.act();
});
$("main").addEventListener("paste", () => Track.act());
document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v" && !$("#app").classList.contains("hidden")) Track.act(); });

/* ---------- verificação do main character (código no comentário do tibia.com) ---------- */
async function needVerification(msg) {
  S.token = null; S.me = null;
  await kv.set("token", null);
  closeDrawer();
  showVerify(msg);
}
function showVerify(msg = "") {
  showOnly("verifyScreen");
  verifyWidget($("#verifyBox"), {
    title: "Informe o nick do main character:",
    intro: msg,
    onDone: async (r) => {
      S.token = r.token; S.me = r.me;
      await kv.set("token", r.token);
      await kv.set("nick", r.me.main_char || r.character);
      if (S.acct) {  // 0.16.0: a chave verificada fica guardada na conta (outro aparelho entra só com a senha)
        const l = await acctPost("/api/account/link", {}, authHeaders());
        if (!l.ok && l.reason === "key_taken") {
          await lockOut("");
          recoveryForm($("#keyRecovery"), { reason: "key_taken", intro: l.message });
          return;
        }
      }
      $("#nickInput").value = "";
      await presentation(1400);
      await showNick();
      await splashHide();
    },
  });
}
$("#verifyBack").addEventListener("click", () => lockOut("", true));

/**
 * Componente reaproveitado: pede o personagem, mostra o código de verificação e confere
 * (no botão e sozinho a cada 30 s) se o código já aparece no comentário pelo TibiaData.
 */
/* 0.23.0: exemplo de nick nos campos de personagem — um conhecido da comunidade, sorteado a cada vez */
const NICK_IDEAS = ["Bubble", "Veyllor", "Dukoth", "Vda Pedro Assombrado", "Vda Assombrado Pedro", "Hilay", "Moonryel", "Bobeek",
                    "Goraca", "Ferangel", "Eternal Oblivion", "Kharsek", "Mateusz Dragon Wielki"];
const nickIdea = () => NICK_IDEAS[Math.floor(Math.random() * NICK_IDEAS.length)];
/** Campos com data-nick-ph ganham "Ex.: <nick>" no idioma escolhido. */
function paintNickPh(root = document) {
  root.querySelectorAll("[data-nick-ph]").forEach((el) => { el.placeholder = `${I18N.t("Ex.:")} ${nickIdea()}`; });
}
I18N.onChange(() => paintNickPh());
paintNickPh();
function verifyWidget(el, { title, intro = "", onDone }) {
  let timer = null;
  const stop = () => { if (timer) clearInterval(timer); timer = null; };
  stop();
  el.innerHTML = `
    <form class="vf">
      <label class="muted">${esc(title)}</label>
      ${intro ? `<div class="hint" style="margin:4px 0 0">${esc(intro)}</div>` : ""}
      <input class="vchar" data-nick-ph autocomplete="off" autocapitalize="words" spellcheck="false" style="margin-top:6px">
      <button class="btn" type="submit">Gerar código de verificação</button>
      <div class="err verr"></div>
      <div class="vrec"></div>
    </form>`;
  paintNickPh(el);
  const form = el.querySelector(".vf");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = form.querySelector(".vchar").value.trim().replace(/\s+/g, " ");
    if (!name) return;
    const btn = form.querySelector("button"); btn.disabled = true; form.querySelector(".verr").textContent = "";
    try {
      const v = await api("POST", "/api/verify/start", { character: name });
      if (v.token) await onDone(v);  // contato de confiança: o criador já definiu o main, sem código
      else showCode(v);
    }
    catch (err) {
      if (err.reason === "char_taken") {  // 0.16.0: o personagem já está em outra chave → pedido ao adm
        const rec = document.createElement("div");
        form.replaceWith(rec);
        recoveryForm(rec, { reason: "char_taken", character: name, intro: "Este personagem já possui código de acesso." });
      } else if (err.status !== 401) form.querySelector(".verr").textContent = err.message;
    }
    finally { btn.disabled = false; }
  });

  function showCode(v) {
    el.innerHTML = `
      <div class="muted">Para confirmar que <b style="color:var(--text)">${esc(v.character)}</b> é seu, coloque este código no comentário do personagem:</div>
      <div class="codebox">${esc(v.code)}</div>
      <button class="btn2" data-copy="${esc(v.code)}">Copiar</button>
      <ol class="steps">
        <li>Entre na sua conta no tibia.com</li>
        <li>Account Management → <b>Edit</b> no personagem → campo <b>Comment</b></li>
        <li>Cole o código, salve e volte aqui</li>
      </ol>
      <div class="hint">Depois de verificado você pode apagar o código do comentário. O código vale por 1 hora.</div>
      <button class="btn vcheck">Já coloquei, verificar</button>
      <div class="hint vstatus" style="margin-top:8px">Vamos conferir sozinhos a cada 30 segundos.</div>
      <div class="err verr"></div>
      <button class="link vother">← usar outro personagem</button>`;
    const status = el.querySelector(".vstatus"), err = el.querySelector(".verr"), btn = el.querySelector(".vcheck");
    let busy = false;
    async function check(manual) {
      if (busy || !el.isConnected || el.closest(".hidden")) { if (!el.isConnected) stop(); return; }
      busy = true; btn.disabled = true; err.textContent = "";
      status.textContent = "Conferindo no TibiaData…";
      try {
        const r = await api("POST", "/api/verify/check", { code: v.code });
        stop();
        status.textContent = "Verificado ✔";
        await onDone(r);
      } catch (e) {
        if (e.status === 410) { stop(); err.textContent = e.message; }
        else if (e.reason === "char_taken") {
          stop();
          recoveryForm(err, { reason: "char_taken", character: v.character, intro: "Este personagem já possui código de acesso." });
        }
        else if (e.status === 409) { status.textContent = `Última conferência: ${new Date().toLocaleTimeString("pt-BR")}`; if (manual) err.innerHTML = `${esc(e.message)}<div class="hint">${esc(e.hint || "")}</div>`; }
        else if (e.status !== 401) { status.textContent = ""; if (manual) err.textContent = e.message; }
      } finally { busy = false; btn.disabled = false; }
    }
    btn.addEventListener("click", () => check(true));
    el.querySelector(".vother").addEventListener("click", () => { stop(); verifyWidget(el, { title, intro, onDone }); });
    timer = setInterval(() => check(false), 30000);
  }
}

/* ---------- nickname ---------- */
async function showNick(prefill = true) {
  if (S.token) {  // 0.20.0: tipo de player escolhido antes da verificação, ou ainda não escolhido
    await savePendingPlayerType();
    if (!S.me) S.me = await api("GET", "/api/me").catch(() => null);
    if (S.me && S.me.player_type_chosen === false) {
      return askPlayerType(async (t) => {
        await kv.set("ptype_pending", t);
        await savePendingPlayerType();
        await showNick(prefill);
      });
    }
  }
  showOnly("nickScreen");
  $("#nickErr").textContent = "";
  $("#nickBack").classList.toggle("hidden", !S.char);
  const last = prefill ? ((await kv.get("nick")) || (S.me && S.me.main_char)) : null;
  if (last && !$("#nickInput").value) $("#nickInput").value = last;
  // 0.29.0: quem já tem personagem entra direto no Início (o Solo/Party é trocado nos menus)
  if (last && prefill && !S.char) {
    try { await enterWithNick(last); return; } catch (err) { if (err.status === 401) return; }
  }
  setTimeout(() => $("#nickInput").focus(), 50);
}
async function enterWithNick(name) {
  S.char = await api("GET", `/api/character/${encodeURIComponent(name)}`);
  S.nick = S.char.name;
  await kv.set("nick", S.nick);
  const saved = await kv.get("mode");
  await setMode(S.mode || (saved === "party" ? "party" : "solo"), { nav: false });
  openApp("home");
}
$("#nickForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#nickInput").value.trim().replace(/\s+/g, " ");
  if (!name) return;
  const btn = e.currentTarget.querySelector("button[type=submit]"); btn.disabled = true; $("#nickErr").textContent = "";
  try {
    await enterWithNick(name);
  } catch (err) {
    if (err.status !== 401) $("#nickErr").textContent = err.message;
  } finally { btn.disabled = false; }
});

/* ---------- 0.22.0: Solo / Party ---------- */
// Escolhido na tela do personagem e trocado a qualquer momento na barra do rodapé.
// Solo → Hunt Session Stacker; Party → Lootsplit. Bosses e Hunts seguem a mesma escolha.
S.mode = null;
const modePage = () => (S.mode === "party" ? "loot" : "stack");
function paintMode() {
  const party = S.mode === "party";
  $("#modeSwitch").dataset.mode = party ? "party" : "solo";
  $("#modeSwitch").querySelectorAll("button[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === S.mode)));
  document.querySelectorAll("#drawer .branch").forEach((b) => b.classList.toggle("on", b.dataset.branch === S.mode));
  markActive();
}
/** Item do menu aceso: a tela atual (e, nos galhos Solo/Party, o galho do modo atual). */
function markActive() {
  document.querySelectorAll("#drawer [data-page]").forEach((b) => b.classList.toggle("active",
    b.dataset.page === S.page && (!b.dataset.mode || b.dataset.mode === S.mode)));
}
async function setMode(m, { nav = true } = {}) {
  m = m === "party" ? "party" : "solo";
  const changed = m !== S.mode;
  S.mode = m; S.btab = m;
  await kv.set("mode", m);
  paintMode();
  if (!nav) return;
  closeDrawer();
  // telas com Solo/Party: trocam ali mesmo; nas outras, a chave leva ao Stacker ou ao Lootsplit
  if (S.page === "boss") { if (changed) { showBossTab(m); renderBoss(); } return; }
  if (S.page === "hunts") { if (changed) loadHunts(); return; }
  if (S.page === "home") { if (changed) loadHome(); return; }
  if (S.page !== modePage()) go(modePage());
}
/** 0.31.1: a bolinha de acertos pendentes (menu e rodapé) leva direto às hunts a acertar, com a primeira aberta. */
async function goPending() {
  HL.filter = "pend"; HL.q = ""; HL.shown = HL_STEP; HL.openFirst = true;
  if (S.mode !== "party") await setMode("party", { nav: false });
  if (S.page === "loot") loadLootList(); else go("loot");
}
$("#modeBar").addEventListener("click", (e) => {
  if (e.target.closest("#partyBadge") && !$("#partyBadge").classList.contains("hidden")) return goPending();
  const b = e.target.closest("button[data-mode]"); if (b) setMode(b.dataset.mode);
});
// 0.22.0: a chave Solo/Party só aparece nas telas que dependem dela
const MODE_PAGES = new Set(["home", "stack", "loot", "boss", "hunts"]);

/* ---------- app / menu ---------- */
function showOnly(id) {
  for (const s of ["loginScreen", "expiredScreen", "keyScreen", "ptypeScreen", "verifyScreen", "nickScreen", "app"]) $("#" + s).classList.toggle("hidden", s !== id);
  document.body.classList.toggle("has-modebar", id === "app");
  // botão de som: no cabeçalho dentro do app; flutuando no canto nas outras telas
  const snd = $("#sound"), inApp = id === "app";
  snd.classList.toggle("floating", !inApp);
  (inApp ? $("#soundSlot") : document.body).appendChild(snd);
  if (!inApp) Music.forPage(null);
}
function openApp(landing = "home") {
  if (!S.mode) { S.mode = "solo"; S.btab = "solo"; }
  paintMode();
  $("#topWho").textContent = S.nick;
  $("#brandHome").dataset.nick = S.nick;
  $("#drawerName").textContent = S.nick;
  paintAvatar($("#drawerAvatar"), S.nick, S.char && S.char.vocation);
  $("#drawerInfo").textContent = `Level ${S.char.level} · ${S.char.vocation} · ${S.char.world}`;
  updateDrawerFoot();
  $("#lootResult").innerHTML = ""; $("#stackResult").innerHTML = ""; $("#bossResult").innerHTML = ""; $("#bossAsk").innerHTML = "";
  $("#readonlyBar").classList.toggle("hidden", !(S.me && S.me.readonly));  // 0.22.3: conta de visitante
  showOnly("app");
  S.navStack = [];
  S.page = null;
  go(landing, { noPush: true });
  refreshChangesFab().catch(() => {});
  setTimeout(offerInstall, 2500);
  setTimeout(flushDrafts, 1500);
}
/** 0.23.0: o envio foi salvo em outro personagem seu (o que estava na PT): ele vira o personagem ativo. */
async function switchActiveChar(name) {
  if (!name || name.toLowerCase() === (S.nick || "").toLowerCase()) return;
  try { S.char = await api("GET", `/api/character/${encodeURIComponent(name)}`); }
  catch { S.char = { ...(S.char || {}), name }; }
  S.nick = S.char.name || name;
  await kv.set("nick", S.nick);
  $("#topWho").textContent = S.nick;
  $("#brandHome").dataset.nick = S.nick;
  $("#drawerName").textContent = S.nick;
  paintAvatar($("#drawerAvatar"), S.nick, S.char.vocation);
  if (S.char.level) $("#drawerInfo").textContent = `Level ${S.char.level} · ${S.char.vocation} · ${S.char.world}`;
}
/** "Sir Kalor" → "SK"; "Druida" → "DR". Só para o círculo dourado do menu. */
function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : parts[0].slice(0, 2)).toUpperCase();
}
// entrada em cascata dos itens do menu (o atraso de cada um vem de --i)
[...$("#drawer").children].forEach((c, i) => c.style.setProperty("--i", i));
let srvCheckedAt = 0;
async function paintServerStatus() {
  if (Date.now() - srvCheckedAt < 30000) return;  // no máximo uma conferência a cada 30 s
  srvCheckedAt = Date.now();
  const box = $("#srvStatus"), ok = await serverOk();
  box.classList.toggle("on", ok); box.classList.toggle("off", !ok);
  box.querySelector("span").textContent = ok ? "Servidor online" : "Servidor fora do ar";
}
/** Contador dourado ao lado do item do menu (0 ou vazio esconde). */
function setBadge(id, n) {
  const b = $("#" + id);
  b.textContent = n > 99 ? "99+" : String(n || "");
  b.classList.toggle("hidden", !n);
  if (id === "lootBadge") setBadge("partyBadge", n);  // 0.22.0: aparece também no botão Party do rodapé
}
function openDrawer() { $("#drawer").classList.add("open"); $("#scrim").classList.add("open"); paintServerStatus(); }
function closeDrawer() { $("#drawer").classList.remove("open"); $("#scrim").classList.remove("open"); }
$("#burger").addEventListener("click", openDrawer);
$("#scrim").addEventListener("click", closeDrawer);
document.querySelectorAll("#drawer [data-page]").forEach((b) => b.addEventListener("click", async () => {
  closeDrawer();
  if (b.dataset.page === "loot" && !$("#lootBadge").classList.contains("hidden")) return goPending();  // tem acerto pendente: já abre nele
  // 0.22.2: item de um galho (Solo/Party) também escolhe o modo
  if (b.dataset.mode && b.dataset.mode !== S.mode) {
    await setMode(b.dataset.mode, { nav: false });
    if (S.page === b.dataset.page) {  // mesma tela, outro modo: redesenha ali
      if (S.page === "boss") { showBossTab(S.mode); renderBoss(); }
      if (S.page === "hunts") loadHunts();
      return;
    }
  }
  if (S.page !== b.dataset.page) go(b.dataset.page);
  if (b.dataset.open === "stack") openStackFlow();  // 0.20.0: Solo → Stacker já abre a janela para colar
}));
document.querySelectorAll("#drawer [data-mode-set]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.modeSet)));
$("#changeNick").addEventListener("click", () => { closeDrawer(); $("#nickInput").value = ""; showNick(false); });
$("#nickBack").addEventListener("click", () => showOnly("app"));
$("#brandHome").addEventListener("click", () => { closeDrawer(); if (S.page !== "home") go("home"); else window.scrollTo(0, 0); });
$("#backBtn").addEventListener("click", goBack);
$("#gearBtn").addEventListener("click", () => { closeDrawer(); if (S.page !== "settings") go("settings"); });

/* ---------- ⚙️ configurações: idioma (0.19.0) ---------- */
// Padrão: português (Brasil). Só a escolha feita nos botões fica salva neste aparelho
// (no app de Windows, junto com as outras preferências dele).
const saveLang = (code) => kv.set(I18N.STORE, code);
I18N.picker($("#settingsLang"), saveLang);
I18N.picker($("#loginLang"), saveLang);
async function loadSavedLang() {
  const saved = await kv.get(I18N.STORE).catch(() => null);
  if (saved && saved !== I18N.lang) await I18N.use(saved);
}
/* ---------- ⚙️ configurações: tipo de player (0.20.0) ---------- */
// Vale para a conta (fica no servidor). Decide o que o app pergunta depois de salvar e o que a pessoa compartilha.
// O que cada tipo é (aparece ao passar o mouse e na escolha da criação da conta).
const PTYPES = {
  hardcore: { ic: "🔥", label: "Player Hardcore",
    desc: "Acesso free. Você quer compartilhar todas as informações possíveis para melhorar o seu estilo de jogo, as hunts, os locais de caça, o profit e a XP: do Hunt Analyser ao lootsplit, o local de hunt, o Input Analyser, a Wheel of Destiny, quando fez o último imbuimento e quanto gastou nos imbuimentos." },
  comum: { ic: "⚔️", label: "Player Comum",
    desc: "Acesso free. Você não se considera mais um novato e quer compartilhar, às vezes, algumas informações mais precisas, como o local de hunt e o Input Analyser." },
  novato: { ic: "🌱", label: "Player Novato",
    desc: "Acesso free. Você quer apenas usar a ferramenta: ainda não sabe muito bem o que tudo faz, mas está aprendendo." },
};
// O que o app faz para cada tipo (dica embaixo da escolha em ⚙️ Configurações).
const PTYPE_INFO = {
  hardcore: "🔥 Depois de salvar uma sessão, o app pergunta a hunt e o Input Analyser. No lootsplit, você junta o seu Hunt Analyser e o Input Analyser para a PT ver.",
  comum: "⚔️ Depois de salvar uma sessão, o app pergunta em qual hunt foi. Quando quiser, você junta o Input Analyser e, no lootsplit, a sua sessão.",
  novato: "🌱 O app só salva, sem perguntas. Quando quiser, toque em \"hunt sem local\" para dizer onde foi.",
};
const ptype = () => (S.me && S.me.player_type) || "comum";
const isHardcore = (t = ptype()) => ((S.me && S.me.hardcore_types) || ["hardcore"]).includes(t);
const canShare = (t = ptype()) => t !== "novato";
const ptypeList = () => (S.me && S.me.player_types) || ["hardcore", "comum", "novato"];
function ptypeInfo(t) {
  if (PTYPES[t]) return PTYPES[t];
  const x = ((S.me && S.me.player_type_info) || {})[t] || {};  // tipo novo ligado no servidor
  return { ic: x.icon || "⭐", label: x.label || t, desc: x.description || "" };
}
function ptypeButtons(current) {
  return ptypeList().map((t) => {
    const p = ptypeInfo(t), on = t === current;
    return `<button type="button" data-ptype="${t}" role="radio" aria-checked="${on}" class="${on ? "on" : ""}" title="${esc(p.desc)}">
      <span class="pt-ic" aria-hidden="true">${p.ic}</span><span><b>${esc(p.label)}</b>${on && current ? `<span class="pt-cur">(Atual)</span>` : ""}</span></button>`;
  }).join("");
}
function paintPlayerType() {
  $("#playerTypes").innerHTML = ptypeButtons(ptype());
  $("#playerTypeHint").textContent = PTYPE_INFO[isHardcore() ? "hardcore" : ptype()] || "";
}
$("#playerTypes").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-ptype]");
  if (!b || b.dataset.ptype === ptype()) return;  // clicar no tipo atual não faz nada
  const label = ptypeInfo(b.dataset.ptype).label;
  if (!confirm(`Tem certeza que deseja alterar o seu tipo de player para ${label}?`)) return;
  $("#playerTypeErr").textContent = "";
  try { S.me = await api("POST", "/api/prefs/player-type", { player_type: b.dataset.ptype }); paintPlayerType(); }
  catch (err) { if (err.status !== 401) $("#playerTypeErr").textContent = err.message; }
});

/** 0.20.0: "Você se considera um:" — na criação da conta, antes de informar o main (e uma vez para quem já tinha conta). */
function askPlayerType(onPicked) {
  showOnly("ptypeScreen");
  let picked = null;
  const box = $("#ptypeAsk"), desc = $("#ptypeAskDesc"), go = $("#ptypeAskGo");
  box.innerHTML = ptypeButtons(null);
  desc.classList.add("hidden"); go.classList.add("hidden");
  box.onclick = (e) => {
    const b = e.target.closest("[data-ptype]");
    if (!b) return;
    picked = b.dataset.ptype;
    box.querySelectorAll("[data-ptype]").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", String(x === b)); });
    const p = ptypeInfo(picked);
    desc.innerHTML = `<b>${p.ic} ${esc(p.label)}</b><div style="margin-top:4px">${esc(p.desc)}</div>`;
    desc.classList.remove("hidden"); go.classList.remove("hidden");
  };
  go.onclick = async () => { if (picked) { go.disabled = true; await onPicked(picked); go.disabled = false; } };
}
/** Escolha feita antes do personagem estar verificado: guarda e envia assim que houver sessão. */
async function savePendingPlayerType() {
  const t = await kv.get("ptype_pending");
  if (!t || !S.token) return;
  try { S.me = await api("POST", "/api/prefs/player-type", { player_type: t }); } catch {}
  await kv.set("ptype_pending", null);
}

// trocou o idioma: as Novidades na tela são redesenhadas no idioma novo
I18N.onChange(async () => {
  if (S.page === "news" && $("#newsList").innerHTML) loadNews();
  // 0.22.2: notícias, CMs e calendário vêm traduzidos do servidor no idioma escolhido
  if (S.page === "tnews") loadTnews();
  if (S.page === "cms") loadCms();
  if (S.page === "cal") loadCal();
  if (S.page === "home") loadHome();
  const n = $("#newsNotice");
  if (n) { const html = await newsNotice(); if (html) n.outerHTML = html; }
});

/* ---------- voltar: botão ← e o "voltar" do celular/navegador ---------- */
S.navStack = [];
function pushNav() {
  if (!S.page || $("#app").classList.contains("hidden")) return;
  S.navStack.push({ page: S.page, htab: S.htab });
  try { history.pushState({ nav: S.navStack.length }, ""); } catch {}
}
function goBack() {
  closeDrawer();
  if (S.navStack.length) { try { history.back(); } catch { restoreNav(); } }
  else if (S.page !== "home") go("home", { noPush: true });
}
function restoreNav() {
  const st = S.navStack.pop();
  if (!st) { if (S.page !== "home") go("home", { noPush: true }); return; }
  if (st.page === "hunts" && S.page === "hunts") { showHuntTab(st.htab); return; }
  if (st.page === "parties" && S.page === "parties" && PT.vault) { PT.vault = null; loadParties(); return; }  // 0.24.0: cofre → lista
  if (st.htab) S.htab = st.htab;
  go(st.page, { noPush: true });
}
window.addEventListener("popstate", () => {
  if (Overlay.closeTop()) return;  // 0.21.0: "voltar" fecha primeiro a tela de contato/créditos
  if ($("#app").classList.contains("hidden")) return;
  if ($("#drawer").classList.contains("open")) { closeDrawer(); }
  restoreNav();
});
function updateBack() {
  $("#backBtn").classList.toggle("hidden", !(S.navStack.length || S.page !== "home"));
}
$("#logout").addEventListener("click", () => accountOut(""));

function go(page, opts = {}) {
  if (!opts.noPush && page !== S.page) pushNav();
  Track.view(page);
  S.page = page;
  document.body.classList.toggle("no-mode", !MODE_PAGES.has(page));
  updateBack();
  markActive();
  $("#pageHome").classList.toggle("hidden", page !== "home");
  $("#pageBoss").classList.toggle("hidden", page !== "boss");
  $("#pageLoot").classList.toggle("hidden", page !== "loot");
  $("#pageStack").classList.toggle("hidden", page !== "stack");
  $("#pageChars").classList.toggle("hidden", page !== "chars");
  $("#pageHunts").classList.toggle("hidden", page !== "hunts");
  $("#pageNews").classList.toggle("hidden", page !== "news");
  $("#pageTnews").classList.toggle("hidden", page !== "tnews");
  $("#pageCms").classList.toggle("hidden", page !== "cms");
  $("#pageCal").classList.toggle("hidden", page !== "cal");
  $("#pageAch").classList.toggle("hidden", page !== "ach");
  $("#pageRank").classList.toggle("hidden", page !== "rank");
  $("#pageVip").classList.toggle("hidden", page !== "vip");
  $("#pageSettings").classList.toggle("hidden", page !== "settings");
  $("#pageSubs").classList.toggle("hidden", page !== "subs");
  $("#pageParties").classList.toggle("hidden", page !== "parties");
  $("#gearBtn").classList.toggle("on", page === "settings");
  if (page === "subs") loadSubs();
  if (page === "parties") { if (!opts.noPush) PT.vault = null; loadParties(); }
  Music.forPage(page);
  if (page === "rank") loadRankings();
  if (page === "vip") loadVip();
  if (page === "news") loadNews();
  if (page === "tnews") loadTnews();
  if (page === "cal") loadCal();
  if (page === "cms") { if (!$("#cmsFrom").value) cmsDefaults(); loadCms(); }
  if (page === "ach") loadAch();
  window.scrollTo(0, 0);
  if (page === "home") loadHome();
  if (page === "stack") loadStack();
  if (page === "boss") { showBossTab(S.mode); loadBoss(); }
  if (page === "hunts") loadHunts();
  if (page === "loot") loadLootList();
  if (page === "chars") loadChars();
  if (page === "settings") { paintPlayerType(); api("GET", "/api/me").then((m) => { S.me = m; paintPlayerType(); }).catch(() => {}); }
}
function updateDrawerFoot() {
  const exp = (S.me && S.me.expires_at) || S.keyExpires;
  $("#renewItem").classList.toggle("hidden", !canRenew());  // vitalício ou com 3 dias ou mais: nada para renovar
  $("#drawerFoot").innerHTML = `${S.me && S.me.main_char ? "Main: <b>" + esc(S.me.main_char) + "</b><br>" : ""}`
    + `${exp ? "Código válido até " + esc(new Date(exp).toLocaleDateString("pt-BR")) + "<br>" : ""}versão ${esc(S.version || "")}`;
}

/* ---------- meus personagens ---------- */
function renderChars() {
  const chars = (S.me && S.me.chars) || [];
  $("#charsList").innerHTML = chars.map((c) => `<div class="card row">
      <div><b>${esc(c.name)}</b>${c.is_main ? '<span class="pill">main</span>' : ""}
        <div class="muted">verificado em ${esc(new Date(c.verified_at).toLocaleDateString("pt-BR"))}</div></div>
      <div style="display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end">
        <button class="btn2" data-view="${esc(c.name)}">Ver</button>
        ${c.is_main ? "" : `<button class="btn2" data-main="${esc(c.name)}">Tornar main</button>
                            <button class="btn2" data-unlink="${esc(c.name)}">Remover</button>`}
      </div></div>`).join("") || `<p class="muted">Nenhum personagem vinculado.</p>`;
}
async function loadChars() {
  try { S.me = await api("GET", "/api/me"); } catch { return; }
  renderChars();
  updateDrawerFoot();
  verifyWidget($("#linkBox"), {
    title: "Nome do personagem para vincular",
    onDone: async (r) => { S.me = r.me; renderChars(); updateDrawerFoot(); loadChars(); },
  });
}
$("#charsList").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  try {
    if (b.dataset.view) { S.char = await api("GET", `/api/character/${encodeURIComponent(b.dataset.view)}`); S.nick = S.char.name; await kv.set("nick", S.nick); openApp(); }
    if (b.dataset.main) { S.me = await api("POST", "/api/chars/main", { character: b.dataset.main }); renderChars(); updateDrawerFoot(); }
    if (b.dataset.unlink && confirm(`Remover ${b.dataset.unlink} dos seus personagens?`)) {
      S.me = await api("DELETE", `/api/chars/${encodeURIComponent(b.dataset.unlink)}`); renderChars();
    }
  } catch (err) { if (err.status !== 401) alert(err.message); }
});

/* ---------- lootsplit: blocos visuais ---------- */
function view(h, name) {
  const key = name.toLowerCase();
  const pays = h.transfers.filter((t) => t.payer.toLowerCase() === key);
  const gets = h.transfers.filter((t) => t.receiver.toLowerCase() === key);
  const me = h.players.find((p) => p.name.toLowerCase() === key);
  return { inParty: !!me, pays, gets, profit: me && me.profit != null ? me.profit : h.profit_each,
           totalPay: pays.reduce((a, t) => a + t.amount, 0), totalGet: gets.reduce((a, t) => a + t.amount, 0),
           pendingPay: pays.filter((t) => !t.paid_at).reduce((a, t) => a + t.amount, 0),
           pendingGet: gets.filter((t) => !t.paid_at).reduce((a, t) => a + t.amount, 0) };
}
/** Personagem vinculado ao código de quem está usando o app (pode marcar "já paguei"/"recebi"). */
const isMine = (name) => ((S.me && S.me.chars) || []).some((c) => c.name.toLowerCase() === String(name).toLowerCase());
const huntBase = (h) => h.kind === "boss" ? `/api/bosses/hunt/${h.id}` : `/api/hunt/${h.id}`;
const HUNTS_BY_ID = new Map();  // "kind:id" -> hunt mostrada (para os botões de pagamento e regras)
const huntRef = (h) => { const k = `${h.kind || "hunt"}:${h.id}`; if (h.id) HUNTS_BY_ID.set(k, h); return k; };
function paidButton(h, t) {
  if (!h.id) return "";
  const ref = huntRef(h), party = isMine(t.payer) || isMine(t.receiver), leader = isLeader(h), canMark = party || leader;
  if (t.paid_at) return `<span class="pos" style="font-size:13px">✔ pago ${esc(new Date(t.paid_at).toLocaleDateString("pt-BR"))}</span>
    ${canMark ? `<button class="link" style="font-size:13px" data-paid="${ref}" data-payer="${esc(t.payer)}" data-receiver="${esc(t.receiver)}" data-set="0">desfazer</button>` : ""}`;
  if (!canMark) return `<span class="muted" style="font-size:13px">⏳ falta pagar</span>`;
  // 0.29.0: o líder da PT confirma por quem esqueceu de marcar
  const label = !party ? "✔ Confirmar pagamento (líder)" : t.receiver.toLowerCase() !== (S.nick || "").toLowerCase() && isMine(t.payer) ? "✔ Já paguei" : "✔ Recebi";
  return `<button class="btn2" style="padding:4px 10px; font-size:13px" data-paid="${ref}" data-payer="${esc(t.payer)}" data-receiver="${esc(t.receiver)}" data-set="1">${label}</button>`;
}
/** Líder da PT: quem enviou o lootsplit ou o personagem marcado como líder no relatório. */
const isLeader = (h) => !!h.can_delete || (h.players || []).some((p) => p.is_leader && isMine(p.name));
function actionBox(v, h) {
  if (!v.inParty) return "";
  if (v.totalPay > 0) return `<div class="action pay"><div class="title">${v.pendingPay ? `Você deve transferir ${fmt(v.pendingPay)} gp` : `Você já pagou tudo ✔ (${fmt(v.totalPay)} gp)`}</div>
    ${v.pays.map((t) => `<div class="tx"><div class="row"><span>para <b>${esc(t.receiver)}</b></span><b>${fmt(t.amount)}</b></div>
      <div class="row"><code>${esc(t.command)}</code><button class="copy" data-copy="${esc(t.command)}">Copiar</button></div>
      ${h ? `<div class="row" style="justify-content:flex-end">${paidButton(h, t)}</div>` : ""}</div>`).join("")}</div>`;
  if (v.totalGet > 0) return `<div class="action get"><div class="title">${v.pendingGet ? `Você vai receber ${fmt(v.pendingGet)} gp` : `Você já recebeu tudo ✔ (${fmt(v.totalGet)} gp)`}</div>
    ${v.gets.map((t) => `<div class="tx row"><span>de <b>${esc(t.payer)}</b> · <b>${fmt(t.amount)}</b></span>${h ? paidButton(h, t) : ""}</div>`).join("")}</div>`;
  return `<div class="action none"><div class="title">Nada a transferir nesta hunt</div></div>`;
}
function transfersBox(h) {
  if (!h.transfers.length) return `<p class="muted">Ninguém precisa transferir.</p>`;
  const pending = h.transfers.filter((t) => !t.paid_at).length;
  return (h.id ? `<div class="muted" style="font-size:13px; margin-bottom:4px">${pending ? `⏳ ${pending} de ${h.transfers.length} transferências ainda não foram marcadas como pagas.` : "✔ Todas as transferências foram pagas."}</div>` : "")
    + h.transfers.map((t) => `<div class="tx"><div class="row"><span><b>${esc(t.payer)}</b>${whoTags(h, t.payer)} → <b>${esc(t.receiver)}</b>${whoTags(h, t.receiver)}</span><b class="gold">${fmt(t.amount)}</b></div>
    <div class="row"><code>${esc(t.command)}</code><button class="copy" data-copy="${esc(t.command)}">Copiar</button></div>
    ${h.id ? `<div class="row" style="justify-content:flex-end">${paidButton(h, t)}</div>` : ""}</div>`).join("");
}
function rulesLine(h) {
  if (!h.rules) return "";
  const parts = [...h.rules.excluded.map((n) => `${esc(n)} fora da divisão`),
                 ...Object.entries(h.rules.fixed).map(([n, v]) => `${esc(n)} fica com ${kk(v)} fixo`)];
  return `<div class="banner ok" style="margin-top:8px">⚖️ Regras de divisão: ${parts.join("; ")}. Quem divide igual fica com ${fmt(h.profit_each)} gp.</div>`;
}
/** ⚖️ Regras de divisão (só quem enviou o lootsplit edita). */
function rulesBox(h) {
  if (!h.can_delete || !h.id) return "";
  const ref = huntRef(h), r = h.rules || { excluded: [], fixed: {} };
  const rows = h.players.map((p) => {
    const mode = r.excluded.includes(p.name) ? "out" : p.name in r.fixed ? "fixed" : "equal";
    return `<div class="row" style="padding:6px 0; border-bottom:1px solid var(--line); flex-wrap:wrap" data-rule-player="${esc(p.name)}">
      <b style="flex:1 1 120px">${vdot(p.name)}${esc(p.name)}</b>
      <select data-rule-mode style="padding:6px 8px; border-radius:8px; background:var(--card2); color:var(--text); border:1px solid var(--line)">
        <option value="equal"${mode === "equal" ? " selected" : ""}>Divide igual</option>
        <option value="out"${mode === "out" ? " selected" : ""}>Fora da divisão</option>
        <option value="fixed"${mode === "fixed" ? " selected" : ""}>Valor fixo</option></select>
      <input data-rule-value type="number" min="0" step="1" inputmode="numeric" placeholder="gp" value="${mode === "fixed" ? r.fixed[p.name] : ""}"
        class="${mode === "fixed" ? "" : "hidden"}" style="width:130px; padding:6px 8px" aria-label="Valor fixo de ${esc(p.name)}"></div>`;
  }).join("");
  return `<details style="margin-top:10px"><summary class="link">⚖️ Regras de divisão ${h.rules ? "(ativas)" : ""} ▾</summary>
    <p class="hint">Fora da divisão: a pessoa recebe de volta os supplies e entrega o loot (termina com 0 de lucro).
      Valor fixo: termina com aquele lucro (ex.: quem só ajudou no boss). O resto divide igual. Mudar as regras apaga as marcações de "já paguei".</p>
    <div data-rules="${ref}">${rows}</div>
    <div class="row" style="gap:8px; margin-top:8px; justify-content:flex-start">
      <button class="btn2" data-rules-save="${ref}">Salvar regras</button>
      ${h.rules ? `<button class="link" data-rules-clear="${ref}">Voltar a dividir igual para todos</button>` : ""}</div>
    <div class="err" data-rules-err="${ref}"></div></details>`;
}
async function afterHuntChange(h) {
  h.kind = h.kind || (S.page === "boss" ? "boss" : undefined);
  if (S.page === "home") return loadHome();
  if (S.page === "boss") return loadBoss({ quiet: true });
  if (S.page === "loot") { renderLoot(h); loadLootList(); }
}
document.addEventListener("change", (e) => {
  const sel = e.target.closest("[data-rule-mode]");
  if (sel) sel.parentElement.querySelector("[data-rule-value]").classList.toggle("hidden", sel.value !== "fixed");
});
document.addEventListener("click", async (e) => {
  const paid = e.target.closest("[data-paid]");
  const save = e.target.closest("[data-rules-save],[data-rules-clear]");
  if (!paid && !save) return;
  e.preventDefault();
  const ref = paid ? paid.dataset.paid : (save.dataset.rulesSave || save.dataset.rulesClear);
  const h = HUNTS_BY_ID.get(ref);
  if (!h) return;
  const btn = paid || save; btn.disabled = true;
  try {
    let r;
    if (paid) {
      r = await api("POST", huntBase(h) + "/paid", { payer: paid.dataset.payer, receiver: paid.dataset.receiver, paid: paid.dataset.set === "1" });
    } else {
      const body = { excluded: [], fixed: {} };
      if (save.dataset.rulesSave) {
        for (const row of document.querySelectorAll(`[data-rules="${ref}"] [data-rule-player]`)) {
          const mode = row.querySelector("[data-rule-mode]").value, name = row.dataset.rulePlayer;
          if (mode === "out") body.excluded.push(name);
          if (mode === "fixed") {
            const v = parseInt(row.querySelector("[data-rule-value]").value, 10);
            if (!(v >= 0)) { document.querySelector(`[data-rules-err="${ref}"]`).textContent = `Informe o valor fixo de ${name}.`; btn.disabled = false; return; }
            body.fixed[name] = v;
          }
        }
      }
      r = await api("POST", huntBase(h) + "/rules", body);
    }
    r.hunt.kind = h.kind;
    await afterHuntChange(r.hunt);
    if (S.homeHunts) {  // contador de acertos do menu sem esperar voltar ao Início
      S.homeHunts = S.homeHunts.map((x) => (huntRef(x) === huntRef(r.hunt) ? r.hunt : x));
      setBadge("lootBadge", S.homeHunts.filter((x) => { const v = view(x, S.nick); return v.pendingPay || v.pendingGet; }).length);
    }
  } catch (err) {
    btn.disabled = false;
    if (err.status === 401) return;
    const box = document.querySelector(`[data-rules-err="${ref}"]`);
    if (save && box) box.textContent = err.message; else alert(err.message);
  }
});
/** 0.23.0: 🤝 jogado por outra pessoa / 🔁 substituto, ao lado do nome do jogador. */
function whoTags(h, name) {
  const t = (h.tags || {})[name];
  if (!t) return "";
  let out = "";
  if (t.other) out += `<span class="who other" title="${t.played_by ? esc(`Jogado por ${t.played_by}`) : "Jogado por outra pessoa"}">${t.played_by ? "🤝 " + esc(t.played_by) : "🤝 outra pessoa"}</span>`;
  if (t.sub) out += `<span class="who sub" title="${t.sub.auto ? "Descoberto pelo app: não é da formação de sempre" : "Marcado pela PT"}">${t.sub.for ? esc(`🔁 no lugar de ${t.sub.for}`) : "🔁 substituto"}</span>`;
  return out;
}
/** 0.23.0: lootsplit enviado por quem não estava na PT: um membro assume. */
function claimBanner(h) {
  if (!h.can_claim || !h.id) return "";
  return `<div class="banner bad"><b>Este lootsplit foi enviado por alguém que não estava na PT.</b>
    <div class="hint">Assuma para poder mudar as regras de divisão, a hunt e apagar se precisar.</div>
    <button class="btn2" style="margin-top:8px" data-claim="${huntRef(h)}">Assumir este lootsplit</button></div>`;
}
/** 0.23.0: marcações da PT (🔁 substituto para qualquer um da PT; 🤝 "não fui eu que joguei" só no seu personagem). */
function tagsBox(h) {
  if (!h.id || !h.in_party && h.kind !== "boss") return "";
  if (h.kind === "boss" && !h.players.some((p) => isMine(p.name))) return "";
  const ref = huntRef(h);
  const rows = h.players.map((p) => {
    const t = (h.tags || {})[p.name] || {}, mine = isMine(p.name);
    const sub = t.sub_manual === "sub" ? "yes" : t.sub_manual === "nosub" ? "no" : "auto";
    const autoLabel = t.sub && t.sub.auto ? "🔁 Automático (substituto)" : "Automático";
    return `<div class="tags-row" data-tag-player="${esc(p.name)}"><b>${vdot(p.name)}${esc(p.name)}</b>
      <select data-tag-sub aria-label="${esc(`Substituto: ${p.name}`)}">
        <option value="auto"${sub === "auto" ? " selected" : ""}>${autoLabel}</option>
        <option value="yes"${sub === "yes" ? " selected" : ""}>🔁 É substituto</option>
        <option value="no"${sub === "no" ? " selected" : ""}>Não é substituto</option></select>
      ${mine ? `<label class="check-row"><input type="checkbox" data-tag-other${t.other ? " checked" : ""}> 🤝 Não fui eu que joguei</label>
        <input type="text" data-tag-by maxlength="40" placeholder="Quem jogou (opcional)" value="${esc(t.played_by || "")}"
          class="${t.other ? "" : "hidden"}" autocomplete="off" aria-label="Quem jogou (opcional)">` : ""}</div>`;
  }).join("");
  return `<details style="margin-top:10px"><summary class="link">🤝 Substitutos e quem jogou ▾</summary>
    <p class="hint">🔁 Substituto: quem entrou no lugar de alguém da PT de sempre (o app tenta descobrir sozinho).
      🤝 Não fui eu que joguei: outra pessoa jogou no seu personagem; esta hunt sai das suas comparações de desempenho.</p>
    <div class="tags-grid" data-tags="${ref}">${rows}</div>
    <div class="row" style="justify-content:flex-start; margin-top:8px"><button class="btn2" data-tags-save="${ref}">Salvar marcações</button></div>
    <div class="err" data-tags-err="${ref}"></div></details>`;
}
document.addEventListener("change", (e) => {
  const cb = e.target.closest("[data-tag-other]");
  if (cb) cb.closest(".tags-row").querySelector("[data-tag-by]").classList.toggle("hidden", !cb.checked);
});
document.addEventListener("click", async (e) => {
  const save = e.target.closest("[data-tags-save]"), claim = e.target.closest("[data-claim]");
  if (!save && !claim) return;
  e.preventDefault();
  const ref = (save || claim).dataset.tagsSave || (save || claim).dataset.claim;
  const h = HUNTS_BY_ID.get(ref);
  if (!h) return;
  const btn = save || claim; btn.disabled = true;
  const errBox = document.querySelector(`[data-tags-err="${ref}"]`);
  if (errBox) errBox.textContent = "";
  try {
    let r = null;
    if (claim) r = await api("POST", huntBase(h) + "/claim");
    else {
      for (const row of document.querySelectorAll(`[data-tags="${ref}"] [data-tag-player]`)) {
        const name = row.dataset.tagPlayer, t = (h.tags || {})[name] || {};
        const before = t.sub_manual === "sub" ? "yes" : t.sub_manual === "nosub" ? "no" : "auto";
        const body = { name };
        const sub = row.querySelector("[data-tag-sub]").value;
        if (sub !== before) body.sub = sub;
        const other = row.querySelector("[data-tag-other]");
        if (other) {
          const by = row.querySelector("[data-tag-by]").value.trim();
          if (other.checked !== !!t.other || (other.checked && by !== (t.played_by || ""))) { body.other = other.checked; if (by) body.played_by = by; }
        }
        if (Object.keys(body).length > 1) r = await api("POST", huntBase(h) + "/tags", body);
      }
    }
    if (r) { r.hunt.kind = h.kind; await afterHuntChange(r.hunt); }
    else btn.disabled = false;
  } catch (err) {
    btn.disabled = false;
    if (err.status === 401) return;
    if (errBox) errBox.textContent = err.message; else alert(err.message);
  }
});
function partyTable(h, name) {
  const key = (name || "").toLowerCase();
  return `<div class="table-wrap"><table><tr><th>Jogador</th><th>Loot</th><th>Supplies</th><th>Balance</th><th>Damage</th><th>Healing</th><th>Acerto</th></tr>
    ${h.players.map((p) => `<tr class="${p.name.toLowerCase() === key ? "me" : ""}">
      <td>${vdot(p.name)}${esc(p.name)}${p.is_leader ? " 👑" : ""}${whoTags(h, p.name)}</td><td>${kk(p.loot)}</td><td>${kk(p.supplies)}</td><td>${kk(p.balance)}</td>
      <td>${kk(p.damage)}</td><td>${kk(p.healing)}</td>
      <td class="${p.diff > 0 ? "neg" : p.diff < 0 ? "pos" : ""}">${p.diff > 0 ? "paga " + kk(p.diff) : p.diff < 0 ? "recebe " + kk(-p.diff) : "—"}</td></tr>`).join("")}
  </table></div>`;
}
function huntCard(h, name, title) {
  const cls = h.profit_each >= 0 ? "gold" : "neg";
  return `<div class="card">
    <div class="muted">${esc(title)} · ${when(h.started_at)} · ${dur(h.duration_seconds)} · ${h.players_count} jogadores</div>
    ${dupBox(h)}${claimBanner(h)}
    ${huntPlaceRow(h)}
    <div style="margin-top:10px" class="muted">Rendeu para cada um</div>
    <div class="big ${cls}" data-count="${h.profit_each}" data-suffix=" gp">${fmt(h.profit_each)} gp</div>
    <div class="muted"><b class="${cls}">${fmt(h.profit_each_per_hour)} gp/h</b> por pessoa · total da PT ${fmt(h.balance)} gp</div>
    ${rulesLine(h)}
    ${actionBox(view(h, name), h)}
    ${chartToggle(h, name)} ${shareButton("hunt", h)}
    ${h.kind === "boss" ? "" : partyShared(h)}
    <details style="margin-top:4px"><summary class="link">Transferências e detalhes da PT ▾</summary>
      <h2>Transferências</h2>${transfersBox(h)}
      <h2>Jogadores</h2>${partyTable(h, name)}
      <div class="muted" style="margin-top:8px"><abbr title="Valor de todo o loot pego pela PT">Loot</abbr> ${fmt(h.loot)} · <abbr title="Gasto com comida, runas e potions">Supplies</abbr> ${fmt(h.supplies)} · <abbr title="Como o Party Hunt Analyser valorizou o loot (campo Loot Type do relatório)">Loot type</abbr> ${esc(h.loot_type || "—")}</div>
      ${rulesBox(h)}
      ${tagsBox(h)}
      ${deleteButton(h)}
    </details>
  </div>`;
}

/* ---------- gráfico de contribuição: escondido até clicar em "Gráfico" ---------- */
const METRICS = [["damage", "Damage"], ["healing", "Healing"], ["supplies", "Supplies"], ["loot", "Loot"], ["balance", "Balance"]];
const CHART_HUNTS = new Map();
let chartSeq = 0;
function chartToggle(h, name) {
  const id = "c" + (++chartSeq);
  CHART_HUNTS.set(id, { h, name });
  return `<button class="link" data-chart-toggle="${id}" style="margin-top:10px">📊 Gráfico</button>
    <div class="chart hidden" id="${id}"></div>`;
}
function renderChart(id, metric = "damage") {
  const { h, name } = CHART_HUNTS.get(id);
  const key = name.toLowerCase();
  const label = METRICS.find(([k]) => k === metric)[1];
  const rows = h.players.map((p) => ({ n: p.name, v: p[metric] || 0, me: p.name.toLowerCase() === key }))
    .sort((a, b) => b.v - a.v);
  const seg = `<div class="seg" role="tablist">${METRICS.map(([k, t]) =>
    `<button data-metric="${k}" data-chart="${id}" class="${k === metric ? "on" : ""}" role="tab" aria-selected="${k === metric}">${t}</button>`).join("")}</div>`;
  const nm = (r) => `<span class="nm ${r.me ? "me gold" : ""}" title="${esc(r.n)}">${vdot(r.n)}${esc(r.n)}${r.me ? " (você)" : ""}</span>`;
  let body, note;
  if (metric === "balance") {
    const maxAbs = Math.max(...rows.map((r) => Math.abs(r.v)), 1);
    body = rows.map((r) => `${nm(r)}
      <div class="track div" title="${esc(r.n)}: ${fmt(r.v)} gp"><div class="fill ${r.v < 0 ? "neg" : "pos"}" style="width:${(Math.abs(r.v) / maxAbs) * 50}%"></div></div>
      <span class="val"><b>${r.v < 0 ? "−" : ""}${kk(Math.abs(r.v))}</b></span>`).join("");
    note = `Balance de cada um antes da divisão (azul = positivo, vermelho = negativo). Total da PT: ${fmt(h.balance)} gp.`;
  } else {
    const total = rows.reduce((a, r) => a + Math.max(r.v, 0), 0);
    if (!total) return (document.getElementById(id).innerHTML = seg + `<p class="muted">Sem ${label.toLowerCase()} registrado nesta hunt.</p>`);
    body = rows.map((r) => {
      const pct = (Math.max(r.v, 0) / total) * 100;
      return `${nm(r)}
        <div class="track" title="${esc(r.n)}: ${fmt(r.v)} (${pct.toFixed(1)}%)"><div class="fill voc ${r.me ? "me" : ""}" style="width:${pct}%; ${vstyle(r.n)}"></div></div>
        <span class="val"><b>${pct.toFixed(0)}%</b> · ${kk(r.v)}</span>`;
    }).join("");
    note = `Parte de cada jogador no ${label.toLowerCase()} total da hunt (${fmt(total)}). Cor da barra = vocação; contorno dourado = você.`;
  }
  document.getElementById(id).innerHTML = `${seg}<div class="bars">${body}</div><div class="chart-note">${note}</div>${vocLegend()}`;
  ensureVocations(h.players.map((p) => p.name)).then((changed) => { if (changed) renderChart(id, metric); });
}
function deleteButton(h) {
  if (!h.can_delete || !h.id) return "";
  return h.kind === "boss"
    ? `<div style="margin-top:12px"><button class="danger-link" data-del-boss-hunt="${h.id}">🗑 Apagar este lootsplit de boss</button></div>`
    : `<div style="margin-top:12px"><button class="danger-link" data-del-hunt="${h.id}">🗑 Apagar esta hunt</button></div>`;
}
/** Etiqueta do resumo: quanto paga/recebe e se já foi acertado. */
function settleTag(v) {
  if (v.totalPay > 0) return v.pendingPay ? `<span class="neg">paga ${kk(v.pendingPay)}</span>` : `<span class="pos">✔ pago</span>`;
  if (v.totalGet > 0) return v.pendingGet ? `<span class="pos">recebe ${kk(v.pendingGet)}</span>` : `<span class="pos">✔ recebido</span>`;
  return `<span class="muted">sem acerto</span>`;
}
/** 0.31.0: aviso e botão quando este lootsplit parece ser a mesma sessão de outro (enviado por outro membro). */
function dupBox(h) {
  const s = (h.similar || [])[0];
  if (!s || !h.id) return "";
  const msg = s.by ? tf("👯 Parece ser a mesma sessão de {0}, enviada por {1}.", when(s.started_at), s.by)
                   : tf("👯 Parece ser a mesma sessão de {0}.", when(s.started_at));
  return `<div class="banner bad"><b data-i18n-skip>${esc(msg)}</b>
    <div class="hint">Unir deixa só a mais completa e leva para ela o local, os Input Analysers, as marcações e os pagamentos.</div>
    <button class="btn2" style="margin-top:8px" data-merge="${h.id}:${s.id}">Unir as duas</button></div>`;
}
function historyItem(h, name) {
  const v = view(h, name);
  const dup = (h.similar || []).length ? ` <span class="dupbadge">possível duplicata</span>` : "";
  return `<details class="card" data-hid="${h.id}"><summary>
      <div class="row"><b>${when(h.started_at)}</b>${settleTag(v)}</div>
      <div class="row muted"><span>${dur(h.duration_seconds)} · ${h.players_count} jogadores${h.pending ? ` · ⏳ ${h.pending} a pagar` : ""}</span>
        <span class="${h.profit_each >= 0 ? "gold" : "neg"}">${kk(h.profit_each)} cada (${kk(h.profit_each_per_hour)}/h)</span></div>
      <div class="muted hl-place">${h.place ? `📍 <span data-i18n-skip>${esc(h.place.name)}</span>` : `<span class="muted">📍 sem local</span>`}${dup}</div>
    </summary>${dupBox(h)}${claimBanner(h)}${huntPlaceRow(h)}${rulesLine(h)}${actionBox(v, h)}${chartToggle(h, name)} ${shareButton("hunt", h)}${partyShared(h)}<h2>Transferências</h2>${transfersBox(h)}${partyTable(h, name)}${rulesBox(h)}${tagsBox(h)}${deleteButton(h)}</details>`;
}
/** 0.20.0: local do lootsplit (quem enviou define; os outros só veem). */
function huntPlaceRow(h) {
  if (!h.id || h.kind === "boss" || !("place" in h)) return "";
  return `<div class="tagline-row" style="font-size:14px">${placeTag("hunt", h)}</div>`;
}
/** Mini-gráfico de linha (SVG) para mostrar a tendência de uma lista de valores. Sem dados suficientes, não mostra nada. */
function sparkline(vals, label) {
  if (!Array.isArray(vals) || vals.length < 2) return "";
  const w = 240, hgt = 48, lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * w).toFixed(1)},${(hgt - 3 - ((v - lo) / span) * (hgt - 6)).toFixed(1)}`).join(" ");
  const last = vals[vals.length - 1];
  return `<div class="spark" role="img" aria-label="${esc(label)}: último valor ${fmt(last)}">
    <svg viewBox="0 0 ${w} ${hgt}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>
    <div class="hint" style="margin:2px 0 0"><span>${esc(label)}</span> · <span>último:</span> <b>${fmt(last)}</b></div></div>`;
}
function statGrid(items) {
  return `<div class="stats">${items.map(([k, v, cls]) => `<div class="stat"><span class="muted">${k}</span><b class="${cls || ""}">${v}</b></div>`).join("")}</div>`;
}

/* ---------- novidades (changelog) ---------- */
async function fetchNews() {
  if (!S.news) S.news = await api("GET", "/api/changelog").catch(() => null);
  return S.news;
}
/** Texto da versão no idioma escolhido (changelog.json traz "tr" com en/es/ja); sem tradução, o português. */
function newsText(r) {
  const tr = r.tr && I18N.lang !== "pt-BR" && r.tr[I18N.lang];
  return tr && Array.isArray(tr.changes) && tr.changes.length === r.changes.length ? tr : r;
}
const newsItems = (n) => `<ul class="news-list" data-i18n-skip>${n.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`;
function releaseCard(r, highlight) {
  const d = r.date ? new Date(r.date + "T12:00:00").toLocaleDateString("pt-BR") : "";
  const n = newsText(r);
  return `<div class="card${highlight ? " news-new" : ""}">
    <div class="row"><b><span>Versão ${esc(r.version)}</span>${n.title ? `<span data-i18n-skip> · ${esc(n.title)}</span>` : ""}</b><span class="muted" style="font-size:13px">${esc(d)}</span></div>
    ${(n.summary || r.summary) ? `<p class="news-summary" style="margin:6px 0 2px"><b>O que muda para você:</b> <span data-i18n-skip>${esc(n.summary || r.summary)}</span></p>` : ""}
    ${newsItems(n)}</div>`;
}
async function loadNews() {
  const d = await fetchNews();
  if (!d) { $("#newsList").innerHTML = `<div class="err">Não foi possível carregar as novidades.</div>`; return; }
  $("#newsList").innerHTML = d.releases.map((r, i) => releaseCard(r, i === 0)).join("");
  await markNewsSeen();
}
/** 0.22.0: atalho fixo 🧾 no canto inferior direito; dourado enquanto houver versão não vista. */
function paintChangesFab(version, unseen) {
  if (version) $("#fabVer").textContent = `v${version}`;
  $("#fabDot").classList.toggle("hidden", !unseen);
  $("#changesFab").classList.toggle("new", !!unseen);
}
async function refreshChangesFab() {
  const d = await fetchNews();
  if (!d || !d.releases.length) return;
  const seen = await kv.get("seen_version");
  paintChangesFab(d.releases[0].version, seen !== d.releases[0].version);
  $("#newsDot").classList.toggle("hidden", seen === d.releases[0].version);  // "novo" no item 🧾 Alterações do menu
}
async function markNewsSeen() {
  const d = await fetchNews();
  if (d && d.releases.length) await kv.set("seen_version", d.releases[0].version);
  $("#newsDot").classList.add("hidden");
  paintChangesFab(d && d.releases.length ? d.releases[0].version : "", false);
}
/** Aviso no Início quando há versão nova que o usuário ainda não viu. */
async function newsNotice() {
  const d = await fetchNews();
  if (!d || !d.releases.length) return "";
  const latest = d.releases[0];
  const seen = await kv.get("seen_version");
  paintChangesFab(latest.version, seen !== latest.version);
  if (seen === latest.version) return "";
  $("#newsDot").classList.remove("hidden");
  return `<div class="card news-new" id="newsNotice">
    <div class="row"><b>🎉 Alterações da versão ${esc(latest.version)}</b><button class="link" id="newsClose" aria-label="Fechar aviso">✕</button></div>
    ${newsItems(newsText(latest))}
    <button class="link" data-page-link="news">Ver todas as versões →</button></div>`;
}
document.addEventListener("click", async (e) => {
  if (e.target.closest("#newsClose")) { $("#newsNotice").remove(); await markNewsSeen(); }
  const link = e.target.closest("[data-page-link]");
  if (link) { closeDrawer(); if (S.page !== link.dataset.pageLink) go(link.dataset.pageLink); else window.scrollTo(0, 0); }
});

/* ---------- 0.22.0: 📰 Novidades do Tibia e 💬 O que os CMs estão falando? ---------- */
// O texto das notícias vem do servidor já limpo (lista fechada de tags; imagens viram link) e fica no idioma original.
const TN_TYPE = { news: "News", ticker: "News Ticker", article: "Featured Article" };
const TN_CAT = { cipsoft: "CipSoft", community: "Community", development: "Development", support: "Support", technical: "Technical" };
const tnDate = (d) => d ? new Date(d + "T12:00:00").toLocaleDateString("pt-BR") : "";
const tnTags = (n) => `<span class="tn-tag t-${n.type}">${TN_TYPE[n.type] || esc(n.type)}</span> <span class="tn-tag">${TN_CAT[n.category] || esc(n.category)}</span>`;
const tnSource = (n) => `<a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer" style="font-size:13px">${n.translated ? "Ler o original no tibia.com ↗" : "Ler no tibia.com ↗"}</a>`
  + (n.translated ? ` <span class="hint" style="margin:0 0 0 6px">🌐 tradução automática</span>` : "");
function tnStatus(d) {
  const when = d.updated_at ? new Date(d.updated_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
  // 0.22.3: o crédito (CipSoft e TibiaData) aparece sempre, com ou sem a fonte no ar
  const credit = `<div class="hint" style="margin:0 0 10px">${when && !d.offline ? `Atualizado em ${esc(when)} · ` : ""}${TN_CREDIT}</div>`;
  return d.offline
    ? `<div class="banner bad" style="margin-bottom:10px">📴 A fonte das notícias está fora do ar ou em manutenção. Você está vendo o que já estava guardado${when ? ` (atualizado em ${esc(when)})` : ""}. As novas aparecem sozinhas quando ela voltar.</div>${credit}`
    : credit;
}
const TN_CREDIT = `conteúdo do tibia.com © CipSoft GmbH, trazido pelo <a href="https://tibiadata.com/" target="_blank" rel="noopener">TibiaData</a>`;
function tnBody(n) {
  return n.content_html != null ? `<div class="tn-body" data-i18n-skip>${n.content_html}</div>`
    : `<p class="muted">O texto desta notícia ainda não foi guardado e a fonte não respondeu agora. ${tnSource(n)}</p>`;
}
function tnCard(n, big = false) {
  return `<article class="card${big ? " news-new" : ""}">
    <div class="row" style="align-items:flex-start"><b data-i18n-skip style="font-size:${big ? 18 : 16}px">${esc(n.title)}</b><span class="muted" style="font-size:13px; white-space:nowrap">${esc(tnDate(n.date))}</span></div>
    <div style="margin:4px 0 2px">${tnTags(n)}</div>${tnBody(n)}<div>${tnSource(n)}</div></article>`;
}
async function loadTnews() {
  const el = $("#tnewsBody");
  el.innerHTML = skeleton("list");
  let d;
  try { d = await api("GET", "/api/tibia/latest?lang=" + encodeURIComponent(I18N.lang)); } catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  if (!d.total) { el.innerHTML = `<div class="card muted">As notícias ainda estão sendo buscadas pela primeira vez. Volte em alguns minutos.</div>`; return; }
  el.innerHTML = `${tnStatus(d)}
    ${d.tickers.length ? `<h2>📢 News Ticker</h2><div class="card" style="padding:4px 14px">${d.tickers.map((t) => `<details class="tn-row" style="display:block">
      <summary class="row" style="justify-content:flex-start; gap:10px"><span class="tn-date">${esc(tnDate(t.date))}</span><span class="tn-title" data-i18n-skip>${esc(t.title)}</span></summary>
      <div class="tn-open">${tnBody(t)}</div></details>`).join("")}</div>` : ""}
    ${d.featured ? `<h2>⭐ Featured Article</h2>${tnCard(d.featured, true)}` : ""}
    <h2>📰 News</h2>${d.news.map((n) => tnCard(n)).join("") || `<p class="muted">Nenhuma notícia nos últimos 90 dias.</p>`}
    <p class="hint">Quer ver notícias mais antigas ou pesquisar? Use 💬 <button class="link" data-page-link="cms">O que os CMs estão falando?</button></p>`;
}
/* filtro igual ao News Archive do tibia.com; abre com a última semana e tudo marcado */
const isoDay = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
function cmsDefaults() {
  const to = new Date(), from = new Date(Date.now() - 7 * 864e5);
  $("#cmsFrom").value = isoDay(from); $("#cmsTo").value = isoDay(to); $("#cmsQ").value = "";
  document.querySelectorAll("#cmsForm input[type=checkbox]").forEach((c) => { c.checked = true; });
}
async function loadCms() {
  const el = $("#cmsBody");
  const vals = (name) => [...document.querySelectorAll(`#cmsForm input[name=${name}]:checked`)].map((c) => c.value).join(",");
  const qs = new URLSearchParams({ from: $("#cmsFrom").value, to: $("#cmsTo").value, categories: vals("cat"), types: vals("type"),
                                   q: $("#cmsQ").value.trim(), lang: I18N.lang });
  el.innerHTML = skeleton("list");
  let d;
  try { d = await api("GET", "/api/tibia/archive?" + qs); } catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  const none = !vals("cat") || !vals("type") ? "Marque pelo menos uma categoria e um tipo." : "Nenhuma notícia com esse filtro.";
  el.innerHTML = `${tnStatus(d)}<div class="muted" style="margin:4px 0 6px">${d.count} ${d.count === 1 ? "resultado" : "resultados"} de ${esc(tnDate(d.from))} a ${esc(tnDate(d.to))}${d.count > d.rows.length ? ` (mostrando os ${d.rows.length} mais novos)` : ""}</div>
    ${d.rows.length ? `<div class="card" style="padding:4px 14px">${d.rows.map((n) => `<details class="tn-row" style="display:block" data-tn="${n.id}">
      <summary class="row" style="justify-content:flex-start; gap:10px; flex-wrap:wrap"><span class="tn-date">${esc(tnDate(n.date))}</span>
        <span class="tn-title" data-i18n-skip>${esc(n.title)}</span><span>${tnTags(n)}</span></summary>
      <div class="tn-open" data-tn-body="${n.id}"><span class="muted">Carregando…</span></div></details>`).join("")}</div>`
      : `<div class="card muted">${none}</div>`}`;
}
$("#cmsForm").addEventListener("submit", (e) => { e.preventDefault(); loadCms(); });
$("#cmsReset").addEventListener("click", () => { cmsDefaults(); loadCms(); });
/* ---------- 0.22.1: 📅 calendário de eventos (o administrador cola do tibia.com; aqui vêm só os dados) ---------- */
const CAL_COLOR = /^(#[0-9a-f]{3,8}|white)$/i;
const calColor = (c, d) => (CAL_COLOR.test(c || "") ? c : d);
const cap1 = (s) => s.charAt(0).toUpperCase() + s.slice(1);  // "novembro de 2026" → "Novembro de 2026"
const calLabel = (d) => new Date(d + "T12:00:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
function calRanges(days, name) {
  // dias seguidos do mesmo evento viram "11/11 – 15/11"
  const list = Object.keys(days).sort().filter((k) => days[k].some((e) => e.name === name));
  const out = [];
  for (const d of list) {
    const last = out[out.length - 1];
    const prev = last && new Date(new Date(last.to + "T12:00:00").getTime() + 864e5).toISOString().slice(0, 10);
    if (last && prev === d) last.to = d; else out.push({ from: d, to: d });
  }
  return out.map((r) => r.from === r.to ? calLabel(r.from) : `${calLabel(r.from)} – ${calLabel(r.to)}`).join(", ");
}
function calEventRow(name, ev, extra = "") {
  return `<div class="cal-item"><span class="cal-sw" style="background:${calColor(ev.bg, "#555")}"></span>
    <div><b data-i18n-skip>${esc(name)}</b>${extra}<div class="muted" style="font-size:14px" data-i18n-skip>${esc(ev.description || "")}</div></div></div>`;
}
function calDayInfo(c, day) {
  const items = c.days[day] || [];
  const title = new Date(day + "T12:00:00").toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
  return `<div class="card cal-info"><b>${esc(cap1(title))}</b>
    ${items.length ? items.map((e) => calEventRow(e.name, c.events[e.name] || e, e.star ? ` <span class="tn-tag" title="Começa ou termina no server save deste dia">⏱ server save</span>` : "")).join("")
      : `<p class="muted" style="margin:6px 0 0">Nenhum evento neste dia.</p>`}</div>`;
}
async function loadCal(month = "") {
  const el = $("#calBody");
  el.innerHTML = skeleton("list");
  let d;
  try { d = await api("GET", `/api/tibia/calendar?lang=${encodeURIComponent(I18N.lang)}` + (month ? "&month=" + encodeURIComponent(month) : "")); }
  catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  if (!d.calendar) { el.innerHTML = `<div class="card muted">O calendário deste mês ainda não foi publicado. Volte em breve.</div>`; return; }
  const c = d.calendar, [y, m] = d.month.split("-").map(Number);
  const first = new Date(y, m - 1, 1), start = new Date(first.getTime() - ((first.getDay() + 6) % 7) * 864e5);  // segunda-feira
  const today = isoDay(new Date());
  const lead = (first.getDay() + 6) % 7, total = Math.ceil((lead + new Date(y, m, 0).getDate()) / 7) * 7;  // semanas inteiras
  const cells = [...Array(total)].map((_, i) => isoDay(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)));
  const wd = [...Array(7)].map((_, i) => new Date(2024, 0, 1 + i).toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", ""));
  const idx = d.months.indexOf(d.month);
  const nav = (dir) => { const t = d.months[idx + dir]; return t ? `<button class="btn2" data-cal-month="${esc(t)}" aria-label="${dir < 0 ? "Mês anterior" : "Próximo mês"}">${dir < 0 ? "‹" : "›"}</button>` : `<span style="width:42px"></span>`; };
  S.cal = c;
  const sel = c.days[today] !== undefined && today.startsWith(d.month) ? today : null;
  el.innerHTML = `<div class="card">
      <div class="cal-head">${nav(-1)}<b>${esc(cap1(first.toLocaleDateString("pt-BR", { month: "long", year: "numeric" })))}</b>${nav(1)}</div>
      <div class="cal-grid">${wd.map((w) => `<div class="cal-wd">${esc(w)}</div>`).join("")}
        ${cells.map((k) => {
          const evs = c.days[k] || [], out = !k.startsWith(d.month);
          return `<button type="button" class="cal-day${out ? " out" : ""}${k === today ? " today" : ""}${k === sel ? " sel" : ""}" data-cal-day="${k}" aria-label="${esc(calLabel(k))}: ${evs.length} eventos">
            <span class="n">${Number(k.slice(8))}</span>${evs.map((e) => `<span class="cal-ev${e.star ? " star" : ""}" style="background:${calColor(e.bg, "#555")}; color:${calColor(e.fg, "#fff")}" data-i18n-skip>${e.star ? "⏱ " : ""}${esc(e.name)}</span>`).join("")}</button>`;
        }).join("")}</div>
      <div class="hint">⏱ = o evento começa ou termina no server save daquele dia. Calendário do tibia.com © CipSoft GmbH.${d.translated ? " 🌐 Descrições com tradução automática." : ""}</div>
    </div>
    <div id="calDay">${sel ? calDayInfo(c, sel) : ""}</div>
    <h2>Eventos do mês</h2><div class="card">${Object.entries(c.events).map(([n, ev]) => calEventRow(n, ev, ` <span class="muted" style="font-size:13px">· ${esc(calRanges(c.days, n))}</span>`)).join("") || `<p class="muted">Nenhum evento.</p>`}</div>`;
}
document.addEventListener("click", (e) => {
  const nav = e.target.closest("[data-cal-month]");
  if (nav) return loadCal(nav.dataset.calMonth);
  const day = e.target.closest("[data-cal-day]");
  if (!day || !S.cal) return;
  document.querySelectorAll(".cal-day.sel").forEach((x) => x.classList.remove("sel"));
  day.classList.add("sel");
  $("#calDay").innerHTML = calDayInfo(S.cal, day.dataset.calDay);
  $("#calDay").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "nearest" });
});
// abre o texto da notícia só quando a pessoa expande (vem do banco; se faltar, o servidor tenta buscar na hora)
document.addEventListener("toggle", async (e) => {
  const det = e.target;
  if (!det.matches || !det.matches("details[data-tn]") || !det.open || det.dataset.loaded) return;
  det.dataset.loaded = "1";
  const box = det.querySelector("[data-tn-body]");
  try { const n = await api("GET", `/api/tibia/news/${det.dataset.tn}?lang=${encodeURIComponent(I18N.lang)}`); box.innerHTML = tnBody(n) + `<div>${tnSource(n)}</div>`; }
  catch (err) { delete det.dataset.loaded; box.innerHTML = `<span class="err">${esc(err.message)}</span>`; }
}, true);

/* ---------- página inicial ---------- */
const EXPIRY_WARN_DAYS = 3;
/** Aviso de código de acesso vencendo (3 dias antes). */
function expiryNotice(streak) {
  return "";  // 0.20.0: a chave de acesso não vence mais
  const exp = (streak && streak.expires_at) || (S.me && S.me.expires_at) || S.keyExpires;  // eslint-disable-line no-unreachable
  if (!exp) return "";
  const ms = new Date(exp) - Date.now();
  if (ms > EXPIRY_WARN_DAYS * 86400000) return "";
  const days = Math.floor(ms / 86400000);
  const whenTxt = days <= 0 ? "em menos de 24 horas" : days === 1 ? "em 1 dia" : `em ${days} dias`;
  return `<div class="banner bad"><b>⏰ Seu código de acesso vence ${whenTxt}</b> (${esc(new Date(exp).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }))}).
    <div class="hint">Renove grátis por mais 7 dias no menu ☰ → <b>🔑 Renove 7 dias grátis da sua chave</b>. Depois que vence, o código e os aparelhos liberados são apagados
      (suas hunts e sessões continuam salvas). Enviar uma hunt por dia também ajuda: a cada 30 dias seguidos o código ganha +7 dias.</div></div>`;
}
/** 0.22.2: destaque do Início — a notícia mais nova do Tibia, no idioma escolhido. */
function headlineCard(n) {
  if (!n) return "";
  return `<article class="card news-new home-news">
    <div class="row" style="align-items:flex-start"><span class="muted" style="font-size:13px">📰 Novidades do Tibia · ${esc(tnDate(n.date))}</span>${tnTags(n)}</div>
    <b data-i18n-skip style="display:block; font-size:18px; margin-top:4px">${esc(n.title)}</b>
    <div class="home-news-body">${tnBody(n)}</div>
    <div class="row" style="margin-top:6px"><button class="link" data-page-link="tnews">Ver todas as novidades →</button>${n.translated ? `<span class="hint" style="margin:0">🌐 tradução automática</span>` : ""}</div>
    <div class="hint" style="margin:4px 0 0">${TN_CREDIT}</div></article>`;
}
/* ---------- 0.29.0: 🎯 "Essa hunt serve?" (meta por hora) e 📝 recap da semana ---------- */
const GOAL = { mode: "solo", hist: [] };
function goalCard(mode, hist) {
  GOAL.mode = mode; GOAL.hist = hist;
  return `<h2>🎯 Essa hunt serve?</h2><div class="card">
    <label class="muted" for="goalIn">${mode === "party" ? "Quanto você quer ganhar por hora? (gp/h)" : "Quanto você quer ganhar por hora? (XP/h)"}</label>
    <input id="goalIn" data-goal-in inputmode="numeric" autocomplete="off" placeholder="${mode === "party" ? "1500000" : "800000"}" style="margin-top:6px">
    <div id="goalOut" class="hint" style="margin-top:8px">Digite a meta para ver quantas das suas hunts chegaram lá e quais lugares costumam render isso no seu level.</div></div>`;
}
let goalSeq = 0;
document.addEventListener("input", async (e) => {
  const inp = e.target.closest("[data-goal-in]");
  if (!inp) return;
  const out = $("#goalOut"), target = parseInt(inp.value.replace(/\D/g, ""), 10), seq = ++goalSeq;
  if (!(target > 0)) { out.textContent = I18N.t("Digite a meta para ver quantas das suas hunts chegaram lá e quais lugares costumam render isso no seu level."); return; }
  const party = GOAL.mode === "party", hist = GOAL.hist.filter((v) => v > 0);
  const hit = hist.filter((v) => v >= target).length;
  const lines = [hist.length ? tf("Você passou disso em {0} de {1} hunts.", hit, hist.length) : I18N.t("Ainda não há hunts suas para comparar.")];
  try {
    const lvl = (S.char && S.char.level) || 0;
    const qs = new URLSearchParams({ sort: party ? "gold" : "xp", mode: party ? "party" : "solo" });
    if (lvl) { qs.set("min_level", Math.max(1, lvl - 60)); qs.set("max_level", lvl + 60); }
    const r = await api("GET", "/api/places/ranking?" + qs);
    if (seq !== goalSeq) return;
    const key = party ? "gold_per_hour" : "xp_per_hour", unit = party ? "gp/h" : "XP/h";
    const ok = r.rows.filter((p) => p[key] >= target).sort((a, b) => a[key] - b[key]).slice(0, 3);
    if (ok.length) lines.push(I18N.t("Lugares do seu level que costumam render isso:"), ...ok.map((p) => `• ${p.name} · ${fmt(p[key])} ${unit}`));
    else if (r.rows.length) { const best = r.rows[0]; lines.push(tf("Nenhum lugar do seu level chega nisso ainda. O melhor é {0}, com {1}.", best.name, `${fmt(best[key])} ${unit}`)); }
  } catch (err) { if (err.status === 401) return; }
  if (seq === goalSeq) out.innerHTML = lines.map((l) => `<div data-i18n-skip>${esc(l)}</div>`).join("");
});
/** Texto da semana (últimos 7 dias) para colar no Discord/WhatsApp. */
function recapCard(mode, items) {
  const since = Date.now() - 7 * 86400000;
  const week = items.filter((x) => new Date(x.at).getTime() >= since);
  if (!week.length) return "";
  const secs = week.reduce((a, x) => a + x.secs, 0), sum = week.reduce((a, x) => a + x.value, 0);
  const best = week.reduce((a, x) => (x.perHour > a.perHour ? x : a), week[0]);
  const party = mode === "party", unit = party ? "gp" : "XP";
  const text = [tf("📅 Minha semana no Tibia · 4rt3mi5"),
    tf("🏹 {0} · {1} de hunt", party ? tf("{0} hunts em party", week.length) : tf("{0} sessões solo", week.length), dur(secs)),
    tf("💰 {0}: {1} ({2}/h)", party ? tf("Lucro") : tf("XP"), `${fmt(sum)} ${unit}`, `${fmt(secs ? Math.round(sum * 3600 / secs) : 0)} ${unit}`),
    tf("🥇 Melhor: {0} · {1}/h", best.label, `${fmt(best.perHour)} ${unit}`)].join("\n");
  return `<div class="card"><b>📝 Recap da semana</b>
    <div class="msgbox" data-i18n-skip style="white-space:pre-line">${esc(text)}</div>
    <div class="row" style="justify-content:flex-end"><button class="copy" data-copy="${esc(text)}">📋 Copiar para Discord/WhatsApp</button></div></div>`;
}
async function loadHome() {
  const el = $("#pageHome");
  el.innerHTML = skeleton("home");
  const mode = S.mode;
  const headline = api("GET", `/api/tibia/headline?lang=${encodeURIComponent(I18N.lang)}`).catch(() => null);
  if (mode !== "party") return loadHomeSolo(el, headline);
  let data;
  try { data = await api("GET", `/api/hunts/${encodeURIComponent(S.nick)}`); }
  catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  if (S.mode !== mode || S.page !== "home") return;
  const hunts = data.hunts;
  S.homeHunts = hunts;
  const total = hunts.reduce((a, h) => a + view(h, S.nick).profit, 0);  // considera as regras de divisão
  const secs = hunts.reduce((a, h) => a + h.duration_seconds, 0);
  let toPay = 0, toGet = 0, owe = 0, oweN = 0, due = 0, dueN = 0;
  hunts.forEach((h) => {
    const v = view(h, S.nick); toPay += v.totalPay; toGet += v.totalGet;
    if (v.pendingPay) { owe += v.pendingPay; oweN++; }
    if (v.pendingGet) { due += v.pendingGet; dueN++; }
  });
  setBadge("lootBadge", oweN + dueN);
  const pendingCard = owe || due ? `<div class="card"><b>💸 Acertos pendentes</b>
    ${owe ? `<div class="neg" style="margin-top:4px">Você ainda deve ${fmt(owe)} gp em ${oweN} ${oweN === 1 ? "lootsplit" : "lootsplits"}.</div>` : ""}
    ${due ? `<div class="pos" style="margin-top:4px">Falta receber ${fmt(due)} gp de ${dueN} ${dueN === 1 ? "lootsplit" : "lootsplits"}.</div>` : ""}
    <div class="hint">Depois de transferir no banco, toque em "✔ Já paguei" na hunt. Quem recebe também pode marcar "✔ Recebi".</div>
    <button class="btn2" style="margin-top:8px" data-page-link="loot" data-hl-go="pend">💸 Ir acertar agora</button></div>` : "";
  const [news, streak, notices, , ach, boosted] = await Promise.all([headline, api("GET", "/api/streak").catch(() => null), subsNotices(),
    refreshChangesFab().catch(() => {}), achievementsFor(S.nick), api("GET", "/api/tibia/boosted").catch(() => null)]);
  if (S.mode !== mode || S.page !== "home") return;
  const n = (v, suffix = "") => `<span data-count="${v}" data-suffix="${suffix}">${fmt(v)}${suffix}</span>`;
  el.innerHTML = `${expiryNotice(streak)}${notices}
    ${headlineCard(news)}
    ${pendingCard}
    ${dupNotice(hunts)}
    ${boostedCard(boosted)}
    ${achHomeCard(ach)}
    <h2>👥 Última hunt em party</h2>
    ${hunts.length ? huntCard(hunts[0], S.nick, "Última hunt") : emptyState("home")}
    ${streak ? streakTeaser(streak) : ""}
    ${hunts.length ? `<h2>Totais</h2>
    ${sparkline(hunts.map((h) => h.profit_each_per_hour).reverse(), "Gp/h por pessoa, da mais antiga para a mais recente")}
    ${statGrid([["Hunts", n(hunts.length)], ["Profit total", n(total, " gp"), total >= 0 ? "gold" : "neg"],
                ["Tempo de hunt", dur(secs)], ["Média por hora", n(secs ? Math.round(total * 3600 / secs) : 0, " gp")],
                ["Total transferido", n(toPay, " gp"), toPay ? "neg" : ""], ["Total recebido", n(toGet, " gp"), toGet ? "pos" : ""]])}
    ${recapCard("party", hunts.map((h) => ({ at: h.started_at, secs: h.duration_seconds, value: view(h, S.nick).profit, perHour: h.profit_each_per_hour,
      label: h.place ? h.place.name : new Date(h.started_at).toLocaleDateString("pt-BR") })))}
    ${goalCard("party", hunts.map((h) => h.profit_each_per_hour))}
    <h2>🏅 Ranking da PT</h2><div class="card" id="ptRank"></div>
    <h2>Hunts anteriores (${hunts.length - 1})</h2>
    ${hunts.length > 1 ? hunts.slice(1, 6).map((h) => historyItem(h, S.nick)).join("") : `<p class="muted">Nenhuma hunt anterior.</p>`}
    ${hunts.length > 6 ? `<button class="btn2" data-page-link="loot" style="width:100%; margin-top:4px">🔎 Ver e buscar todas as hunts</button>` : ""}` : ""}`;
  countUp(el);
  if (hunts.length) {
    renderPtRank();
    const names = [...new Set(hunts.flatMap((h) => h.players.map((p) => p.name)))];
    ensureVocations(names).then((changed) => { if (changed && S.page === "home") { renderPtRank(); paintVocations(el); } });
  }
  if (streak) celebrateRewards(streak.granted);
}
/** Início no modo Solo: notícia do Tibia e a última sessão do Hunt Session Stacker. */
async function loadHomeSolo(el, headline) {
  const [news, d, streak, notices, , ach, boosted] = await Promise.all([headline, api("GET", `/api/stacker/${encodeURIComponent(S.nick)}?period=7`).catch(() => null),
    api("GET", "/api/streak").catch(() => null), subsNotices(), refreshChangesFab().catch(() => {}), achievementsFor(S.nick),
    api("GET", "/api/tibia/boosted").catch(() => null)]);
  if (S.mode !== "solo" || S.page !== "home") return;
  if (d) S.prices = { ...S.prices, ...(d.prices || {}) };
  const last = d && d.sessions.length ? d.sessions[0] : null;
  el.innerHTML = `${expiryNotice(streak)}${notices}
    ${headlineCard(news)}
    ${boostedCard(boosted)}
    ${achHomeCard(ach)}
    <h2>🧍 Última hunt solo</h2>
    ${last ? soloItem(last).replace("<details class=\"card\">", "<details class=\"card\" open>") : emptyState("stack")}
    <button class="btn2" data-page-link="stack" style="width:100%; margin-top:4px">📈 Abrir o Hunt Session Stacker</button>
    ${d && d.sessions.length ? `<h2>Totais do dia ${d.day ? dayLabel(d.day) : ""}</h2>${sparkline(d.sessions.map((s) => s.xp || 0).reverse(), "XP de cada sessão, da mais antiga para a mais recente")}${soloStats(d.day_totals)}` : ""}
    ${d && d.sessions.length ? recapCard("solo", d.sessions.filter((s) => s.xp && s.duration_seconds).map((s) => ({ at: s.started_at, secs: s.duration_seconds, value: s.xp,
      perHour: Math.round(s.xp * 3600 / s.duration_seconds), label: new Date(s.started_at).toLocaleDateString("pt-BR") }))) : ""}
    ${goalCard("solo", d ? d.sessions.filter((s) => s.xp && s.duration_seconds).map((s) => Math.round(s.xp * 3600 / s.duration_seconds)) : [])}
    ${streak ? streakTeaser(streak) : ""}`;
  countUp(el);
  if (streak) celebrateRewards(streak.granted);
}

/* ---------- 📤 rascunhos sem internet: guarda o envio e manda sozinho quando a conexão voltar ---------- */
const DRAFT_LABEL = { "/api/lootsplit": "Lootsplit", "/api/stacker": "Sessão do Stacker",
                      "/api/bosses/session": "Sessão de boss", "/api/bosses/lootsplit": "Lootsplit de boss" };
async function loadDrafts() { try { return JSON.parse((await kv.get("drafts")) || "[]"); } catch { return []; } }
async function saveDrafts(list) { await kv.set("drafts", list.length ? JSON.stringify(list) : null); }
/** Envio que falhou por falta de conexão: guarda (sem repetir) e avisa. */
async function queueDraft(path, body, errEl) {
  const list = await loadDrafts();
  if (!list.some((d) => d.path === path && d.body.raw_text === body.raw_text)) list.push({ path, body, saved_at: new Date().toISOString() });
  await saveDrafts(list.slice(-20));
  if (errEl) errEl.innerHTML = `<span style="color:var(--gold)">📤 Sem conexão: guardei o texto como rascunho e envio sozinho quando a internet voltar.</span>`;
}
let flushingDrafts = false;
async function flushDrafts() {
  if (flushingDrafts || !S.key || !S.token || S.offline) return;
  flushingDrafts = true;
  const done = [];
  try {
    let list = await loadDrafts();
    while (list.length) {
      const d = list[0];
      try { const r = await api("POST", d.path, d.body); done.push({ d, ok: true, created: r.created }); }
      catch (err) {
        if (err.status === 0 || err.status === 401 || err.status === 429) break;  // tenta de novo depois
        done.push({ d, ok: false, msg: err.message });                            // erro do texto: não adianta repetir
      }
      list.shift();
      await saveDrafts(list);
    }
  } finally { flushingDrafts = false; }
  if (!done.length) return;
  const sheet = $("#sheet");
  sheet.innerHTML = `<b>📤 Rascunhos enviados</b>
    ${done.map((x) => `<div class="muted" style="font-size:14px; margin-top:4px">${x.ok ? "✔" : "✖"} ${esc(DRAFT_LABEL[x.d.path] || "Envio")}
      de ${esc(new Date(x.d.saved_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }))}
      (${esc(x.d.body.nickname || "")})${x.ok ? (x.created ? "" : " · já estava salvo") : ": " + esc(x.msg)}</div>`).join("")}
    <div class="actions"><button class="btn2" data-paste-cancel>Ok</button></div>`;
  sheet.classList.remove("hidden");
  if (S.page === "home") loadHome(); else if (S.page === "stack") loadStack(); else if (S.page === "boss") loadBoss({ quiet: true });
}
window.addEventListener("online", () => setTimeout(flushDrafts, 2000));

/* ---------- lootsplit ---------- */
// 0.22.0: primeiro o que importa (quem paga quem, pronto para copiar), depois o texto para quem não tem o app,
// e só então o próximo passo de acordo com o tipo de player.
function quickTransfers(h) {
  if (!h.transfers.length) return `<div class="card quick"><b>💸 Transferências</b><p class="muted" style="margin:4px 0 0">Ninguém precisa transferir: todos ficaram com ${fmt(h.profit_each)} gp.</p>
    <div class="row" style="margin-top:8px">${shareMenuButton(h)}</div></div>`;
  const all = h.transfers.map((t) => `${t.payer}: ${t.command}`).join("\n");
  return `<div class="card quick"><div class="row"><b>💸 Quem transfere para quem</b><button class="copy" data-copy="${esc(all)}">Copiar todas</button></div>
    ${h.transfers.map((t) => `<div class="tx"><div class="row"><span><b class="${isMine(t.payer) ? "gold" : ""}">${vdot(t.payer)}${esc(t.payer)}</b> → <b class="${isMine(t.receiver) ? "gold" : ""}">${esc(t.receiver)}</b></span><b class="gold">${fmt(t.amount)} gp</b></div>
      <div class="row"><code>${esc(t.command)}</code><button class="copy" data-copy="${esc(t.command)}">Copiar</button></div></div>`).join("")}
    <div class="hint">Cada um que paga digita o comando no banco do Tibia (NPC banker). Cada um fica com ${fmt(h.profit_each)} gp.</div>
    <div class="row" style="margin-top:8px">${shareMenuButton(h)}</div></div>`;
}
/** Resumo do lootsplit para colar no Discord ou no WhatsApp (texto simples, sem depender do app). */
function splitSummary(h) {
  const lines = [`🏹 Lootsplit${h.place ? " · " + h.place.name : ""}`,
    `⏱️ ${dur(h.duration_seconds)} · ${h.players_count} jogadores`,
    `💰 Cada um: ${fmt(h.profit_each)} gp (${fmt(h.profit_each_per_hour)} gp/h)`, ""];
  if (h.transfers.length) lines.push("💸 Quem transfere para quem:", ...h.transfers.map((t) => `• ${t.payer} → ${t.receiver}: ${fmt(t.amount)} gp`));
  else lines.push("✅ Ninguém precisa transferir.");
  return lines.join("\n");
}
/** Texto pronto para mandar no chat do jogo para quem paga e não tem o app. */
function payerMessage(h, name) {
  // 0.23.0: a mensagem vai copiada para o chat do Tibia: já sai no idioma escolhido (frase inteira, valores no lugar)
  // 0.29.0: o nome da pessoa também aparece na frase ("Hilay precisa transferir…"), e quem só recebe tem a sua versão
  const sep = I18N.lang === "pt-BR" ? " e " : "; ";
  const pays = h.transfers.filter((t) => t.payer === name), gets = h.transfers.filter((t) => t.receiver === name);
  const payTxt = pays.map((t) => tf("{0} gp para {1} ({2})", fmt(t.amount), t.receiver, t.command)).join(sep);
  const getTxt = gets.map((t) => tf("{0} gp de {1}", fmt(t.amount), t.payer)).join(sep);
  if (pays.length) {
    const base = tf("{0}, lootsplit da hunt: cada um ficou com {1} gp. {0} precisa transferir {2}.", name, fmt(h.profit_each), payTxt);
    return gets.length ? base + " " + tf("{0} também vai receber {1}.", name, getTxt) : base;
  }
  return tf("{0}, lootsplit da hunt: cada um ficou com {1} gp. {0} vai receber {2}.", name, fmt(h.profit_each), getTxt);
}
/** Frase com valores no idioma escolhido: traduz o modelo ("… {0} …") e depois põe os valores. */
function tf(template, ...vals) {
  return I18N.t(template).replace(/\{(\d+)\}/g, (m, i) => (vals[+i] === undefined ? m : String(vals[+i])));
}
function partyMessages(h) {
  // 0.29.0: quem paga e também quem só recebe (cada um com a sua mensagem)
  const payers = [...new Set(h.transfers.flatMap((t) => [t.payer, t.receiver]))].filter((p) => !isMine(p));
  if (!payers.length) return "";
  const all = payers.map((p) => payerMessage(h, p)).join("\n");
  return `<div class="card"><div class="row"><b>💬 Mensagem para quem não tem o app</b>${payers.length > 1 ? `<button class="copy" data-copy="${esc(all)}">Copiar todas</button>` : ""}</div>
    <p class="muted" style="margin:2px 0 0; font-size:14px">Copie e mande no chat do Tibia para a pessoa saber quanto pagar ou receber.</p>
    ${payers.map((p) => { const m = payerMessage(h, p); return `<div class="msgbox">${esc(m)}</div>
      <div class="row" style="justify-content:flex-end"><button class="copy" data-copy="${esc(m)}">Copiar mensagem para ${esc(p)}</button></div>`; }).join("")}</div>`;
}
/** Depois do essencial: o que completar, conforme o tipo de player. Tudo opcional e salvo como estiver. */
function lootNextStep(h) {
  if (!h.id || !h.in_party) return "";
  const t = ptype();
  if (t === "novato") return `<div class="card"><b>🌱 Pronto!</b><p class="muted" style="margin:4px 0 0">O lootsplit da sua PT ficou salvo.
    Pode fechar e seguir a vida: ele fica no 🏠 Início e em 🗺️ Hunts (Party) quando quiser ver de novo.</p></div>`;
  const own = (list) => (list || []).some((x) => x.name.toLowerCase() === (S.nick || "").toLowerCase());
  const has = { place: !!h.place, session: own(h.member_sessions), input: own(h.inputs) };
  const order = ["place", "session", ...(isHardcore(t) ? ["input"] : [])];
  const label = { place: "📍 Inserir a hunt", session: "📈 Hunt Analyser", input: "🛡️ Input Analyser" };
  const done = { place: h.place ? `📍 ${esc(h.place.name)}` : "", session: "📈 Hunt Analyser ✔", input: "🛡️ Input Analyser ✔" };
  const canPlace = h.can_delete;  // só quem enviou o lootsplit escolhe o local
  const pending = order.filter((s) => !has[s] && (s !== "place" || canPlace));
  const next = pending[0];
  const btn = (s) => {
    if (has[s]) return `<span class="tagbtn" style="justify-content:center">${done[s]}</span>`;
    if (s === "place" && !canPlace) return `<span class="muted" style="font-size:13px">📍 Quem enviou o lootsplit escolhe a hunt.</span>`;
    const gold = isHardcore(t) && s === next ? " goldpulse" : "";
    return `<button class="btn2${gold}" data-loot-step="${s}" data-hunt="${h.id}" type="button">${label[s]}</button>`;
  };
  const intro = isHardcore(t)
    ? (next ? "🔥 Complete a sua hunt: siga o botão dourado. Primeiro a hunt, depois o Hunt Analyser e por fim o Input Analyser." : "🔥 Tudo preenchido ✔")
    : (pending.length ? "⚔️ Quer completar? Diga em qual hunt foi e junte o seu Hunt Analyser." : "⚔️ Tudo preenchido ✔");
  return `<div class="card"><b>${intro}</b><div class="nextstep">${order.map(btn).join("")}</div>
    ${pending.length ? `<div class="hint">Não precisa ser agora: o que você não preencher fica salvo e dá para completar depois.</div>` : ""}</div>`;
}
function renderLoot(h) {
  S.lastLoot = h.id;
  const el = $("#lootResult");
  el.innerHTML = `${S.lootBanner ? `<div class="banner ok"><div>${esc(S.lootBanner)}</div>${S.lootNote ? `<div class="hint">🔁 ${esc(S.lootNote)}</div>` : ""}</div>` : ""}
    ${quickTransfers(h)}${partyMessages(h)}${lootNextStep(h)}
    <h2>Detalhes</h2>${huntCard(h, S.nick, "Resultado")}`;
  countUp(el);
  paintVocations(el);
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-loot-step]");
  if (!b) return;
  e.preventDefault();
  // Hardcore: o botão dourado conduz pela sequência inteira (hunt → sessão → input); Comum: só aquele passo.
  const id = +b.dataset.hunt, first = b.dataset.lootStep;
  const btns = [...document.querySelectorAll(`[data-loot-step][data-hunt="${id}"]`)].map((x) => x.dataset.lootStep);
  const steps = isHardcore() ? btns.slice(btns.indexOf(first)) : [first];
  startFlow("hunt", id, { chain: steps, after: () => refreshAfterFlow("hunt") });
});
$("#lootBtn").addEventListener("click", async () => {
  const raw = $("#lootText").value.trim();
  if (!raw) return;
  const btn = $("#lootBtn"); btn.disabled = true; $("#lootErr").textContent = ""; $("#lootResult").innerHTML = "";
  try {
    const r = await api("POST", "/api/lootsplit", { raw_text: raw, nickname: S.nick });
    S.lootBanner = r.for_owner ? `Salvo para ${r.saved_as} (o dono do personagem), marcado como jogado por você ✔`
      : r.created ? "Lootsplit salvo ✔ Todos da PT já podem ver no app." : "Esse lootsplit já estava salvo ✔";
    S.lootNote = "";
    // 0.31.0: a sessão já tinha sido enviada por outro membro: não duplica, e quem enviou depois só completa o que é seu
    if (r.same && !r.created && !isMine(r.same.by)) {
      S.lootBanner = r.same.kind === "updated"
        ? tf("Essa sessão já tinha sido enviada por {0}. Atualizei com a sua versão, que estava mais completa ✔", r.same.by)
        : tf("Essa sessão já tinha sido enviada por {0}. Você já está nela ✔ Falta só o seu Hunt Analyser e o seu Input Analyser, logo abaixo.", r.same.by);
    }
    if (r.switched_from) {  // 0.23.0: salvo no personagem seu que estava na PT
      await switchActiveChar(r.saved_as);
      S.lootNote = `Salvo em ${r.saved_as}, que estava na PT (você estava em ${r.switched_from}).`;
    }
    renderLoot(r.hunt);
    $("#lootResult").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });  // direto para quem paga quem
    ensureVocations(r.hunt.players.map((p) => p.name)).then((c) => c && paintVocations($("#lootResult")));
    $("#lootText").value = "";
    celebrateRewards(r.rewards);
    if (r.created) checkAchievements();
    loadLootList();
    // 0.20.0: no lootsplit o que importa primeiro é quem paga quem. Nada de perguntas aqui: o local da hunt,
    // a sessão e o Input Analyser ficam como opções no próprio card, para preencher depois.
    S.lastLoot = r.hunt.id;
  } catch (err) {
    if (err.status === 0) {
      await queueDraft("/api/lootsplit", { raw_text: raw, nickname: S.nick }, $("#lootErr"));
      $("#lootText").value = "";
    } else if (err.status === 403) {
      // mostra o cálculo mesmo assim, mas sem salvar
      const preview = await api("POST", "/api/lootsplit/preview", { raw_text: raw, nickname: S.nick }).catch(() => null);
      $("#lootResult").innerHTML = `<div class="banner bad"><b>${esc(err.message)}</b><div class="hint">${esc(err.hint || "")}</div>
        <div class="hint">Cálculo abaixo apenas para conferência (não foi salvo).</div></div>` + (preview ? huntCard(preview, S.nick, "Prévia") : "");
    } else if (err.status !== 401) {
      $("#lootErr").textContent = err.message;
    }
  } finally { btn.disabled = false; }
});

/* ---------- 📚 Minhas hunts em party: busca, filtros, meses e "mostrar mais" (0.31.0) ---------- */
const HL = { all: [], filter: "all", q: "", shown: 12 };
const HL_STEP = 12;
const HL_FILTERS = [["all", "Todas"], ["pend", "⏳ A acertar"], ["noplace", "📍 Sem local"], ["dups", "👯 Duplicadas"]];
function dupPairs(hunts) { return hunts.filter((h) => (h.similar || []).some((s) => s.id > h.id)).length; }
/** Aviso no Início e na lista quando existem lootsplits que parecem ser a mesma sessão. */
function dupNotice(hunts) {
  const byId = new Map(hunts.map((h) => [h.id, h]));
  const pairs = [];
  hunts.forEach((h) => (h.similar || []).forEach((s) => { if (s.id > h.id && byId.has(s.id)) pairs.push([h, byId.get(s.id)]); }));
  if (!pairs.length) return "";
  const n = pairs.length;
  const line = (h) => `<div class="row" style="font-size:14px"><span data-i18n-skip>${esc(when(h.started_at))} · ${dur(h.duration_seconds)} · ${kk(h.balance)} gp</span>
    <span class="muted" data-i18n-skip>${esc(h.submitted_by || "")}</span></div>`;
  // 0.31.1: o "Unir as duas" fica no próprio aviso, sem precisar abrir nenhuma hunt
  return `<div class="banner bad"><b>${tf(n === 1 ? "👯 {0} possível duplicata entre as suas hunts." : "👯 {0} possíveis duplicatas entre as suas hunts.", n)}</b>
    <div class="hint">A mesma sessão da PT foi enviada por mais de uma pessoa. Una as duas para ficar só a mais completa.</div>
    ${pairs.map(([a, b]) => `<div class="card" style="margin:8px 0 0">${line(a)}${line(b)}
      <div class="row" style="justify-content:flex-start; margin-top:8px"><button class="btn2" data-merge="${a.id}:${b.id}">Unir as duas</button></div></div>`).join("")}</div>`;
}
function hlHaystack(h) {
  const d = new Date(h.started_at);
  return plain([when(h.started_at), d.toLocaleDateString("pt-BR"), d.toLocaleDateString("pt-BR", { weekday: "long", month: "long" }),
    h.place ? h.place.name : "sem local", (h.players || []).map((p) => p.name).join(" "), h.submitted_by || ""].join(" "));
}
function hlMatch(h) {
  const v = view(h, S.nick);
  if (HL.filter === "pend" && !(v.pendingPay || v.pendingGet)) return false;
  if (HL.filter === "noplace" && h.place) return false;
  if (HL.filter === "dups" && !(h.similar || []).length) return false;
  const words = plain(HL.q).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = h._hay || (h._hay = hlHaystack(h));
  return words.every((w) => hay.includes(w));
}
function paintHuntList() {
  const rows = $("#hlRows"), chips = $("#hlChips");
  if (!rows) return;
  const count = (f) => { const keep = HL.filter; HL.filter = f; const n = HL.all.filter((h) => hlMatch(h)).length; HL.filter = keep; return n; };
  chips.innerHTML = HL_FILTERS.map(([k, t]) => {
    const n = count(k);
    return k !== "all" && !n && HL.filter !== k ? "" : `<button type="button" data-hl-filter="${k}" class="${HL.filter === k ? "on" : ""}">${t} <span class="muted">${n}</span></button>`;
  }).join("");
  const list = HL.all.filter(hlMatch);
  if (!list.length) {
    rows.innerHTML = `<p class="muted">${HL.q || HL.filter !== "all" ? "Nenhuma hunt com esse filtro. Limpe a busca ou escolha “Todas”." : "Nenhuma hunt ainda."}</p>`;
    return;
  }
  const shown = list.slice(0, HL.shown);
  let month = "", html = "";
  for (const h of shown) {
    let m = new Date(h.started_at).toLocaleDateString(I18N.locale, { month: "long", year: "numeric" });
    m = m.charAt(0).toUpperCase() + m.slice(1);
    if (m !== month) { month = m; html += `<div class="hl-month" data-i18n-skip>${esc(m)}</div>`; }
    html += historyItem(h, S.nick);
  }
  if (list.length > shown.length) html += `<button class="btn2" data-hl-more style="width:100%; margin-top:6px">${tf("Mostrar mais ({0})", list.length - shown.length)}</button>`;
  rows.innerHTML = html;
  paintVocations(rows);
  if (HL.openFirst) {  // vindo de um aviso: já abre a hunt para tratar e leva a tela até ela
    HL.openFirst = false;
    const first = rows.querySelector("details");
    if (first) { first.open = true; setTimeout(() => first.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" }), 150); }
  }
}
async function loadLootList() {
  const el = $("#huntList");
  if (!el || !S.nick) return;
  let d;
  try { d = await api("GET", `/api/hunts/${encodeURIComponent(S.nick)}`); }
  catch (err) { if (err.status !== 401) el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  HL.all = d.hunts;
  S.homeHunts = d.hunts;
  if (HL.filter === "dups" && !dupPairs(HL.all)) HL.filter = "all";  // acabaram as duplicadas: volta para a lista inteira
  if (!HL.all.length) { el.innerHTML = ""; return; }
  const typing = document.activeElement && document.activeElement.id === "huntSearch";
  if (!$("#huntSearch")) {
    el.innerHTML = `<h2>📚 Minhas hunts em party</h2>
      <div class="hl-tools"><input id="huntSearch" type="search" autocomplete="off" spellcheck="false" aria-label="Buscar hunts"
        placeholder="Buscar por data, local ou jogador" value="${esc(HL.q)}"><div class="hl-chips" id="hlChips"></div></div>
      <div id="hlRows"></div>`;
  }
  const top = el.querySelector("[data-hl-top]");
  if (top) top.remove();
  if (dupPairs(HL.all)) el.querySelector("h2").insertAdjacentHTML("afterend", `<div data-hl-top>${dupNotice(HL.all)}</div>`);
  paintHuntList();
  if (typing) $("#huntSearch").focus();
}
document.addEventListener("input", (e) => {
  if (e.target.id !== "huntSearch") return;
  HL.q = e.target.value; HL.shown = HL_STEP; paintHuntList();
});
document.addEventListener("click", async (e) => {
  const f = e.target.closest("[data-hl-filter]");
  if (f) { HL.filter = f.dataset.hlFilter; HL.shown = HL_STEP; return paintHuntList(); }
  if (e.target.closest("[data-hl-more]")) { HL.shown += HL_STEP; return paintHuntList(); }
  const go = e.target.closest("[data-hl-go]");
  if (go) { HL.filter = go.dataset.hlGo; HL.shown = HL_STEP; HL.q = ""; HL.openFirst = true; return; }  // a navegação (data-page-link) abre a lista já filtrada, com a primeira hunt aberta
  const m = e.target.closest("[data-merge]");
  if (!m) return;
  e.preventDefault();
  if (!confirm(tf("Unir as duas? Fica só a mais completa e nada do que já foi salvo se perde."))) return;
  const [a, b] = m.dataset.merge.split(":");
  m.disabled = true;
  try {
    await api("POST", `/api/hunt/${a}/merge`, { other_id: +b });
    if (S.page === "loot") { $("#lootResult").innerHTML = `<div class="banner ok">Hunts unidas ✔ Ficou só a mais completa.</div>`; loadLootList(); }
    else loadHome();
  } catch (err) { if (err.status !== 401) alert(err.message); m.disabled = false; }
});

/* ---------- hunt session stacker ---------- */
function soloStats(t) {
  return statGrid([
    ["XP", fmt(t.xp), "gold"], ["XP/h", fmt(t.xp_per_hour), "gold"],
    ["Raw XP", fmt(t.raw_xp)], ["Raw XP/h", fmt(t.raw_xp_per_hour)],
    ["Balance", fmt(t.balance) + " gp", t.balance >= 0 ? "pos" : "neg"], ["Balance/h", fmt(t.balance_per_hour) + " gp"],
    ["Supplies", fmt(t.supplies) + " gp"], ["Tempo", dur(t.duration_seconds)],
    ["Damage", fmt(t.damage)], ["Damage/h", fmt(t.damage_per_hour)],
    ["Healing", fmt(t.healing)], ["Healing/h", fmt(t.healing_per_hour)],
    ["Sessões", fmt(t.sessions)],
  ]);
}
function soloItem(s) {
  const owner = s.net_profit !== undefined;  // 0.20.0: quem não é o dono recebe só o geral
  return `<details class="card"><summary>
      <div class="row"><b>${when(s.started_at)}</b><span class="gold">${kk(s.xp)} XP</span></div>
      <div class="row muted"><span>${dur(s.duration_seconds)}${s.loot_value ? " · loot ≈ " + kk(s.loot_value) : ""}</span>
        <span class="${s.balance >= 0 ? "pos" : "neg"}">balance ${kk(s.balance)}</span></div>
      ${owner ? `<div class="muted" style="font-size:13px">lucro líquido real <b class="${s.net_profit >= 0 ? "pos" : "neg"}">${kk(s.net_profit)}</b></div>` : ""}
      ${s.other_player ? `<div><span class="who other" style="margin-left:0">${s.played_by ? esc(`🤝 Jogada por ${s.played_by}`) : "🤝 Jogada por outra pessoa"}</span></div>` : ""}
    </summary>
    <div class="tagline-row" style="font-size:14px">${placeTag("solo", s)} ${s.can_delete ? inputTag("solo", s) : ""}</div>
    ${inputBlock(s.input)}
    <div style="margin-top:10px">${statGrid([
      ["XP", fmt(s.xp)], ["Raw XP", fmt(s.raw_xp)], ["Balance", fmt(s.balance) + " gp"], ["Supplies", fmt(s.supplies) + " gp"],
      ["Damage", fmt(s.damage)], ["Damage/h", fmt(s.damage_h)], ["Healing", fmt(s.healing)], ["Healing/h", fmt(s.healing_h)],
    ])}</div>
    ${s.loot && s.loot.length ? `<h2>Itens coletados</h2>${itemList(s.loot, 999)}` : ""}
    ${s.kills && s.kills.length ? `<h2>Criaturas mortas</h2>${killChips(s.kills)}` : ""}
    ${owner ? `<div style="margin-top:10px">${shareButton("solo", s)}</div>` : ""}
    ${owner ? playerMarkBox("stacker", s) : ""}
    ${s.can_delete ? `<div style="margin-top:10px"><button class="danger-link" data-del-solo="${s.id}">🗑 Apagar esta sessão</button></div>` : ""}</details>`;
}
/** 0.23.0: o dono marca que outra pessoa jogou a sessão (sai dos rankings, recordes e comparações). */
function playerMarkBox(kind, s) {
  const base = kind === "boss" ? "bosses" : "stacker";
  return `<div class="tagline-row" style="margin-top:10px" data-mark="${base}:${s.id}">
    <label class="check-row"><input type="checkbox" data-mark-other${s.other_player ? " checked" : ""}> 🤝 Não fui eu que joguei</label>
    <input type="text" data-mark-by maxlength="40" placeholder="Quem jogou (opcional)" value="${esc(s.played_by || "")}"
      class="${s.other_player ? "" : "hidden"}" style="width:auto; padding:6px 8px" autocomplete="off" aria-label="Quem jogou (opcional)">
    <button class="btn2 ${s.other_player ? "" : "hidden"}" data-mark-save type="button">Salvar</button></div>`;
}
document.addEventListener("change", async (e) => {
  const cb = e.target.closest("[data-mark-other]");
  if (!cb) return;
  const box = cb.closest("[data-mark]");
  box.querySelector("[data-mark-by]").classList.toggle("hidden", !cb.checked);
  box.querySelector("[data-mark-save]").classList.toggle("hidden", !cb.checked);
  if (!cb.checked) markSession(box);  // desmarcar salva na hora
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-mark-save]");
  if (b) markSession(b.closest("[data-mark]"));
});
async function markSession(box) {
  const [base, id] = box.dataset.mark.split(":");
  const other = box.querySelector("[data-mark-other]").checked, by = box.querySelector("[data-mark-by]").value.trim();
  try {
    await api("POST", `/api/${base}/session/${id}/player`, other ? { other, ...(by ? { played_by: by } : {}) } : { other });
    if (base === "bosses") loadBoss({ quiet: true }); else if (S.page === "home") loadHome(); else loadStack({ quiet: true });
  } catch (err) { if (err.status !== 401) alert(err.message); }
}

/* ---------- loot: itens, preços, NPCs e minimapa ---------- */
const PERIODS = [[7, "Semana"], [15, "15 dias"], [30, "Mês"], [90, "3 meses"], [180, "6 meses"], [365, "1 ano"]];
// Imagens da TibiaWiki: no site saem do banco do servidor (/img/wiki, a wiki só é consultada na 1ª vez).
// No app desktop a página roda em 127.0.0.1 e o CSP não libera o servidor para imagens: busca direto na wiki.
const WIKI_FILE = (name) => {
  const file = encodeURIComponent(String(name).replace(/ /g, "_")) + ".gif";
  return S.api ? "https://www.tibiawiki.com.br/wiki/Especial:Redirecionar/file/" + file : "/img/wiki/" + file;
};
const MAP_TILE = (x, y, z) => `https://tibiamaps.github.io/tibia-map-data/mapper/Minimap_Color_${x}_${y}_${z}.png`;
// 0.21.0: crédito no lugar onde o conteúdo de outro site aparece
const WIKI_CREDIT = `<div class="credit">📚 Imagens e dados de itens, criaturas e NPCs: <a href="https://www.tibiawiki.com.br/" target="_blank" rel="noopener">TibiaWiki BR</a></div>`;
S.prices = {}; S.period = 7;

function itemImg(name, size = 28) {
  return `<img src="${WIKI_FILE(name)}" alt="" width="${size}" height="${size}" loading="lazy" style="image-rendering:pixelated; flex:none" data-err="hide">`;
}
function itemRow(it) {
  const p = S.prices[it.key] || { name: it.key, unit_price: 0 };
  const priceTxt = p.unit_price
    ? `<span class="muted">${fmt(p.unit_price)} gp${p.source === "media" ? " (média)" : ""}</span>`
    : `<span class="muted">sem preço</span>`;
  return `<div class="item-row" data-item="${esc(it.key)}" tabindex="0">
      ${itemImg(p.name)}
      <span class="item-name"><b>${fmt(it.count)}x</b> ${esc(p.name)}<br>${priceTxt}</span>
      <span class="item-val">${it.value ? kk(it.value) + " gp" : "—"}</span>
    </div>`;
}
function itemList(items, limit = 8) {
  const head = items.slice(0, limit).map(itemRow).join("");
  const rest = items.slice(limit);
  return `<div class="items">${head}${rest.length ? `<details><summary class="link">Ver todos os itens (${items.length})</summary>${rest.map(itemRow).join("")}</details>` : ""}</div>`;
}
function killChips(kills) {
  return `<div class="chips">${kills.map((k) => `<span class="chip" style="display:inline-flex; align-items:center; gap:6px">${creatureImg(k.key)}${fmt(k.count)}x ${esc(k.key)}</span>`).join("")}</div>`;
}
/** Imagem da criatura na TibiaWiki BR ("dragon lord" -> Dragon_Lord.gif). Some se não existir. */
function creatureImg(name, size = 24) {
  const small = new Set(["of", "the", "de", "da", "do"]);
  const title = String(name).split(" ").map((w, i) => (i && small.has(w.toLowerCase()) ? w.toLowerCase() : w.charAt(0).toUpperCase() + w.slice(1))).join(" ");  // 0.29.0: "Unaz The Mean" -> Unaz_the_Mean.gif
  return `<img src="${WIKI_FILE(title)}" alt="" width="${size}" height="${size}" loading="lazy" style="image-rendering:pixelated; flex:none; object-fit:contain" data-err="remove">`;
}
function itemsChart(items) {
  const top = items.filter((i) => i.value > 0).slice(0, 10);
  if (!top.length) return `<p class="muted">Sem itens com preço neste período.</p>`;
  const max = Math.max(...top.map((i) => i.value));
  return `<div class="bars">${top.map((i) => {
    const name = (S.prices[i.key] || {}).name || i.key;
    return `<span class="nm" title="${esc(name)}">${esc(name)}</span>
      <div class="track" title="${esc(name)}: ${fmt(i.value)} gp"><div class="fill" style="width:${(i.value / max) * 100}%"></div></div>
      <span class="val"><b>${kk(i.value)}</b></span>`;
  }).join("")}</div><div class="chart-note">Valor de cada item no período (quantidade × preço). Top 10.</div>`;
}
function periodBlock(p) {
  const label = PERIODS.find(([d]) => d === p.days)[1].toLowerCase();
  return `<div class="seg" role="tablist">${PERIODS.map(([d, t]) =>
      `<button data-period="${d}" class="${d === p.days ? "on" : ""}" role="tab" aria-selected="${d === p.days}">${t}</button>`).join("")}</div>
    <div class="card">
      <div class="muted">Loot estimado (${label}) · ${fmt(p.totals.sessions)} sessões · ${dur(p.totals.duration_seconds)}</div>
      <div class="big gold" data-count="${p.loot_value}" data-suffix=" gp">${fmt(p.loot_value)} gp</div>
      <div class="muted">${p.totals.duration_seconds ? fmt(Math.round(p.loot_value * 3600 / p.totals.duration_seconds)) + " gp/h de loot · " : ""}XP ${fmt(p.totals.xp)} · balance ${fmt(p.totals.balance)} gp</div>
      <div style="margin-top:8px">Lucro líquido real: <b class="${p.net_profit >= 0 ? "pos" : "neg"}">${fmt(p.net_profit)} gp</b>
        <span class="muted">(${fmt(p.net_profit_per_hour)} gp/h)</span>
        <div class="hint">Loot avaliado pelos preços de NPC (ou média dos usuários) menos os supplies gastos.</div></div>
      ${p.unpriced ? `<div class="hint" style="margin-top:6px">${p.unpriced} ${p.unpriced === 1 ? "item não tem" : "itens não têm"} NPC comprador. Toque no item para informar um preço.</div>` : ""}
      ${p.items.length ? `<h2>Itens</h2>${itemSortSeg()}<div id="itemsBox">${itemList(sortItems(p.items))}</div>
        <button class="link" data-loot-chart style="margin-top:8px">📊 Gráfico</button><div class="chart hidden" id="lootChart">${itemsChart(p.items)}</div>`
        : `<p class="muted">Nenhum item coletado neste período.</p>`}
      ${p.kills.length ? `<h2>Criaturas mortas</h2>${killChips(p.kills)}` : ""}
    </div>`;
}

async function loadStack(opts = {}) {
  const el = $("#stackResult");
  if (!opts.quiet) el.innerHTML = skeleton("stack");
  paintLive();
  let d;
  try { d = await api("GET", `/api/stacker/${encodeURIComponent(S.nick)}?period=${S.period}`); }
  catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  S.prices = d.prices || {};
  S.stack = d;
  paintLive();
  if (!d.sessions.length) {
    el.innerHTML = emptyState("stack");
    return d;
  }
  el.innerHTML = `
    ${alertsBlock(d)}
    ${goalsBlock(d)}
    ${weeklyBlock(d.sessions)}
    ${d.is_owner ? `<h2>Loot e criaturas</h2>${periodBlock(d.period)}`
      : `<div class="card muted">🔒 Loot e criaturas mortas de ${esc(S.nick)} ficam só com o dono do personagem.</div>`}
    ${byPlaceBlock(d.by_place)}
    ${forecastBlock(d.forecast)}
    <details class="card"><summary class="row"><b>🏆 Recordes pessoais</b><span class="muted">▾</span></summary>${recordsBlock(d.records)}</details>
    ${d.is_owner ? `<details class="card"><summary class="row"><b>🧺 Lista de venda</b><span class="muted">${d.sell.filter((i) => i.count).length} itens ▾</span></summary>${sellBlock(d)}</details>` : ""}
    <h2>Totais do dia ${d.day ? dayLabel(d.day) : ""}</h2>${soloStats(d.day_totals)}
    <details style="margin-top:12px"><summary class="link">Totais de toda a vida ▾</summary>${soloStats(d.lifetime)}</details>
    <h2>Sessões enviadas (${d.sessions.length})</h2>
    ${d.sessions.length ? d.sessions.map(soloItem).join("") : `<p class="muted">Nenhuma sessão enviada para ${esc(S.nick)} ainda.</p>`}`;
  countUp(el);
  return d;
}

/** 📊 Comparar as suas hunts (para todos os tipos de player): no mesmo tempo, onde rendeu mais XP e mais lucro. */
function byPlaceBlock(b) {
  if (!b || !b.rows.length) return "";
  const top = b.rows.length > 1
    ? `<p style="margin:6px 0; color:var(--gold2)">No mesmo tempo de hunt, você fez mais XP em ${esc(b.best_xp)} e mais lucro em ${esc(b.best_gold)}.</p>`
    : `<p class="muted" style="margin:6px 0">Diga o local de sessões em outras hunts para comparar uma com a outra.</p>`;
  return `<details class="card" open><summary class="row"><b>📊 Comparar minhas hunts</b><span class="muted">${b.rows.length} ${b.rows.length === 1 ? "hunt" : "hunts"} ▾</span></summary>
    ${top}
    <div class="table-wrap"><table><tr><th>Hunt</th><th>XP/h</th><th>Balance/h</th><th>Melhor XP/h</th><th>Sessões</th></tr>
      ${b.rows.map((r) => `<tr><td>${esc(r.place)}<div class="muted" style="font-size:12px">${String(r.hours).replace(".", ",")} h</div></td>
        <td class="${r.place === b.best_xp ? "gold" : ""}">${kk(r.xp_h)}</td>
        <td class="${r.place === b.best_gold ? "pos" : r.gold_h < 0 ? "neg" : ""}">${kk(r.gold_h)}</td>
        <td>${kk(r.best_xp_h)}</td><td>${r.sessions}</td></tr>`).join("")}</table></div>
    <div class="hint">Média por hora das suas sessões de 10 min ou mais em cada hunt. Melhor XP/h = a sua melhor sessão ali. Só para você se informar.</div></details>`;
}

/* ---------- 0.26.1: 🥇 Rankings — Usuários do 4rt3mi5 (XP 30/90), Geral (top 1000 por métrica) e ficha do jogador ---------- */
S.rtab = "artemis";
S.xp = { days: 30 };
S.geral = { metric: "level", page: 1 };
const GERAL_LABELS = { level: "Level", magiclevel: "Magic Level", shielding: "Shielding",
  distancefighting: "Distance Fighting", clubfighting: "Club Fighting", swordfighting: "Sword Fighting",
  axefighting: "Axe Fighting", fistfighting: "Fist Fighting", fishing: "Fishing", achievements: "Achievements",
  charmpoints: "Charm Points", goshnarstaint: "Goshnar's Taint", loyaltypoints: "Loyalty Points", dromescore: "Drome Score",
  bosspoints: "Boss Points", bountypoints: "Bounty Points", weeklytasks: "Weekly Tasks", phosphorusrecord: "Phosphorus Record" };
const brData = (iso) => (iso ? iso.split("-").reverse().join("/") : "");

function loadRankings() { showRankTab(S.rtab); }
function showRankTab(t) {
  S.rtab = t;
  document.querySelectorAll("[data-rtab]").forEach((b) => b.classList.toggle("on", b.dataset.rtab === t));
  $("#tabArtemis").classList.toggle("hidden", t !== "artemis");
  $("#tabGeral").classList.toggle("hidden", t !== "geral");
  $("#tabAmigos").classList.toggle("hidden", t !== "amigos");
  if (t === "artemis") loadXp(); else if (t === "geral") loadGeral(); else loadAmigos();
}

async function loadXp() {
  const body = $("#xpBody");
  document.querySelectorAll("[data-xdays]").forEach((b) => b.classList.toggle("on", +b.dataset.xdays === S.xp.days));
  body.innerHTML = skeleton("stack");
  let d;
  try { d = await api("GET", `/api/xp-ranking?days=${S.xp.days}&scope=board&world=${encodeURIComponent(S.rworld)}`); }
  catch (err) { if (err.status !== 401) body.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  $("#xpNoteDated").classList.toggle("hidden", !d.note_visible);
  paintWorldSelect($("#xpWorld"), d.worlds || []);
  if (!d.rows.length) { body.innerHTML = `<p class="muted">${d.world ? esc(tf("Nenhum personagem acompanhado em {0} ainda.", d.world)) : "Nenhum personagem acompanhado ainda."}</p>`; return; }
  const medal = ["🥇", "🥈", "🥉"], W = "white-space:normal";
  body.innerHTML = `<div class="table-wrap"><table style="table-layout:fixed;width:100%"><tr><th style="width:44px;${W}">#</th><th style="${W};text-align:left">Personagem</th><th style="text-align:right;width:112px;${W}">Ganho ${d.days} dias</th></tr>
    ${d.rows.map((r, i) => `<tr><td style="${W}">${r.gain == null ? "–" : (medal[i] || i + 1)}</td>
      <td style="${W};text-align:left"><a href="#" data-player="${esc(r.name)}" style="font-weight:600;color:inherit;text-decoration:underline dotted">${esc(r.name)}</a>${r.xp != null
        ? `<div class="muted" style="font-size:12px"><abbr title="XP medida pelo highscore do Tibia (top 1000), conferida todo dia">highscore</abbr>${r.partial ? ` · desde ${brData(r.since)}` : ""}</div>`
        : r.gain != null
          ? `<div class="muted" style="font-size:12px"><abbr title="Este personagem está fora do top 1000, então o ganho é a soma das sessões solo que ele enviou ao site">pelas sessões solo enviadas</abbr>${r.partial ? ` · desde ${brData(r.since)}` : ""}</div>`
          : `<div class="muted" style="font-size:12px">sem dados ainda (fora do top 1000 ou ainda não medido)</div>`}</td>
      <td style="text-align:right;${W}">${r.gain == null ? "–" : `<b>${fmt(r.gain)}</b> XP`}</td></tr>`).join("")}</table></div>
    <div class="hint">Ganho = XP de hoje menos o XP do início da contagem: 21/11/2026 ou o cadastro do personagem, o que for depois. Quando não há highscore do personagem (fora do top 1000), o ganho vem das sessões solo enviadas.</div>`;
}

/** 0.30.0: lista de mundos do filtro (o do seu personagem vem primeiro). */
// 0.30.1: o mesmo filtro de mundo nas três abas (Usuários do 4rt3mi5, Geral e Amigos); o padrão é "Todos os mundos"
S.rworld = "";
function paintWorldSelect(sel, worlds) {
  const mine = S.char && S.char.world;
  const key = worlds.join("|") + "|" + (mine || "");
  if (sel.dataset.key !== key) {
    const ordered = mine && worlds.includes(mine) ? [mine, ...worlds.filter((w) => w !== mine)] : worlds;
    sel.innerHTML = `<option value="">${esc(I18N.t("Todos os mundos"))}</option>` + ordered.map((w) =>
      `<option value="${esc(w)}" data-i18n-skip>${w === mine ? "📍 " : ""}${esc(w)}</option>`).join("");
    sel.dataset.key = key;
  }
  sel.value = worlds.includes(S.rworld) ? S.rworld : "";
}
const paintGeralWorlds = (worlds) => paintWorldSelect($("#geralWorld"), worlds);
for (const [id, reload] of [["#geralWorld", () => { S.geral.page = 1; loadGeral(); }], ["#xpWorld", () => loadXp()], ["#amigosWorld", () => loadAmigos()]]) {
  $(id).addEventListener("change", (e) => { S.rworld = e.target.value; reload(); });
}
async function loadGeral() {
  const sel = $("#geralMetric");
  if (!sel.options.length) sel.innerHTML = Object.entries(GERAL_LABELS).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  sel.value = S.geral.metric;
  const body = $("#geralBody");
  body.innerHTML = skeleton("stack");
  let d;
  try { d = await api("GET", `/api/rank/geral?metric=${S.geral.metric}&page=${S.geral.page}&world=${encodeURIComponent(S.rworld)}`); }
  catch (err) { if (err.status !== 401) body.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  paintGeralWorlds(d.worlds || []);
  $("#geralDay").textContent = d.day ? `Varredura de ${brData(d.day)} · 100 por página` : "Ainda não há varredura.";
  $("#geralNote").textContent = !d.world ? "" : d.source === "mundo"
    ? tf("Top {0} de {1}.", d.total, d.world)
    : tf("Mostrando só os de {0} que estão no top 1000 geral ({1}). O top completo do mundo chega na próxima varredura.", d.world, d.total);
  $("#geralPage").textContent = `Página ${d.page} de ${d.pages}`;
  $("#geralPrev").disabled = d.page <= 1;
  $("#geralNext").disabled = d.page >= d.pages;
  if (!d.rows.length) { body.innerHTML = `<p class="muted">Sem dados ainda. O ranking aparece depois da primeira varredura (09h).</p>`; return; }
  const W = "white-space:normal";
  body.innerHTML = `<div class="table-wrap"><table style="table-layout:fixed;width:100%"><tr><th style="width:52px;${W}">#</th><th style="${W};text-align:left">Personagem</th><th style="text-align:right;width:120px;${W}">${esc(GERAL_LABELS[S.geral.metric])}</th></tr>
    ${d.rows.map((r) => `<tr><td style="${W}">${r.pos}</td>
      <td style="${W};text-align:left"><a href="#" data-player="${esc(r.name)}" style="font-weight:600;color:inherit;text-decoration:underline dotted">${esc(r.name)}</a>
        <div class="muted" style="font-size:12px">${esc(r.world || "")}${r.vocation ? " · " + esc(r.vocation) : ""}${r.level ? " · level " + r.level : ""}</div></td>
      <td style="text-align:right;${W}">${fmt(r.value)}</td></tr>`).join("")}</table></div>`;
}

async function openPlayer(name) {
  $("#playerModal").classList.remove("hidden");
  $("#pmTitle").textContent = name;
  $("#pmBody").innerHTML = skeleton("stack");
  let d;
  try { d = await api("GET", `/api/rank/player/${encodeURIComponent(name)}`); }
  catch (err) { $("#pmBody").innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  const c = d.calc;
  $("#pmBody").innerHTML = `
    <div class="row" style="flex-wrap:wrap;gap:14px">
      <div><div class="muted">Vocação</div><b>${esc(d.vocation || "–")}</b></div>
      <div><div class="muted">Level</div><b>${d.level ?? "–"}</b></div>
      <div><div class="muted">Mundo</div><b>${esc(d.world || "–")}</b></div>
      ${c ? `<div><div class="muted">HP</div><b>${fmt(c.hp)}</b></div><div><div class="muted">Mana</div><b>${fmt(c.mana)}</b></div><div><div class="muted">Cap</div><b>${fmt(c.cap)} oz</b></div>` : ""}
    </div>
    ${c ? `<div class="hint">HP, mana e cap calculados pela regra do jogo a partir do level e da vocação.</div>` : ""}
    <div class="row" style="gap:14px;margin-top:12px;flex-wrap:wrap">
      <div><div class="muted">XP ganha 30 dias</div><b>${d.xp.d30.gain == null ? "–" : fmt(d.xp.d30.gain)}</b></div>
      <div><div class="muted">XP ganha 90 dias</div><b>${d.xp.d90.gain == null ? "–" : fmt(d.xp.d90.gain)}</b></div>
    </div>
    <div class="seg" style="margin-top:14px">
      <button data-pmc="daily" class="on">Diária</button><button data-pmc="monthly">Mensal</button><button data-pmc="quarterly">Trimestral</button>
    </div>
    <div id="pmSvg" style="margin-top:8px"></div>
    <h3 style="margin-top:16px">Alterações recentes</h3>
    <div id="pmChanges"></div>`;
  S.pm = d;
  paintPmChart("daily");
  paintPmChanges(d.changes);
}

function paintPmChart(kind) {
  document.querySelectorAll("[data-pmc]").forEach((b) => b.classList.toggle("on", b.dataset.pmc === kind));
  const ch = S.pm.charts;
  const rows = kind === "daily" ? ch.daily.map((r) => ({ k: r.day, v: r.gain }))
    : kind === "monthly" ? ch.monthly.map((r) => ({ k: r.month, v: r.gain }))
    : ch.quarterly.map((r) => ({ k: r.quarter, v: r.gain }));
  const el = $("#pmSvg");
  if (!rows.length) { el.innerHTML = `<p class="muted">Ainda não há pontos suficientes. A contagem começa em 21/11/2026 e cresce a cada dia.</p>`; return; }
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.v)));
  const W = 520, H = 160, P = 24, bw = (W - 2 * P) / rows.length;
  const bars = rows.map((r, i) => {
    const h = Math.abs(r.v) / max * (H / 2 - P), x = P + i * bw + bw * 0.15, w = bw * 0.7;
    const y = r.v >= 0 ? H / 2 - h : H / 2;
    const col = r.v >= 0 ? "#3ddc84" : "#ff5c5c";
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(h, 1).toFixed(1)}" fill="${col}"><title>${esc(r.k)}: ${fmt(r.v)} XP</title></rect>`;
  }).join("");
  const total = rows.reduce((a, r) => a + r.v, 0);
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Gráfico de XP">
      <line x1="${P}" x2="${W - P}" y1="${H / 2}" y2="${H / 2}" stroke="currentColor" opacity=".3"/>${bars}</svg>
    <div class="hint">Barras verdes: XP ganha. Vermelhas: XP perdida. Total no período: ${fmt(total)} XP.</div>`;
}

function paintPmChanges(list) {
  const el = $("#pmChanges");
  if (!list.length) { el.innerHTML = `<p class="muted">Nenhuma alteração registrada.</p>`; return; }
  el.innerHTML = list.map((m) => {
    const nome = GERAL_LABELS[m.category] || m.category;
    const cor = m.kind === "up" ? "#3ddc84" : "#ff5c5c";
    return `<div class="row" style="justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(128,128,128,.25)">
      <span>${brData(m.day)} · ${esc(nome)}</span><b style="color:${cor}">${m.delta > 0 ? "+" : ""}${fmt(m.delta)}</b></div>`;
  }).join("");
}

document.addEventListener("click", (e) => {
  const tab = e.target.closest("[data-rtab]"), dy = e.target.closest("[data-xdays]"), pl = e.target.closest("[data-player]"), pmc = e.target.closest("[data-pmc]");
  if (tab) return showRankTab(tab.dataset.rtab);
  if (dy) { S.xp.days = +dy.dataset.xdays; return loadXp(); }
  if (pl) { e.preventDefault(); return openPlayer(pl.dataset.player); }
  if (pmc) return paintPmChart(pmc.dataset.pmc);
  if (e.target.closest("#pmClose") || e.target.id === "playerModal") return $("#playerModal").classList.add("hidden");
  if (e.target.closest("#geralPrev")) { S.geral.page--; return loadGeral(); }
  if (e.target.closest("#geralNext")) { S.geral.page++; return loadGeral(); }
});
$("#geralMetric").addEventListener("change", (e) => { S.geral.metric = e.target.value; S.geral.page = 1; loadGeral(); });

/* ---------- 0.23.0: 🤝 substituições (link de envio e jogador autorizado) ---------- */
const SUB_SCOPES = [["solo", "Hunt solo (Stacker)"], ["party", "Lootsplit e sessão da PT"], ["boss", "Bosses"]];
const SUB_HOURS = { 6: "6 horas", 24: "24 horas", 72: "3 dias", 168: "7 dias" };
const LINK_STATE = { active: "✔ valendo", used: "envios esgotados", expired: "venceu", revoked: "cancelado" };
const PLAYED_KIND = { solo: "Hunt solo", boss: "Bosses", hunt: "Lootsplit" };
const scopeName = (s) => (SUB_SCOPES.find(([k]) => k === s) || [s, s])[1];
/** Endereço público da página do link (no app de Windows, o do servidor). O código vai depois do #. */
const linkUrl = (token) => `${S.api || location.origin}/envio#${token}`;
const usesLeft = (n) => (n === 1 ? "1 envio restante" : `${n} envios restantes`);

async function loadSubs() {
  let d;
  try { d = await api("GET", "/api/subs"); }
  catch (err) { if (err.status !== 401) $("#subsLinks").innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  S.subs = d;
  const chars = (S.me && S.me.chars) || [];
  $("#subsCreate").innerHTML = !chars.length ? `<p class="muted">Vincule um personagem em 👤 Meus personagens primeiro.</p>`
    : `<p class="muted" style="margin:0 0 10px">Crie um link e mande para quem vai jogar. A pessoa cola o Hunt Analyser
        ou o Party Hunt Analyser e tudo fica salvo no seu personagem, sem ela precisar de conta.</p>
      <form class="subs-form" id="subsForm">
        <label><span>Personagem</span><select name="character">${chars.map((c) => `<option${c.name === S.nick ? " selected" : ""}>${esc(c.name)}</option>`).join("")}</select></label>
        <div><span class="muted" style="font-size:13px">O que a pessoa pode enviar</span>
          <div class="subs-scopes">${SUB_SCOPES.map(([k, t]) => `<label class="check-row"><input type="checkbox" name="scope" value="${k}" checked> ${t}</label>`).join("")}</div></div>
        <label><span>Validade</span><select name="hours">${d.hours.map((h) => `<option value="${h}"${h === 24 ? " selected" : ""}>${SUB_HOURS[h] || h + " h"}</option>`).join("")}</select></label>
        <label><span>Limite de envios</span><input name="max_uses" type="number" min="1" max="50" value="10" inputmode="numeric"></label>
        <label><span>Personagem de quem vai jogar (opcional)</span><input name="operator" maxlength="40" data-nick-ph autocomplete="off"></label>
        <div class="hint" style="margin:0">Com o nome, o 4rt3mi5 registra quem jogou e, se a pessoa tiver conta aqui, ela também
          envia logada na conta dela: tudo vai para o seu personagem, nunca para o dela.</div>
        <button class="btn" type="submit" style="margin-top:0">Criar link de envio</button>
        <div class="err" id="subsErr"></div></form>`;
  $("#subsLinks").innerHTML = d.links.length ? d.links.map((l) => `<div class="card">
      <div class="row"><b>${esc(l.character)}</b><span class="${l.state === "active" ? "pos" : "muted"}" style="font-size:13px">${LINK_STATE[l.state]}</span></div>
      <div class="muted" style="font-size:13px"><span>${esc(`${l.uses} de ${l.max_uses} envios`)}</span> · <span>${esc(`vale até ${when(l.expires_at)}`)}</span></div>
      ${l.operator ? `<div class="muted" style="font-size:13px">${esc(`Quem joga: ${l.operator}`)}</div>` : ""}
      <div class="chips" style="margin-top:6px">${l.scopes.map((s) => `<span class="chip">${esc(scopeName(s))}</span>`).join("")}</div>
      ${l.state === "active" ? `<div class="row" style="justify-content:flex-end; margin-top:6px"><button class="danger-link" data-link-revoke="${l.id}">Cancelar link</button></div>` : ""}</div>`).join("")
    : `<p class="muted">Nenhum link criado ainda.</p>`;
  $("#subsGrants").innerHTML = d.grants.length ? d.grants.map((g) => `<div class="card">
      <div class="row"><b>${esc(g.character)}</b><span class="muted" style="font-size:13px">${esc(`como ${g.as}`)}</span></div>
      <div class="muted" style="font-size:13px"><span>${esc(usesLeft(g.uses_left))}</span> · <span>${esc(`vale até ${when(g.expires_at)}`)}</span></div>
      ${g.scopes.includes("party") ? `<div class="hint">Lootsplit: envie normalmente em 💰 Lootsplit. O app reconhece o personagem na PT e salva para o dono.</div>` : ""}
      <div class="tagline-row">${g.scopes.includes("solo") ? `<button class="tagbtn" data-grant-send="solo" data-char="${esc(g.character)}">＋ Sessão do Stacker</button>` : ""}
        ${g.scopes.includes("boss") ? `<button class="tagbtn" data-grant-send="boss" data-char="${esc(g.character)}">＋ Sessão de boss</button>` : ""}</div></div>`).join("")
    : `<p class="muted">Ninguém autorizou um personagem seu. Quando alguém colocar o nome do seu personagem num link de envio, ele aparece aqui.</p>`;
  $("#subsPlayed").innerHTML = d.played.length ? `<div class="table-wrap"><table><tr><th>Personagem</th><th>Quando</th><th>Tempo</th><th>XP</th><th>Balance</th></tr>
      ${d.played.map((p) => `<tr><td>${esc(p.name)}<div class="muted" style="font-size:12px">${PLAYED_KIND[p.kind] || ""}</div></td>
        <td>${when(p.started_at)}</td><td>${dur(p.duration_seconds)}</td><td>${p.xp == null ? "—" : kk(p.xp)}</td>
        <td class="${(p.balance || 0) >= 0 ? "pos" : "neg"}">${p.balance == null ? "—" : kk(p.balance)}</td></tr>`).join("")}</table></div>
      <div class="hint">Só você vê. Aparece o que os donos marcaram como jogado por um personagem seu. No lootsplit, Balance é a parte de cada um.</div>`
    : `<p class="muted">Nada por aqui.</p>`;
  setBadge("subsBadge", 0);
  paintNickPh($("#subsCreate"));
}
document.addEventListener("submit", async (e) => {
  const f = e.target.closest("#subsForm");
  if (!f) return;
  e.preventDefault();
  const btn = f.querySelector("button[type=submit]"), err = $("#subsErr");
  err.textContent = "";
  const scopes = [...f.querySelectorAll("[name=scope]:checked")].map((x) => x.value);
  if (!scopes.length) { err.textContent = "Escolha o que a pessoa pode enviar."; return; }
  const body = { character: f.character.value, scopes, hours: +f.hours.value, max_uses: +f.max_uses.value || 10 };
  const op = f.operator.value.trim();
  if (op) body.operator = op;
  btn.disabled = true;
  try {
    const r = await api("POST", "/api/links", body);
    const url = linkUrl(r.token), until = when(r.link.expires_at);
    // a mensagem vai copiada (fora da tela): já sai no idioma escolhido
    const msg = I18N.t(`Link para enviar as hunts de ${r.link.character} no 4rt3mi5 (vale até ${until}): ${url} — abra, cole o Hunt Analyser ou o Party Hunt Analyser e toque em Enviar.`);
    $("#subsNew").innerHTML = `<div class="card" style="border-color:var(--gold)"><b>🔗 Link criado</b>
      <div class="subs-link" data-i18n-skip>${esc(url)}</div>
      <div class="row" style="gap:8px; justify-content:flex-start">
        <button class="copy" data-copy="${esc(url)}">Copiar link</button><button class="copy" data-copy="${esc(msg)}">Copiar mensagem pronta</button></div>
      <div class="hint">⚠️ O link só aparece agora. Mande só para quem vai jogar: quem tiver o link pode enviar hunts para o seu personagem até ele vencer.</div></div>`;
    f.operator.value = "";
    loadSubs();
    $("#subsNew").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "center" });
  } catch (ex) { if (ex.status !== 401) err.textContent = ex.message; }
  finally { btn.disabled = false; }
});
document.addEventListener("click", async (e) => {
  const rv = e.target.closest("[data-link-revoke]"), gs = e.target.closest("[data-grant-send]");
  if (rv) {
    if (!confirm("Cancelar este link de envio? Quem tiver o link não vai mais conseguir enviar.")) return;
    rv.disabled = true;
    try { await api("DELETE", `/api/links/${rv.dataset.linkRevoke}`); loadSubs(); }
    catch (err) { rv.disabled = false; if (err.status !== 401) alert(err.message); }
  }
  if (gs) openGrantSend(gs.dataset.grantSend, gs.dataset.char);
});
/** Jogador autorizado: cola a sessão e ela vai para o personagem do dono. */
function openGrantSend(kind, char) {
  openModal(`<h3>${kind === "boss" ? "👑 Sessão de boss" : "📈 Sessão do Stacker"}</h3>
    <p class="muted" style="margin-top:0">${esc(`Vai para ${char}, marcada como jogada por você.`)}</p>
    ${kind === "boss" ? `<div class="seg" role="tablist" id="grantMode"><button data-gmode="solo" class="on" type="button">Solo</button><button data-gmode="party" type="button">Party</button></div>` : ""}
    <textarea id="grantText" spellcheck="false" style="margin-top:8px" placeholder="Session data: From ... to ...&#10;Session: 01:30h&#10;..."></textarea>
    <button class="btn2 paste-btn" data-paste-into="grantText" data-paste-err="grantErr" type="button">📋 Colar da área de transferência</button>
    <div class="actions"><button class="btn" id="grantSave" type="button" data-kind="${kind}" data-char="${esc(char)}">Enviar</button><button class="btn2" data-close-modal type="button">Cancelar</button></div>
    <div class="err" id="grantErr"></div>`);
}
document.addEventListener("click", async (e) => {
  const m = e.target.closest("[data-gmode]");
  if (m) { document.querySelectorAll("[data-gmode]").forEach((x) => x.classList.toggle("on", x === m)); return; }
  const b = e.target.closest("#grantSave");
  if (!b) return;
  const raw = $("#grantText").value.trim();
  if (!raw) { $("#grantErr").textContent = "Cole o Hunt Analyser primeiro."; return; }
  b.disabled = true; $("#grantErr").textContent = "";
  try {
    const boss = b.dataset.kind === "boss";
    const mode = (document.querySelector("[data-gmode].on") || {}).dataset?.gmode || "solo";
    const r = await api("POST", boss ? "/api/bosses/session" : "/api/stacker",
      boss ? { raw_text: raw, nickname: S.nick, mode, for_char: b.dataset.char } : { raw_text: raw, nickname: S.nick, for_char: b.dataset.char });
    openModal(`<div class="banner ok">${r.created ? esc(`Enviado para ${r.saved_as} ✔`) : "Essa sessão já estava salva ✔"}</div>
      <div class="actions"><button class="btn2" data-close-modal type="button">Ok</button></div>`);
    loadSubs();
  } catch (err) {
    b.disabled = false;
    if (err.status !== 401) $("#grantErr").innerHTML = `${esc(err.message)}${err.hint ? `<div class="hint">${esc(err.hint)}</div>` : ""}`;
  }
});

/** 0.23.0: avisos do Início — o que chegou pelo link de envio e tentativa de vincular um personagem seu. */
async function subsNotices() {
  const me = await api("GET", "/api/me").catch(() => null);
  if (!me) return "";
  S.me = me;
  setBadge("subsBadge", me.link_sends || 0);
  let out = "";
  if (me.link_sends) out += `<div class="banner ok">🤝 ${esc(me.link_sends === 1 ? "1 envio chegou pelo seu link nas últimas 24 horas." : `${me.link_sends} envios chegaram pelo seu link nas últimas 24 horas.`)}
    <button class="link" data-page-link="subs" style="display:block">Ver em 🤝 Substituições</button></div>`;
  const seen = (await kv.get("claims_seen")) || "";
  const fresh = (me.char_claims || []).filter((c) => c.at > seen);
  if (fresh.length) {
    const names = fresh.map((c) => (me.chars.find((x) => x.name.toLowerCase() === c.name_key) || { name: c.name_key }).name);
    out += `<div class="banner bad"><b>⚠️ ${esc(names.length === 1 ? `Alguém tentou vincular ${names[0]} em outra conta do 4rt3mi5.` : `Alguém tentou vincular ${names.join(", ")} em outra conta do 4rt3mi5.`)}</b>
      <div class="hint">O personagem continua só seu: ninguém mais consegue usá-lo aqui. Se você passou a conta do Tibia para alguém,
        apague do comentário do personagem qualquer código 4RT3MI5 e troque a senha do Tibia.</div>
      <button class="link" data-page-link="chars" style="display:block; margin-top:6px">Ver em 👤 Meus personagens</button>
      <button class="btn2" style="margin-top:8px" data-claims-ok="${esc(fresh.map((c) => c.at).sort().pop())}">Entendi</button></div>`;
  }
  return out;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-claims-ok]");
  if (!b) return;
  kv.set("claims_seen", b.dataset.claimsOk);
  b.closest(".banner").remove();
});

/** Sessão recém-enviada x sua média na mesma hunt. */
function compareBanner(c) {
  if (!c) return "";
  if (!c.sessions) return `<div class="card">📊 Sua primeira sessão em <b>${esc(c.place)}</b> (com 10 min ou mais):
    ${fmt(c.xp_h)} XP/h e ${fmt(c.gold_h)} gp/h de balance. As próximas vão ser comparadas com ela.</div>`;
  const line = (label, v, avg, pct) => {
    const cls = pct == null ? "muted" : pct >= 0 ? "pos" : "neg";
    const txt = pct == null ? "" : pct === 0 ? "igual à média" : `${Math.abs(pct)}% ${pct > 0 ? "acima" : "abaixo"} da média`;
    return `<div class="row"><span>${label}: <b>${fmt(v)}</b> <span class="muted">(média ${fmt(avg)})</span></span><b class="${cls}">${txt}</b></div>`;
  };
  return `<div class="card"><b>📊 Comparada com a sua média em ${esc(c.place)}</b>
    <div class="muted" style="font-size:13px; margin-bottom:6px">Média das suas outras ${c.sessions} ${c.sessions === 1 ? "sessão" : "sessões"} lá (10 min ou mais).</div>
    ${line("XP/h", c.xp_h, c.avg_xp_h, c.xp_pct)}${line("Balance/h", c.gold_h, c.avg_gold_h, c.gold_pct)}</div>`;
}
/* ---------- avisos de venda, metas, previsão, recordes, lista de venda ---------- */
/* ---------- 👑 rotação de bosses (solo / party) ---------- */
S.btab = "solo";
function showBossTab(tab) {
  S.btab = tab === "party" ? "party" : "solo";
  document.querySelectorAll("#bossTabs [data-btab]").forEach((b) => {
    const on = b.dataset.btab === S.btab;
    b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on));
  });
  // 0.22.2: Solo = Boss Session Stacker (a sua sessão, só sua) · Party = Lootsplit de bosses (quem paga quem, para toda a PT)
  const party = S.btab === "party";
  $("#bossTitle").textContent = party ? "Lootsplit de bosses" : "Boss Session Stacker";
  $("#bossIntro").textContent = party
    ? "👥 Cole o Party Hunt Analyser da luta: o app divide o loot e o lootsplit aparece para todos da PT."
    : "🧍 Cole o Hunt Analyser da luta solo. 🔒 Só você vê as suas sessões de boss.";
  $("#bossModeNote").innerHTML = "";
  $("#bossLabel").textContent = party ? "Cole aqui o Party Hunt Analyser do boss" : "Cole aqui o Hunt Analyser do boss (solo)";
  $("#bossText").placeholder = party ? "Session data: From ... to ...\nSession: 00:25h\nLoot Type: Leader\n..."
    : "Session data: From ... to ...\nSession: 00:25h\nRaw XP Gain: ...\nKilled Monsters:\n  1x Grand Master Oberon";
  $("#bossBtn").textContent = party ? "Calcular e enviar" : "Salvar sessão de boss";
  $("#bossAsk").innerHTML = "";
}
$("#bossTabs").addEventListener("click", (e) => { const b = e.target.closest("[data-btab]"); if (b) showBossTab(b.dataset.btab); });

const BOSS_CLASS = { Nemesis: "nemesis", Archfoe: "archfoe", Bane: "bane" };
function bossTag(b) {
  return `<span style="display:inline-flex; align-items:center; gap:6px">${creatureImg(b.key || b.name)}<b>${esc(b.name)}</b>`
    + `${b.class ? `<span class="boss-class ${BOSS_CLASS[b.class] || ""}">${esc(b.class)}</span>` : ""}</span>`;
}
function bossChips(list) {
  return list.length ? `<div class="chips">${list.map((b) => `<span class="chip" style="display:inline-flex; align-items:center; gap:6px">${creatureImg(b.key || b.name)}${fmt(b.count)}x ${esc(b.name)}</span>`).join("")}</div>`
    : `<span class="muted">nenhum boss reconhecido</span>`;
}
function bossTable(list) {
  if (!list.length) return `<p class="muted">Nenhum boss reconhecido ainda.</p>`;
  return `<div class="table-wrap"><table><tr><th>Boss</th><th>Kills</th><th>Loot</th><th>Último</th></tr>
    ${list.map((b) => `<tr><td>${bossTag(b)}${b.from_hunts ? `<div class="muted" style="font-size:12px">${b.from_hunts} em hunts do Stacker</div>` : ""}</td>
      <td>${fmt(b.kills)}</td><td>${b.value ? kk(b.value) : "—"}</td><td>${b.last ? esc(dayLabel(b.last.slice(0, 10))) : "—"}</td></tr>`).join("")}
  </table></div>`;
}
function bossSessionItem(s) {
  const party = s.party ? `<div class="muted" style="font-size:13px">👥 Lootsplit da party: <b class="${s.party.profit_each >= 0 ? "gold" : "neg"}">${kk(s.party.profit_each)} para cada</b> (${s.party.players_count} jogadores)</div>`
    : s.mode === "party" ? `<div class="muted" style="font-size:13px">👥 Party sem lootsplit (guardada só para você)</div>` : "";
  return `<details class="card"><summary>
      <div class="row"><b>${when(s.started_at)}</b><span class="pill">${s.mode === "party" ? "party" : "solo"}</span></div>
      ${s.other_player ? `<div><span class="who other" style="margin-left:0">${s.played_by ? esc(`🤝 Jogada por ${s.played_by}`) : "🤝 Jogada por outra pessoa"}</span></div>` : ""}
      ${rotationLine(s.rotation)}
      <div style="margin-top:4px">${bossChips(s.bosses)}</div>
      <div class="row muted"><span>${dur(s.duration_seconds)}${s.loot_value ? " · loot ≈ " + kk(s.loot_value) : ""}</span>
        <span class="${s.balance >= 0 ? "pos" : "neg"}">balance ${kk(s.balance)}</span></div>
      ${party}
    </summary>
    <div style="margin-top:10px">${statGrid([
      ["XP", fmt(s.xp)], ["Balance", fmt(s.balance) + " gp"], ["Supplies", fmt(s.supplies) + " gp"],
      ["Lucro líquido real", fmt(s.net_profit) + " gp", s.net_profit >= 0 ? "pos" : "neg"],
      ["Damage", fmt(s.damage)], ["Healing", fmt(s.healing)],
    ])}</div>
    ${s.loot.length ? `<h2>Itens coletados</h2>${itemList(s.loot, 999)}` : ""}
    ${s.kills.length ? `<h2>Criaturas mortas</h2>${killChips(s.kills)}` : ""}
    ${s.vault ? vaultBlock(s.vault) : ""}
    ${playerMarkBox("boss", s)}
    ${s.can_delete ? `<div style="margin-top:10px"><button class="danger-link" data-del-boss-session="${s.id}">🗑 Apagar esta sessão de boss</button></div>` : ""}</details>`;
}
function bossHuntItem(h) {
  h.kind = "boss";
  const v = view(h, S.nick);
  return `<details class="card"><summary>
      <div class="row"><b>${when(h.started_at)}</b>${settleTag(v)}</div>
      <div class="row muted"><span>${dur(h.duration_seconds)} · ${h.players_count} jogadores${h.pending ? ` · ⏳ ${h.pending} a pagar` : ""}</span>
        <span class="${h.profit_each >= 0 ? "gold" : "neg"}">${kk(h.profit_each)} cada (${kk(h.profit_each_per_hour)}/h)</span></div>
      <div class="muted" style="font-size:13px">Sessões vinculadas: ${h.members && h.members.length ? h.members.map(esc).join(", ") : "nenhuma ainda"}</div>
      ${rotationLine(h.rotation)}
    </summary>${claimBanner(h)}${rulesLine(h)}${actionBox(v, h)}${chartToggle(h, S.nick)}<h2>Transferências</h2>${transfersBox(h)}${partyTable(h, S.nick)}${rulesBox(h)}${tagsBox(h)}${h.vault ? vaultBlock(h.vault) : ""}${deleteButton(h)}</details>`;
}
/* ---------- 0.23.0: 👑 rotações e 🗃️ cofre da rotação ---------- */
/** "Rotação Bastions: Cobra Bastion" -> linha com a coroa (o nome dos bosses fica como no jogo). */
function rotationLine(r) {
  if (!r) return "";
  return `<div class="rot-name">${esc(`👑 Rotação ${r.name.replace(/^Rotação /, "")}`)}</div>`;
}
function rotationsBlock(list, mode) {
  const rows = (list || []).filter((r) => r.mode === mode).slice(0, 15);
  if (!rows.length) return "";
  return `<details class="card"><summary class="row"><b>👑 Rotações</b><span class="muted">${rows.length} ▾</span></summary>
    ${rows.map((r) => `<div class="row" style="padding:6px 0; border-bottom:1px solid var(--line)">
      <span><b>${esc(dayLabel(r.day))}</b> · ${esc(`👑 Rotação ${r.name.replace(/^Rotação /, "")}`)}
        <div class="muted" style="font-size:12px">${r.groups.map((g) => esc(g.quest)).join(" · ")}</div></span>
      <span class="${r.balance >= 0 ? "pos" : "neg"}">${kk(r.balance)}</span></div>`).join("")}
    <div class="hint">Rotação = os bosses do mesmo dia, pelo grupo de cada um (quest ou lore). Nomes como a comunidade usa.</div></details>`;
}
/** Taxa do Market pela regra atual (a mesma conta do servidor). */
function marketFee(total) {
  const r = (S.boss && S.boss.fee) || { pct: 2.5, cap: 2500000, min: 20 };
  return total > 0 ? Math.min(r.cap, Math.max(r.min, Math.floor(total * r.pct / 100))) : 0;
}
const VAULT_STATUS = { stock: "📦 no estoque", sold: "✔ vendido", used: "🔨 usado" };
const vref = (v) => `${v.ref.kind}:${v.ref.id}`;
const VAULTS = new Map();  // "kind:id" -> cofre mostrado
function vaultTransfers(kind, id, list) {
  if (!list.length) return "";
  return `<div style="margin-top:6px">${list.map((t) => {
    const mine = isMine(t.payer) || isMine(t.receiver);
    const mark = t.paid_at ? `<span class="pos" style="font-size:13px">${esc(`✔ pago ${new Date(t.paid_at).toLocaleDateString("pt-BR")}`)}</span>`
      : mine ? `<button class="btn2" style="padding:3px 9px; font-size:13px" data-vpaid="${kind}:${id}" data-payer="${esc(t.payer)}" data-receiver="${esc(t.receiver)}">${isMine(t.payer) ? "✔ Já paguei" : "✔ Recebi"}</button>`
      : `<span class="muted" style="font-size:13px">⏳ falta pagar</span>`;
    return `<div class="tx"><div class="row"><span><b>${esc(t.payer)}</b> → <b>${esc(t.receiver)}</b>${subTag(t.receiver)}</span><b class="gold">${fmt(t.amount)} gp</b></div>
      <div class="row"><code>${esc(t.command)}</code><span>${mark}</span></div></div>`;
  }).join("")}</div>`;
}
let VAULT_SUBS = [];
const subTag = (name) => (VAULT_SUBS.some((s) => s.toLowerCase() === String(name).toLowerCase()) ? `<span class="who sub">🔁 substituto</span>` : "");
/** Prévia da venda: taxa, líquido e quanto fica para cada um (atualiza enquanto digita). */
function sellPreview(total, withFee, members, cost = 0, perItem = 0) {
  if (!(total > 0)) return "";
  const fee = withFee ? marketFee(total) : 0, net = total - fee - cost, each = Math.floor(net / Math.max(1, members));
  return `<span>${esc(`Taxa do Market: ${fmt(fee)} gp`)}</span> · <span>${esc(`Líquido: ${fmt(net)} gp`)}</span>`
    + (perItem ? ` · <span>${esc(`${fmt(Math.floor(net / perItem))} gp por runa`)}</span>` : "")
    + ` · <b class="gold">${esc(`${fmt(each)} gp para cada um`)}</b>`;
}
function vaultBlock(v, open = false) {
  VAULTS.set(vref(v), v);
  VAULT_SUBS = v.subs || [];
  const n = v.members.length, mineIn = v.members.some(isMine);
  // padrão dos seletores: o personagem ativo (se estava na rotação), senão o primeiro personagem seu
  const me = v.members.find((m) => m.toLowerCase() === (S.nick || "").toLowerCase()) || v.members.find(isMine);
  const memberOpts = v.members.map((m) => `<option${m === me ? " selected" : ""}>${esc(m)}</option>`).join("");
  const drops = v.drops.map((d) => {
    const sold = d.status === "sold";
    return `<div class="vault-row" data-vdrop="${d.id}">
      <div class="row"><b>${fmt(d.qty)}x ${esc(d.item)}</b><span class="muted" style="font-size:13px">${VAULT_STATUS[d.status]}</span></div>
      <div class="vault-key" title="Código e dia do drop">${esc(d.code)} · ${esc(dayLabel(d.dropped_on))}</div>
      <div class="muted" style="font-size:13px"><span>${esc(`dropou: ${d.dropped_by}`)}</span>${d.estimate ? ` · <span>${esc(`estimado ${fmt(d.estimate)} gp`)}</span>` : ""}</div>
      ${sold ? `<div style="font-size:14px; margin-top:4px"><span>${esc(`Vendido por ${fmt(d.sold_total)} gp`)}</span>${d.market_fee ? ` · <span>${esc(`taxa ${fmt(d.fee)} gp`)}</span>` : ""}
        · <span>${esc(`líquido ${fmt(d.net)} gp`)}</span> · <b class="gold">${esc(`${fmt(d.each)} gp para cada um`)}</b></div>${vaultTransfers("drop", d.id, d.transfers)}` : ""}
      ${d.can_edit && d.status === "stock" ? `<div class="vault-actions">
          <input type="number" min="0" step="1" inputmode="numeric" placeholder="Preço de cada (gp)" value="${d.price_each ?? ""}" data-vprice-in aria-label="Preço de cada (gp)">
          <button class="btn2" data-vprice="${d.id}">Salvar preço</button>
          <button class="btn2" data-vsell-open="${d.id}">💰 Vendi</button>
          <button class="danger-link" data-vdel="${d.id}">Apagar</button></div>
        <div class="vault-sell hidden" data-vsell-box="${d.id}">
          <input type="number" min="1" step="1" inputmode="numeric" placeholder="Vendido por quanto (total, gp)" data-vtotal aria-label="Vendido por quanto (total, gp)">
          <label class="check-row"><input type="checkbox" data-vfee checked> Taxa do Market</label>
          <div class="hint" data-vpreview data-members="${n}"></div>
          <button class="btn2" data-vsell="${d.id}">Confirmar venda</button></div>` : ""}
      ${d.can_edit && sold ? `<button class="link" style="font-size:13px" data-vstock="${d.id}">desfazer venda</button>` : ""}</div>`;
  }).join("");
  const crafts = v.crafts.map((c) => `<div class="vault-row">
      <div class="row"><b>${esc(`🔨 ${c.label} → ${c.result || "?"}`)}</b><span class="muted" style="font-size:13px">${esc(`fica com ${c.seller}`)}</span></div>
      <div class="muted" style="font-size:13px"><span>Do estoque:</span> ${esc(c.used.map((u) => `${u.item} ${u.code} (${dayLabel(u.dropped_on)}, ${u.dropped_by})`).join(", ") || "—")}${c.bought.length
        ? ` · <span>Compradas:</span> ${esc(c.bought.map((b) => `${b.item} (${fmt(b.cost)} gp)`).join(", "))}` : ""}</div>
      ${c.sold_total ? `<div style="font-size:14px; margin-top:4px"><span>${esc(`Vendido por ${fmt(c.sold_total)} gp`)}</span>${c.market_fee ? ` · <span>${esc(`taxa ${fmt(c.fee)} gp`)}</span>` : ""}
        ${c.cost ? ` · <span>${esc(`runas compradas ${fmt(c.cost)} gp`)}</span>` : ""} · <span>${esc(`líquido ${fmt(c.net)} gp`)}</span>
        · <span>${esc(`${fmt(c.per_item)} gp por runa`)}</span> · <b class="gold">${esc(`${fmt(c.each)} gp para cada um`)}</b></div>${vaultTransfers("craft", c.id, c.transfers)}`
        : `<div class="hint">Ainda não vendido.</div>`}
      ${c.can_edit ? `<div class="vault-actions" data-vcraft-box="${c.id}">
          <input type="number" min="1" step="1" inputmode="numeric" placeholder="Vendido por quanto (total, gp)" value="${c.sold_total ?? ""}" data-vtotal aria-label="Vendido por quanto (total, gp)">
          <label class="check-row"><input type="checkbox" data-vfee${c.sold_total ? (c.market_fee ? " checked" : "") : " checked"}> Taxa do Market</label>
          <button class="btn2" data-vcraft-sell="${c.id}">Salvar venda</button>
          <button class="danger-link" data-vcraft-del="${c.id}">Desfazer o uso</button>
          <div class="hint" data-vpreview data-members="${n}" data-cost="${c.cost}" data-per="5"></div></div>` : ""}</div>`).join("");
  const sets = Object.entries(v.sets).map(([key, s]) => {
    const have = Object.values(s.have).filter((x) => x > 0).length, total = Object.keys(s.have).length;
    // estoque de cada tipo, com a chave (#código · dia) de cada unidade
    const lines = Object.keys(s.have).map((item) => {
      const units = v.drops.filter((d) => d.status === "stock" && d.item === item);
      return `<div class="row" style="font-size:13px; padding:2px 0"><span>${s.have[item] ? "✔" : "—"} ${esc(item)}</span>
        <span class="muted">${units.length ? units.map((d) => esc(`${d.code} · ${dayLabel(d.dropped_on)}${d.qty > 1 ? ` (${d.qty}x)` : ""}`)).join(", ") : ""}</span></div>`;
    }).join("");
    return `<div class="vault-set"><b>${esc(`🧩 ${s.label}: ${have} de ${total} no estoque`)}</b>
      <div style="margin-top:4px">${lines}</div>
      ${s.missing.length ? `<div class="muted" style="font-size:13px">${esc(`Faltam: ${s.missing.join(", ")}`)}</div>` : ""}
      ${mineIn ? `<button class="btn2" style="margin-top:8px" data-vcraft-open="${vref(v)}" data-set="${key}">🔨 Usar o conjunto</button>` : ""}</div>`;
  }).join("");
  return `<details class="card vault"${open ? " open" : ""} data-vault="${vref(v)}"><summary class="row"><b>🗃️ Cofre da rotação</b>
      <span class="muted">${v.drops.length ? esc(`${v.drops.length} ${v.drops.length === 1 ? "item" : "itens"}`) : ""} ▾</span></summary>
    <p class="hint">Drops para vender ou usar depois, inclusive os que caíram para outro membro. A divisão é entre quem estava nesta rotação,
      mesmo que a venda seja meses depois. Só quem registrou um drop muda o preço dele.</p>
    <div class="hint" style="margin-bottom:6px">👥 ${v.members.map((m) => `${esc(m)}${subTag(m)}`).join(", ")}</div>
    ${drops || `<p class="muted">Nenhum drop guardado.</p>`}
    ${sets}${crafts}
    ${mineIn ? `<form class="vault-add" data-vadd="${vref(v)}">
        <input name="item" maxlength="60" placeholder="Item (ex.: Icy Crypt Rune)" list="vaultItems" required aria-label="Item">
        <input name="qty" type="number" min="1" max="1000" value="1" inputmode="numeric" aria-label="Quantidade" style="width:80px">
        <select name="dropped_by" aria-label="Quem dropou">${memberOpts}</select>
        <input name="dropped_on" type="date" value="${esc(String(v.day).slice(0, 10))}" aria-label="Dia do drop" title="Dia do drop">
        <input name="price_each" type="number" min="0" step="1" inputmode="numeric" placeholder="Preço de cada (gp, opcional)" aria-label="Preço de cada (gp, opcional)">
        <button class="btn2" type="submit">＋ Guardar drop</button></form>` : ""}
    <div class="err" data-vault-err="${vref(v)}"></div></details>`;
}
/** Sugestões do campo de item: as Crypt Runes. */
document.body.insertAdjacentHTML("beforeend", `<datalist id="vaultItems">${["Ancient Crypt Rune", "Deathly Crypt Rune", "Fiery Crypt Rune",
  "Icy Crypt Rune", "Necromantic Crypt Rune"].map((i) => `<option value="${i}">`).join("")}</datalist>`);
function paintPreview(box) {
  const pv = box.querySelector("[data-vpreview]");
  if (!pv) return;
  const total = +(box.querySelector("[data-vtotal]") || {}).value || 0, fee = (box.querySelector("[data-vfee]") || {}).checked;
  let cost = +pv.dataset.cost || 0;
  box.querySelectorAll("[data-vbought]").forEach((i) => { if (!i.classList.contains("hidden")) cost += +i.value || 0; });
  pv.innerHTML = sellPreview(total, fee, +pv.dataset.members || 1, cost, +pv.dataset.per || 0);
}
document.addEventListener("input", (e) => {
  const box = e.target.closest("[data-vsell-box],[data-vcraft-box],[data-vset]");
  if (box) paintPreview(box);
});
document.addEventListener("change", (e) => {
  const box = e.target.closest("[data-vsell-box],[data-vcraft-box],[data-vset]");
  if (box && e.target.matches("[data-vfee]")) paintPreview(box);
});
async function vaultCall(ref, method, path, body) {
  const err = document.querySelector(`[data-vault-err="${ref}"]`);
  if (err) err.textContent = "";
  try {
    const v = await api(method, path, body);
    const el = document.querySelector(`[data-vault="${ref}"]`);
    if (el) { el.outerHTML = vaultBlock(v, true); }
    return v;
  } catch (ex) {
    if (ex.status === 401) return null;
    if (err) err.innerHTML = `${esc(ex.message)}${ex.hint ? `<div class="hint">${esc(ex.hint)}</div>` : ""}`;
    return null;
  }
}
document.addEventListener("submit", (e) => {
  const f = e.target.closest("[data-vadd]");
  if (!f) return;
  e.preventDefault();
  const [kind, id] = f.dataset.vadd.split(":");
  const body = { item: f.item.value.trim(), qty: +f.qty.value || 1, dropped_by: f.dropped_by.value };
  if (f.dropped_on.value) body.dropped_on = f.dropped_on.value;
  if (f.price_each.value !== "") body.price_each = +f.price_each.value;
  vaultCall(f.dataset.vadd, "POST", `/api/vault/${kind}/${id}/drops`, body);
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-vprice],[data-vsell-open],[data-vsell],[data-vstock],[data-vdel],[data-vcraft],[data-vcraft-sell],[data-vcraft-del],[data-vpaid]");
  if (!b) return;
  e.preventDefault();
  const ref = b.closest("[data-vault]").dataset.vault, ds = b.dataset;
  if (ds.vsellOpen) { const box = document.querySelector(`[data-vsell-box="${ds.vsellOpen}"]`); box.classList.toggle("hidden"); box.querySelector("[data-vtotal]").focus(); return; }
  if (ds.vprice) {
    const v = b.parentElement.querySelector("[data-vprice-in]").value;
    return vaultCall(ref, "POST", `/api/vault/drops/${ds.vprice}`, { action: "price", price_each: v === "" ? null : +v });
  }
  if (ds.vsell) {
    const box = b.closest("[data-vsell-box]"), total = +box.querySelector("[data-vtotal]").value;
    if (!(total > 0)) { box.querySelector("[data-vtotal]").focus(); return; }
    return vaultCall(ref, "POST", `/api/vault/drops/${ds.vsell}`, { action: "sell", sold_total: total, market_fee: box.querySelector("[data-vfee]").checked });
  }
  if (ds.vstock) return vaultCall(ref, "POST", `/api/vault/drops/${ds.vstock}`, { action: "stock" });
  if (ds.vdel) { if (!confirm("Apagar este drop do cofre?")) return; return vaultCall(ref, "DELETE", `/api/vault/drops/${ds.vdel}`); }
  if (ds.vcraft) {
    const box = b.closest("[data-vset]"), [kind, id] = ds.vcraft.split(":");
    const bought = [...box.querySelectorAll("[data-vbought]")].map((i) => ({ item: i.dataset.vbought, cost: +i.value || 0 }));
    const total = +box.querySelector("[data-vtotal]").value;
    return vaultCall(ref, "POST", `/api/vault/${kind}/${id}/crafts`, {
      set: box.dataset.vset, drop_ids: [...box.querySelectorAll("[data-vuse]")].map((x) => +x.dataset.vuse), bought,
      result: box.querySelector("[data-vresult]").value || null, seller: box.querySelector("[data-vseller]").value,
      ...(total > 0 ? { sold_total: total, market_fee: box.querySelector("[data-vfee]").checked } : {}) });
  }
  if (ds.vcraftSell) {
    const box = b.closest("[data-vcraft-box]"), total = +box.querySelector("[data-vtotal]").value;
    return vaultCall(ref, "POST", `/api/vault/crafts/${ds.vcraftSell}`, total > 0 ? { sold_total: total, market_fee: box.querySelector("[data-vfee]").checked } : {});
  }
  if (ds.vcraftDel) { if (!confirm("Desfazer o uso? Os itens do estoque voltam para o cofre.")) return; return vaultCall(ref, "DELETE", `/api/vault/crafts/${ds.vcraftDel}`); }
  if (ds.vpaid) {
    const [kind, id] = ds.vpaid.split(":");
    return vaultCall(ref, "POST", "/api/vault/paid", { kind, id: +id, payer: ds.payer, receiver: ds.receiver, paid: true });
  }
});
/* 0.23.0: 🔨 usar um conjunto (ex.: Crypt Runes) numa tela própria: 1) escolher qual unidade de cada tipo
   (pelo código e dia do drop) ou dizer que foi comprada; 2) revisar tudo; 3) confirmar. */
const CM = { ref: null, set: null };
function craftModalStep1() {
  const v = VAULTS.get(CM.ref), s = v.sets[CM.set], n = v.members.length;
  const me = v.members.find((m) => m.toLowerCase() === (S.nick || "").toLowerCase()) || v.members.find(isMine);
  const rows = Object.keys(s.have).map((item) => {
    const units = v.drops.filter((d) => d.status === "stock" && d.item === item);
    const opts = units.map((d, i) => `<option value="${d.id}"${i === 0 ? " selected" : ""}>${esc(`${d.code} · ${dayLabel(d.dropped_on)} · dropou ${d.dropped_by}${d.qty > 1 ? ` (${d.qty}x)` : ""}`)}</option>`).join("");
    return `<div class="cm-row" data-cm-item="${esc(item)}"><b>${esc(item)}</b>
      <select data-cm-pick aria-label="${esc(item)}">${opts}<option value="buy"${units.length ? "" : " selected"}>🛒 Comprei esta</option></select>
      <input type="number" min="0" step="1" inputmode="numeric" placeholder="Comprada por (gp)" data-vbought="${esc(item)}"
        class="${units.length ? "hidden" : ""}" aria-label="Comprada por (gp)"></div>`;
  }).join("");
  return `<div id="cmStep1" data-vset="${CM.set}">
    <p class="hint" style="margin-top:0">${esc(`Uma de cada vira 1 item no ${s.npc}. Escolha qual unidade do estoque vai ser usada (pelo código e dia do drop) ou marque as que foram compradas.`)}</p>
    ${rows}
    <label class="vault-label">Qual item saiu?<select data-vresult><option value="">—</option>${s.results.map((r) => `<option>${esc(r)}</option>`).join("")}</select></label>
    <label class="vault-label">Quem ficou com o item?<select data-vseller>${v.members.map((m) => `<option${m === me ? " selected" : ""}>${esc(m)}</option>`).join("")}</select></label>
    <input type="number" min="1" step="1" inputmode="numeric" placeholder="Vendido por quanto (total, gp) — opcional" data-vtotal aria-label="Vendido por quanto (total, gp)" style="margin-top:8px">
    <label class="check-row" style="margin-top:6px"><input type="checkbox" data-vfee checked> Taxa do Market</label>
    <div class="hint" data-vpreview data-members="${n}" data-per="5"></div>
    <div class="actions"><button class="btn" type="button" data-cm-review>Revisar</button><button class="btn2" data-close-modal type="button">Cancelar</button></div>
    <div class="err" id="cmErr"></div></div>
    <div id="cmStep2" class="hidden"></div>`;
}
function openCraftModal(ref, set) {
  Object.assign(CM, { ref, set });
  const s = VAULTS.get(ref).sets[set];
  openModal(`<h3>${esc(`🔨 Usar o conjunto: ${s.label}`)}</h3>${craftModalStep1()}`);
}
/** Lê a tela 1: o que vai ser usado do estoque, o que foi comprado, o item, quem ficou e a venda. */
function craftModalRead() {
  const box = $("#cmStep1"), v = VAULTS.get(CM.ref);
  const plan = [...box.querySelectorAll("[data-cm-item]")].map((row) => {
    const pick = row.querySelector("[data-cm-pick]").value;
    return pick === "buy" ? { item: row.dataset.cmItem, cost: +row.querySelector("[data-vbought]").value || 0 }
      : { item: row.dataset.cmItem, drop: v.drops.find((d) => d.id === +pick) };
  });
  const total = +box.querySelector("[data-vtotal]").value || 0;
  return { plan, result: box.querySelector("[data-vresult]").value, seller: box.querySelector("[data-vseller]").value,
           total, fee: box.querySelector("[data-vfee]").checked };
}
document.addEventListener("change", (e) => {
  const pick = e.target.closest("[data-cm-pick]");
  if (!pick) return;
  pick.parentElement.querySelector("[data-vbought]").classList.toggle("hidden", pick.value !== "buy");
  paintPreview($("#cmStep1"));
});
document.addEventListener("click", async (e) => {
  const open = e.target.closest("[data-vcraft-open]");
  if (open) { e.preventDefault(); return openCraftModal(open.dataset.vcraftOpen, open.dataset.set); }
  if (e.target.closest("[data-cm-review]")) {
    const r = craftModalRead(), v = VAULTS.get(CM.ref);
    const cost = r.plan.reduce((a, p) => a + (p.cost || 0), 0);
    $("#cmStep1").classList.add("hidden");
    $("#cmStep2").classList.remove("hidden");
    $("#cmStep2").innerHTML = `<b>Confira antes de usar</b>
      <div class="table-wrap" style="margin-top:8px"><table><tr><th>Runa</th><th>Origem</th></tr>
      ${r.plan.map((p) => `<tr><td>${esc(p.item)}</td><td>${p.drop
        ? esc(`${p.drop.code} · ${dayLabel(p.drop.dropped_on)} · dropou ${p.drop.dropped_by}`)
        : esc(`🛒 comprada por ${fmt(p.cost)} gp`)}</td></tr>`).join("")}</table></div>
      <div style="margin-top:8px"><span>${esc(`Item: ${r.result || "—"}`)}</span> · <span>${esc(`fica com ${r.seller}`)}</span></div>
      <div class="hint">${r.total ? sellPreview(r.total, r.fee, v.members.length, cost, 5) : "Ainda não vendido."}</div>
      <div class="hint">👥 ${v.members.map(esc).join(", ")}</div>
      <div class="actions"><button class="btn" type="button" data-cm-confirm>Confirmar e usar</button><button class="btn2" type="button" data-cm-back>Voltar</button></div>
      <div class="err" id="cmErr2"></div>`;
    return;
  }
  if (e.target.closest("[data-cm-back]")) { $("#cmStep2").classList.add("hidden"); $("#cmStep1").classList.remove("hidden"); return; }
  const ok = e.target.closest("[data-cm-confirm]");
  if (!ok) return;
  ok.disabled = true;
  const r = craftModalRead(), [kind, id] = CM.ref.split(":");
  try {
    const v = await api("POST", `/api/vault/${kind}/${id}/crafts`, {
      set: CM.set, drop_ids: r.plan.filter((p) => p.drop).map((p) => p.drop.id),
      bought: r.plan.filter((p) => !p.drop).map((p) => ({ item: p.item, cost: p.cost })),
      result: r.result || null, seller: r.seller, ...(r.total > 0 ? { sold_total: r.total, market_fee: r.fee } : {}) });
    closeModal();
    const el = document.querySelector(`[data-vault="${CM.ref}"]`);
    if (el) el.outerHTML = vaultBlock(v, true);
  } catch (ex) {
    ok.disabled = false;
    if (ex.status !== 401) $("#cmErr2").innerHTML = `${esc(ex.message)}${ex.hint ? `<div class="hint">${esc(ex.hint)}</div>` : ""}`;
  }
});

/* ---------- 0.24.0: 🛡️ Minhas parties (titulares + substitutos) e 🗃️ cofre da party ---------- */
const PT = { list: [], rotations: [], vault: null, editing: null };
const PT_KIND = { hunt: "Hunt", boss: "Bosses", both: "Hunt e bosses" };
const ORIGIN_TXT = { drop: "Drop", service: "Service", buy: "Compra" };
/** Sacolinha da origem: 🟡 drop (limpa), 🟢 service ($), 🔴 compra ($). */
function bag(origin) {
  const c = { drop: "#f2c94c", service: "#4cd18a", buy: "#ff7a6b" }[origin] || "#98a1b3";
  const sign = origin === "drop" ? "" : `<text x="12" y="19" text-anchor="middle" font-size="10" font-weight="800" fill="#0b0d12" font-family="system-ui">$</text>`;
  return `<svg class="bag" viewBox="0 0 24 26" role="img" aria-label="${esc(ORIGIN_TXT[origin] || "")}"><title>${esc(ORIGIN_TXT[origin] || "")}</title>
    <path d="M8 3h8l-2 4h-4z" fill="${c}" opacity=".85"/><path d="M9 7h6c5 3 7 8 7 12 0 4-3 6-10 6S2 23 2 19c0-4 2-9 7-12z" fill="${c}"/>
    <path d="M9 7h6" stroke="#0b0d12" stroke-width="1.2" opacity=".5"/>${sign}</svg>`;
}
const bagLegend = () => `<div class="bag-legend"><span>${bag("drop")} Drop (vale entre 0 e o preço médio)</span>
  <span>${bag("service")} Service (runa garantida: metade do valor para o serviçado, dividida entre os titulares)</span><span>${bag("buy")} Compra (volta para quem pagou na venda)</span></div>`;
const ptErr = (ex) => `${esc(ex.message)}${ex.hint ? `<div class="hint">${esc(ex.hint)}</div>` : ""}`;
const gp = (n) => `${fmt(n)} gp`;
const range = (lo, hi) => lo === hi ? gp(lo) : `entre ${kk(lo)} e ${kk(hi)}`;

async function loadParties() {
  $("#ptList").classList.toggle("hidden", !!PT.vault);
  $("#ptVault").classList.toggle("hidden", !PT.vault);
  if (PT.vault) return openPartyVault(PT.vault.party.id);
  $("#ptCards").innerHTML = `<p class="muted">Carregando…</p>`;
  try {
    const r = await api("GET", "/api/parties");
    PT.list = r.parties; PT.rotations = r.rotations;
  } catch (ex) { if (ex.status !== 401) $("#ptCards").innerHTML = `<div class="err">${ptErr(ex)}</div>`; return; }
  renderParties();
}
function renderParties() {
  $("#ptCards").innerHTML = PT.list.map((p) => {
    const rot = PT.rotations.find((r) => r.key === p.rotation);
    const chips = p.members.map((m) => `<span class="pt-chip${isMine(m.name) ? " me" : ""}${m.role === "sub" ? " sub" : ""}">${esc(m.name)}${m.role === "sub" ? " 🔁" : ""}</span>`).join("");
    return `<div class="card"><div class="row"><b>${esc(p.name)}</b><span><span class="pill">${esc(PT_KIND[p.kind])}</span>${rot ? `<span class="pill">${esc(`👑 ${rot.label}`)}</span>` : ""}</span></div>
      <div class="pt-chips">${chips}</div>
      <div class="hint">${esc(`${p.members.filter((m) => m.role === "main").length} titulares · ${p.members.filter((m) => m.role === "sub").length} substitutos (🔁)`)}</div>
      <div class="pv-buttons"><button class="btn2" data-pt-vault="${p.id}">🗃️ Abrir cofre</button>
        ${p.can_edit ? `<button class="btn2" data-pt-edit="${p.id}">✏️ Editar formação</button>` : ""}</div>
      ${p.can_edit ? `<button class="danger-link" data-pt-del="${p.id}">Apagar party</button>` : ""}</div>`;
  }).join("") || `<p class="muted">Você ainda não está em nenhuma party registrada.</p>`;
}
function memberRow(m = { name: "", role: "main" }) {
  return `<div class="pt-mem"><input maxlength="30" placeholder="Nome do personagem" value="${esc(m.name)}" list="ptMyChars" data-pt-name aria-label="Nome do personagem">
    <select data-pt-role aria-label="Função"><option value="main"${m.role === "main" ? " selected" : ""}>Titular</option><option value="sub"${m.role === "sub" ? " selected" : ""}>🔁 Substituto</option></select>
    <button class="danger-link" type="button" data-pt-mem-del aria-label="Tirar da party">✕</button></div>`;
}
function partyForm(p) {
  PT.editing = p ? p.id : null;
  const my = ((S.me && S.me.chars) || []).map((c) => `<option value="${esc(c.name)}">`).join("");
  const members = p ? p.members : [{ name: S.nick || "", role: "main" }];
  const box = $("#ptFormBox");
  box.classList.remove("hidden");
  box.innerHTML = `<h3 style="margin-top:0">${p ? "✏️ Editar party" : "＋ Registrar party"}</h3>
    <datalist id="ptMyChars">${my}</datalist>
    <form class="pt-form" id="ptForm">
      <label><span>Nome da party</span><input name="name" maxlength="40" required value="${esc(p ? p.name : "")}" placeholder="Ex.: PT de quinta, Graveborn da guild"></label>
      <label><span>Para que é</span><select name="kind">${Object.entries(PT_KIND).map(([k, t]) => `<option value="${k}"${(p ? p.kind : "both") === k ? " selected" : ""}>${esc(t)}</option>`).join("")}</select></label>
      <label><span>Rotação de bosses (liga o craft)</span><select name="rotation"><option value="">Nenhuma</option>
        ${PT.rotations.map((r) => `<option value="${esc(r.key)}"${p && p.rotation === r.key ? " selected" : ""}>${esc(`👑 ${r.label} (craft das ${r.set_label})`)}</option>`).join("")}</select></label>
      <div><span class="muted" style="font-size:13px">Formação (titulares dividem as vendas do cofre; substitutos entram quando falta alguém)</span>
        <div id="ptMembers" style="margin-top:6px">${members.map(memberRow).join("")}</div>
        <button class="btn2" type="button" id="ptAddMem">＋ Adicionar personagem</button></div>
      <div class="actions"><button class="btn" type="submit">${p ? "Salvar formação" : "Registrar party"}</button><button class="btn2" type="button" id="ptCancel">Cancelar</button></div>
      <div class="err" id="ptFormErr"></div></form>`;
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}
$("#ptNew").addEventListener("click", () => partyForm(null));
$("#ptFormBox").addEventListener("click", (e) => {
  if (e.target.id === "ptAddMem") { if ($("#ptMembers").children.length < 15) $("#ptMembers").insertAdjacentHTML("beforeend", memberRow()); return; }
  if (e.target.closest("[data-pt-mem-del]")) { e.target.closest(".pt-mem").remove(); return; }
  if (e.target.id === "ptCancel") { $("#ptFormBox").classList.add("hidden"); PT.editing = null; }
});
$("#ptFormBox").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const members = [...f.querySelectorAll(".pt-mem")].map((r) => ({ name: r.querySelector("[data-pt-name]").value.trim(), role: r.querySelector("[data-pt-role]").value }))
    .filter((m) => m.name);
  const body = { name: f.name.value.trim(), kind: f.kind.value, rotation: f.rotation.value || null, members };
  try {
    await api("POST", PT.editing ? `/api/parties/${PT.editing}` : "/api/parties", body);
    $("#ptFormBox").classList.add("hidden"); PT.editing = null;
    loadParties();
  } catch (ex) { if (ex.status !== 401) $("#ptFormErr").innerHTML = ptErr(ex); }
});
$("#ptCards").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.ptVault) return openPartyVault(+b.dataset.ptVault, true);
  if (b.dataset.ptEdit) return partyForm(PT.list.find((p) => p.id === +b.dataset.ptEdit));
  if (b.dataset.ptDel) {
    const p = PT.list.find((x) => x.id === +b.dataset.ptDel);
    if (!confirm(`Apagar a party ${p.name}? O cofre dela (itens, preços e crafts) também é apagado.`)) return;
    try { await api("DELETE", `/api/parties/${p.id}`); loadParties(); } catch (ex) { if (ex.status !== 401) alert(ex.message); }
  }
});

/* --- cofre --- */
async function openPartyVault(id, push = false) {
  try {
    const v = await api("GET", `/api/parties/${id}/vault`);
    if (push) pushNav();
    PT.vault = v;
    $("#ptList").classList.add("hidden");
    $("#ptVault").classList.remove("hidden");
    renderPartyVault();
    window.scrollTo(0, 0);
  } catch (ex) { if (ex.status !== 401) alert(ex.message); PT.vault = null; }
}
function closePartyVault() { PT.vault = null; $("#ptVault").classList.add("hidden"); $("#ptList").classList.remove("hidden"); loadParties(); }
const holderOpts = (v, sel) => v.party.members.map((m) => `<option value="${esc(m.name)}"${m.name === sel ? " selected" : ""}>${esc(m.name)}${m.role === "sub" ? " (🔁)" : ""}</option>`).join("");
function myDefault(v) {
  const names = v.party.members.map((m) => m.name);
  return names.find((n) => n.toLowerCase() === (S.nick || "").toLowerCase()) || names.find(isMine) || names[0];
}
function ptTransfers(kind, id, list) {
  if (!list || !list.length) return "";
  return `<div style="margin-top:6px">${list.map((t) => {
    const mine = isMine(t.payer) || isMine(t.receiver);
    const mark = t.paid_at ? `<span class="pos" style="font-size:13px">${esc(`✔ pago ${new Date(t.paid_at).toLocaleDateString("pt-BR")}`)}</span>`
      : mine ? `<button class="btn2" style="padding:3px 9px; font-size:13px" data-pv-paid="${kind}:${id}" data-payer="${esc(t.payer)}" data-receiver="${esc(t.receiver)}">${isMine(t.payer) ? "✔ Já paguei" : "✔ Recebi"}</button>`
      : `<span class="muted" style="font-size:13px">⏳ falta pagar</span>`;
    return `<div class="tx"><div class="row"><span><b>${esc(t.payer)}</b> → <b>${esc(t.receiver)}</b></span><b class="gold">${gp(t.amount)}</b></div>
      <div class="row"><code>${esc(t.command)}</code><span>${mark}</span></div></div>`;
  }).join("")}</div>`;
}
function ptFee(total) {
  const r = (PT.vault && PT.vault.fee) || { pct: 2.5, cap: 2500000, min: 20 };
  return total > 0 ? Math.min(r.cap, Math.max(r.min, Math.floor(total * r.pct / 100))) : 0;
}
/** Prévia da venda: taxa, reembolso das compras, líquido e quanto fica para cada titular. */
function ptSalePreview(box) {
  const pv = box.querySelector("[data-pv-preview]");
  if (!pv) return;
  const total = +box.querySelector("[data-pv-total]").value || 0, fee = box.querySelector("[data-pv-fee]").checked ? ptFee(total) : 0;
  const refund = +pv.dataset.refund || 0, n = Math.max(1, PT.vault.mains.length), net = total - fee - refund;
  pv.innerHTML = total > 0 ? `<span>${esc(`Taxa: ${gp(fee)}`)}</span>${refund ? ` · <span>${esc(`reembolso das compras: ${gp(refund)}`)}</span>` : ""}`
    + ` · <span>${esc(`lucro: ${gp(net)}`)}</span> · <b class="gold">${esc(`${gp(Math.max(0, Math.floor(net / n)))} para cada titular`)}</b>` : "";
}
function sellBox(attr, id, refund, sellerSel) {
  const v = PT.vault;
  return `<div class="vault-sell hidden" ${attr}="${id}">
    <input type="number" min="1" step="1" inputmode="numeric" placeholder="Vendido por quanto (total, gp)" data-pv-total aria-label="Vendido por quanto (total, gp)">
    <select data-pv-seller aria-label="Quem vendeu">${holderOpts(v, sellerSel)}</select>
    <label class="check-row"><input type="checkbox" data-pv-fee checked> Taxa do Market</label>
    <div class="hint" data-pv-preview data-refund="${refund}"></div>
    <button class="btn2" data-pv-sell-ok="${id}">Confirmar venda</button></div>`;
}
function renderPartyVault() {
  const v = PT.vault, p = v.party, t = v.totals;
  const stockRows = v.stock.map((s) => `<tr><td>${esc(s.item)}<div class="muted" style="font-size:12px">${["drop", "service", "buy"].filter((o) => s.origins[o])
      .map((o) => `${bag(o)} ${s.origins[o]}`).join(" ")}</div></td>
    <td class="num">${fmt(s.qty)}</td>
    <td class="num"><input type="number" min="0" step="1" inputmode="numeric" value="${s.price ?? ""}" placeholder="sem preço" data-pv-price="${esc(s.item)}" aria-label="${esc(`Preço de ${s.item}`)}"></td>
    <td class="num">${s.qty ? `${kk(s.value)}${s.min !== s.value || s.max !== s.value ? `<div class="pv-range" style="font-size:12px">${esc(range(s.min, s.max))}</div>` : ""}` : "—"}</td></tr>`).join("");
  const items = v.items.filter((i) => i.status !== "used").map((i) => {
    const refund = i.origin === "buy" ? (i.cost_each || 0) * i.qty : 0;
    return `<div class="vault-row">
      <div class="row"><span>${bag(i.origin)} <b>${esc(`${fmt(i.qty)}x ${i.item}`)}</b></span><span class="muted" style="font-size:13px">${VAULT_STATUS[i.status]}</span></div>
      <div class="vault-key">${esc(`${i.code} · ${dayLabel(i.obtained_on)}`)}</div>
      <div class="muted" style="font-size:13px"><span>${esc(`${ORIGIN_TXT[i.origin]} · guarda: ${i.holder}`)}</span>${i.origin === "buy" && i.cost_each != null ? ` · <span>${esc(`pago ${gp(i.cost_each)} cada`)}</span>` : ""}
        ${i.status === "stock" ? ` · <span class="pv-range">${esc(range(i.min, i.max))}</span>` : ""}${i.note ? ` · <span>${esc(i.note)}</span>` : ""}</div>
      ${i.service ? `<div class="pv-craft-sum" style="margin-top:6px">${esc(`🟢 Service de ${i.service.client}: runa de ${kk(i.service.rune_value)} → metade ${kk(i.service.half)} ÷ ${PT.vault.mains.length} titulares = `)}<b class="gold">${esc(`${gp(i.service.each)} de cada um`)}</b>
        ${ptTransfers("service", i.id, i.service.transfers)}</div>` : ""}
      ${i.status === "sold" ? `<div style="font-size:14px; margin-top:4px"><span>${esc(`Vendido por ${gp(i.sold_total)} (${i.seller})`)}</span>${i.fee ? ` · <span>${esc(`taxa ${gp(i.fee)}`)}</span>` : ""}
        ${i.refund ? ` · <span>${esc(`reembolso ${gp(i.refund)}`)}</span>` : ""} · <span>${esc(`lucro ${gp(i.net)}`)}</span> · <b class="gold">${esc(`${gp(i.each)} para cada titular`)}</b></div>
        ${ptTransfers("item", i.id, i.transfers)}<button class="link" style="font-size:13px" data-pv-stock="${i.id}">desfazer venda</button>` : ""}
      ${i.status === "stock" ? `<div class="vault-actions"><button class="btn2" data-pv-sell="${i.id}">💰 Vendi</button>
          <select data-pv-origin="${i.id}" aria-label="Origem">${["drop", "service", "buy"].map((o) => `<option value="${o}"${o === i.origin ? " selected" : ""}>${esc(`Origem: ${ORIGIN_TXT[o]}`)}</option>`).join("")}</select>
          ${i.can_delete ? `<button class="danger-link" data-pv-del="${i.id}">Apagar</button>` : ""}</div>
        ${sellBox("data-pv-sellbox", i.id, refund, i.holder)}` : ""}</div>`;
  }).join("");
  const crafts = v.crafts.map((c) => `<div class="vault-row">
      <div class="row"><b>${esc(`🔨 ${c.label} → ${c.result || "?"}`)}</b><span class="muted" style="font-size:13px">${esc(`fica com ${c.holder}`)}</span></div>
      <div class="pv-craft-sum">Preço aproximado: <b class="pv-range">${esc(range(c.min, c.max))}</b>
        <div class="muted" style="font-size:13px">${c.used.map((u) => `${bag(u.origin)} ${esc(`${u.item.replace(" Crypt Rune", "")}: ${u.origin === "drop" || u.cost_each == null ? `0 a ${kk(u.ref_price || 0)}` : kk(u.cost_each)}`)}`).join(" · ")}</div>
        ${c.cost ? `<div class="muted" style="font-size:13px">${esc(`Compras a reembolsar na venda: ${gp(c.cost)}`)}</div>` : ""}</div>
      ${c.sold_total ? `<div style="font-size:14px; margin-top:6px"><span>${esc(`Vendido por ${gp(c.sold_total)}`)}</span>${c.fee ? ` · <span>${esc(`taxa ${gp(c.fee)}`)}</span>` : ""}
        ${c.refund ? ` · <span>${esc(`reembolso ${gp(c.refund)}`)}</span>` : ""} · <span>${esc(`lucro ${gp(c.net)}`)}</span> · <b class="gold">${esc(`${gp(c.each)} para cada titular`)}</b>
        <div class="hint">${esc(c.sold_total - c.fee >= c.max ? "Vendeu acima do máximo estimado 🎉" : c.sold_total - c.fee <= c.min ? "Vendeu abaixo do mínimo: as compras não se pagaram." : "Venda dentro da faixa estimada.")}</div></div>
        ${ptTransfers("craft", c.id, c.transfers)}` : `<div class="hint">Ainda não vendido — o valor é pedido quando vender.</div>`}
      <div class="vault-actions">${c.sold_total ? `<button class="link" style="font-size:13px" data-pv-craft-unsell="${c.id}">desfazer venda</button>`
        : `<button class="btn2" data-pv-craft-sell="${c.id}">💰 Vendi o item craftado</button>`}
        ${c.can_delete ? `<button class="danger-link" data-pv-craft-del="${c.id}">Desfazer o craft</button>` : ""}</div>
      ${c.sold_total ? "" : sellBox("data-pv-craftbox", c.id, c.cost, c.holder)}</div>`).join("");
  const cs = v.craft_set;
  const setBox = cs ? `<div class="vault-set"><b>${esc(`🧩 ${cs.label}: ${cs.items.filter((x) => cs.have[x]).length} de ${cs.items.length} no estoque`)}</b>
      <div style="margin-top:4px">${cs.items.map((x) => `<div class="row" style="font-size:13px; padding:2px 0"><span>${cs.have[x] ? "✔" : "—"} ${esc(x)}</span>
        <span>${v.items.filter((i) => i.status === "stock" && i.item === x).map((i) => `${bag(i.origin)}${i.qty > 1 ? esc(`×${i.qty}`) : ""}`).join(" ")}</span></div>`).join("")}</div>
      <div class="pv-buttons"><button class="btn2" data-pv-buy>🛒 Alguém comprou um item para o craft</button>
        <button class="btn2" data-pv-craft${cs.missing.length ? " disabled" : ""}>🔨 Craftar</button></div>
      ${cs.missing.length ? `<div class="muted" style="font-size:13px">${esc(`Para craftar faltam: ${cs.missing.join(", ")}`)}</div>` : ""}</div>` : "";
  $("#ptVault").innerHTML = `<button class="link" id="ptBack" type="button">← Minhas parties</button>
    <h1 style="margin-top:6px">${esc(`🗃️ Cofre · ${p.name}`)}</h1>
    <div class="pt-chips">${p.members.map((m) => `<span class="pt-chip${isMine(m.name) ? " me" : ""}${m.role === "sub" ? " sub" : ""}">${esc(m.name)}${m.role === "sub" ? " 🔁" : ""}</span>`).join("")}</div>
    <div class="stats" style="margin-top:12px">
      <div class="stat"><span class="muted">Itens no estoque</span><b>${fmt(t.units)}</b></div>
      <div class="stat"><span class="muted">Valor (preço do cofre)</span><b>${kk(t.value)}</b></div>
      <div class="stat"><span class="muted">Faixa (drops 0 → preço)</span><b class="pv-range">${esc(range(t.min, t.max))}</b></div>
      <div class="stat"><span class="muted">Investido em compras</span><b>${kk(t.invested)}</b></div></div>
    ${t.unpriced.length ? `<div class="banner bad" style="margin-top:8px">${esc(`Sem preço: ${t.unpriced.join(", ")}. Coloque quanto está valendo na tabela abaixo.`)}</div>` : ""}
    <h2>📦 Estoque total</h2>
    <div class="table-wrap pv-stock"><table><tr><th>Item</th><th class="num">Qtd</th><th class="num">Valendo (cada)</th><th class="num">Total</th></tr>
      ${stockRows || `<tr><td colspan="4" class="muted">Nada no cofre ainda.</td></tr>`}</table></div>
    <div class="hint">O preço de cada item pode ser mudado a qualquer momento por qualquer membro (vale para o cofre todo). Ele é a "média praticada".</div>
    ${bagLegend()}
    ${setBox}
    <h2>＋ Guardar item</h2>
    <form class="card vault-add" id="pvAdd">
      <input name="item" maxlength="60" placeholder="Item (ex.: Icy Crypt Rune)" list="vaultItems" required aria-label="Item">
      <input name="qty" type="number" min="1" max="1000" value="1" inputmode="numeric" aria-label="Quantidade" style="max-width:80px">
      <select name="origin" aria-label="Origem"><option value="drop">🟡 Drop</option><option value="service">🟢 Service</option><option value="buy">🔴 Compra</option></select>
      <input name="cost_each" type="number" min="0" step="1" inputmode="numeric" placeholder="Quanto pagou (cada, gp)" class="hidden" aria-label="Quanto pagou (cada, gp)">
      <input name="client" maxlength="30" placeholder="Serviçado (personagem)" class="hidden" aria-label="Serviçado (personagem)">
      <input name="rune_value" type="number" min="0" step="1" inputmode="numeric" placeholder="Valor da runa (gp; vazio = preço do cofre)" class="hidden" aria-label="Valor da runa (gp)">
      <div class="hint hidden" id="pvSvcHint" style="flex-basis:100%"></div>
      <select name="holder" aria-label="Quem guarda">${holderOpts(v, myDefault(v))}</select>
      <input name="obtained_on" type="date" value="${new Date().toISOString().slice(0, 10)}" aria-label="Dia" title="Dia">
      <input name="note" maxlength="80" placeholder="Observação (opcional)" aria-label="Observação">
      <button class="btn2" type="submit">＋ Guardar</button></form>
    <div class="err" id="pvErr"></div>
    <h2>Itens</h2>
    <div class="card">${items || `<p class="muted">Nenhum item guardado.</p>`}</div>
    ${crafts ? `<h2>🔨 Crafts</h2><div class="card">${crafts}</div>` : ""}
    <p class="hint">Vendas são divididas igualmente entre os titulares (${esc(v.mains.join(", "))}). Compras voltam para quem pagou antes da divisão.</p>`;
}
async function pvCall(method, path, body) {
  $("#pvErr") && ($("#pvErr").innerHTML = "");
  try { PT.vault = await api(method, `/api/parties/${PT.vault.party.id}/vault${path}`, body); renderPartyVault(); return true; }
  catch (ex) { if (ex.status !== 401) { if ($("#pvErr")) { $("#pvErr").innerHTML = ptErr(ex); $("#pvErr").scrollIntoView({ block: "center" }); } else alert(ex.message); } return false; }
}
$("#ptVault").addEventListener("change", (e) => {
  const t = e.target;
  if (t.matches("#pvAdd [name=origin]")) {
    const f = t.form, svc = t.value === "service";
    f.cost_each.classList.toggle("hidden", t.value !== "buy");
    f.cost_each.required = t.value === "buy";
    f.client.classList.toggle("hidden", !svc); f.client.required = svc;
    f.rune_value.classList.toggle("hidden", !svc);
    $("#pvSvcHint").classList.toggle("hidden", !svc);
    if (svc) pvSvcHint(f);
  }
  if (t.dataset.pvPrice !== undefined) {
    pvCall("POST", "/prices", { item: t.dataset.pvPrice, price: t.value === "" ? null : +t.value });
  }
  if (t.dataset.pvOrigin) {
    const i = PT.vault.items.find((x) => x.id === +t.dataset.pvOrigin);
    const body = { action: "origin", origin: t.value };
    if (t.value === "buy") {
      const ans = prompt(`Quanto foi pago por cada ${i.item}? (gp)`, i.cost_each ?? "");
      if (ans === null || !ans.trim()) { t.value = i.origin; return; }
      body.cost_each = Math.max(0, Math.floor(+ans.replace(/\D/g, "")));
    }
    if (t.value === "service") {
      const who = prompt(`Quem é o serviçado (recebe a metade da ${i.item})?`, i.client || "");
      if (!who || !who.trim()) { t.value = i.origin; return; }
      const val = prompt(`Quanto vale a ${i.item}? (gp; vazio = preço do cofre)`, i.price ?? "");
      if (val === null) { t.value = i.origin; return; }
      body.client = who.trim();
      if (val.trim()) body.rune_value = Math.max(0, Math.floor(+val.replace(/\D/g, "")));
    }
    pvCall("POST", `/items/${i.id}`, body);
  }
  const box = t.closest(".vault-sell");
  if (box) ptSalePreview(box);
});
$("#ptVault").addEventListener("input", (e) => { const sf = e.target.closest("#pvAdd"); if (sf && sf.origin.value === "service") pvSvcHint(sf); const box = e.target.closest(".vault-sell"); if (box) ptSalePreview(box); });
$("#ptVault").addEventListener("submit", (e) => {
  if (e.target.id !== "pvAdd") return;
  e.preventDefault();
  const f = e.target, body = { item: f.item.value.trim(), qty: +f.qty.value || 1, origin: f.origin.value, holder: f.holder.value };
  if (f.origin.value === "buy" && f.cost_each.value !== "") body.cost_each = +f.cost_each.value;
  if (f.origin.value === "service") { body.client = f.client.value.trim(); if (f.rune_value.value !== "") body.rune_value = +f.rune_value.value; }
  if (f.obtained_on.value) body.obtained_on = f.obtained_on.value;
  if (f.note.value.trim()) body.note = f.note.value.trim();
  pvCall("POST", "/items", body);
});
$("#ptVault").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  const ds = b.dataset;
  if (b.id === "ptBack") { e.preventDefault(); return goBack(); }
  if (ds.pvSell || ds.pvCraftSell) {
    const box = $(`[${ds.pvSell ? "data-pv-sellbox" : "data-pv-craftbox"}="${ds.pvSell || ds.pvCraftSell}"]`);
    box.classList.toggle("hidden"); box.querySelector("[data-pv-total]").focus(); return;
  }
  if (ds.pvSellOk) {
    const box = b.closest(".vault-sell"), total = +box.querySelector("[data-pv-total]").value;
    if (!(total > 0)) { box.querySelector("[data-pv-total]").focus(); return; }
    const fee = box.querySelector("[data-pv-fee]").checked, seller = box.querySelector("[data-pv-seller]").value;
    if (box.hasAttribute("data-pv-sellbox")) return pvCall("POST", `/items/${ds.pvSellOk}`, { action: "sell", sold_total: total, market_fee: fee, seller });
    return pvCall("POST", `/crafts/${ds.pvSellOk}`, { sold_total: total, market_fee: fee, seller });
  }
  if (ds.pvStock) return pvCall("POST", `/items/${ds.pvStock}`, { action: "stock" });
  if (ds.pvDel) { if (confirm("Apagar este item do cofre?")) pvCall("DELETE", `/items/${ds.pvDel}`); return; }
  if (ds.pvCraftUnsell) { const c = PT.vault.crafts.find((x) => x.id === +ds.pvCraftUnsell); return pvCall("POST", `/crafts/${c.id}`, { result: c.result }); }
  if (ds.pvCraftDel) { if (confirm("Desfazer o craft? Os itens usados voltam para o estoque.")) pvCall("DELETE", `/crafts/${ds.pvCraftDel}`); return; }
  if (ds.pvPaid) {
    const [kind, id] = ds.pvPaid.split(":");
    return pvCall("POST", "/paid", { kind, id: +id, payer: ds.payer, receiver: ds.receiver, paid: true });
  }
  if (ds.pvBuy !== undefined) {
    const f = $("#pvAdd");
    f.origin.value = "buy"; f.origin.dispatchEvent(new Event("change", { bubbles: true }));
    f.item.value = (PT.vault.craft_set.missing[0]) || ""; f.item.focus();
    f.scrollIntoView({ behavior: "smooth", block: "center" });
    $("#pvErr").innerHTML = `<span class="muted">${esc("Escolha a runa, quanto foi pago e quem comprou. Ela entra no estoque com a sacolinha vermelha.")}</span>`;
    return;
  }
  if (ds.pvCraft !== undefined) return openPartyCraft();
});
/** Dica do service enquanto digita: metade do valor da runa ÷ titulares. */
function pvSvcHint(f) {
  const v = PT.vault, item = f.item.value.trim().toLowerCase();
  const price = +f.rune_value.value || (v.stock.find((s) => s.item.toLowerCase() === item) || {}).price || 0, n = Math.max(1, v.mains.length);
  $("#pvSvcHint").innerHTML = price ? esc(`Runa de ${kk(price)} → metade ${kk(Math.floor(price / 2))} ÷ ${n} titulares = ${gp(Math.floor(Math.floor(price / 2) / n))} de cada um para o serviçado.`)
    : esc("Informe o valor da runa (ou coloque o preço dela no cofre). A party paga a metade ao serviçado, dividida entre os titulares.");
}
/** 🔨 Craftar: escolher uma unidade de cada item (com a sacolinha), o item que saiu e quem ficou com ele.
    Mostra a faixa de preço na hora; o valor de venda só é pedido quando vender. */
function partyCraftRange() {
  const v = PT.vault, cs = v.craft_set;
  let lo = 0, hi = 0;
  const parts = cs.items.map((x) => {
    const id = +($(`[data-pc-pick="${CSS.escape(x)}"]`) || {}).value;
    const i = v.items.find((u) => u.id === id);
    if (!i) return null;
    const price = (v.stock.find((s) => s.item === x) || {}).price || 0;
    const fixed = i.origin === "buy" || (i.origin === "service" && i.cost_each != null);
    const a = fixed ? i.cost_each || 0 : 0, b = fixed ? i.cost_each || 0 : price;
    lo += a; hi += b;
    return `${bag(i.origin)} ${esc(`${x.replace(" Crypt Rune", "")}: ${fixed ? kk(a) : `0 a ${kk(b)}`}`)}`;
  });
  $("#pcSum").innerHTML = `Preço aproximado do item craftado: <b class="pv-range">${esc(range(lo, hi))}</b>
    <div class="muted" style="font-size:13px">${parts.filter(Boolean).join(" · ")}</div>
    <div class="hint">Drop vale entre 0 e o preço médio do cofre; compra vale o que foi pago e service vale a metade paga ao serviçado.</div>`;
}
function openPartyCraft() {
  const v = PT.vault, cs = v.craft_set;
  const rows = cs.items.map((x) => {
    const units = v.items.filter((i) => i.status === "stock" && i.item === x);
    return `<div class="cm-row"><b>${esc(x)}</b><select data-pc-pick="${esc(x)}" aria-label="${esc(x)}">${units.map((i, n) => `<option value="${i.id}"${n === 0 ? " selected" : ""}>${esc(`${i.origin === "drop" ? "🟡" : i.origin === "service" ? "🟢" : "🔴"} ${ORIGIN_TXT[i.origin]}${i.cost_each != null ? ` ${kk(i.cost_each)}` : ""}${i.client ? ` (${i.client})` : ""} · ${i.code} · ${dayLabel(i.obtained_on)} · ${i.holder}${i.qty > 1 ? ` (${i.qty}x)` : ""}`)}</option>`).join("")}</select></div>`;
  }).join("");
  openModal(`<h3>${esc(`🔨 Craftar: ${cs.label}`)}</h3>
    <p class="hint" style="margin-top:0">${esc(`Uma de cada vira 1 arma no ${cs.npc}. Escolha quais itens do cofre vão ser usados.`)}</p>
    <div id="pcRows">${rows}</div>
    <label class="vault-label">Qual item saiu?<select id="pcResult"><option value="">— ainda não sei —</option>${cs.results.map((r) => `<option>${esc(r)}</option>`).join("")}</select></label>
    <label class="vault-label">Quem ficou com o item?<select id="pcHolder">${holderOpts(v, myDefault(v))}</select></label>
    <div class="pv-craft-sum" id="pcSum"></div>
    <div class="actions"><button class="btn" type="button" id="pcOk">Confirmar craft</button><button class="btn2" data-close-modal type="button">Cancelar</button></div>
    <div class="err" id="pcErr"></div>`);
  partyCraftRange();
}
$("#modal").addEventListener("change", (e) => { if (e.target.closest("[data-pc-pick]")) partyCraftRange(); });
$("#modal").addEventListener("click", async (e) => {
  const ok = e.target.closest("#pcOk");
  if (!ok) return;
  ok.disabled = true;
  const ids = [...document.querySelectorAll("[data-pc-pick]")].map((s) => +s.value);
  try {
    PT.vault = await api("POST", `/api/parties/${PT.vault.party.id}/vault/crafts`, {
      set: PT.vault.craft_set.key, item_ids: ids, result: $("#pcResult").value || null, holder: $("#pcHolder").value });
    closeModal(); renderPartyVault();
  } catch (ex) { ok.disabled = false; if (ex.status !== 401) $("#pcErr").innerHTML = ptErr(ex); }
});

function fromHuntsBlock(list) {
  if (!list.length) return "";
  return `<h2>Bosses nas suas hunts (${list.length})</h2>
    <p class="hint" style="margin-top:-4px">Sessões do 📈 Hunt Session Stacker em que apareceu um boss. O loot do boss é estimado: itens da
      tabela dele que as outras criaturas mortas na sessão não dropam (moedas ficam de fora).</p>
    ${list.map((x) => `<details class="card"><summary>
      <div class="row"><b>${when(x.started_at)}</b><span class="gold">${x.value ? "≈ " + kk(x.value) + " gp" : "sem item exclusivo"}</span></div>
      <div style="margin-top:4px">${bossChips(x.bosses)}</div></summary>
      ${x.items.length ? itemList(x.items, 999) : `<p class="muted">Nenhum item exclusivo do boss nessa sessão.</p>`}</details>`).join("")}`;
}
function rareBlock(list) {
  if (!list.length) return "";
  return `<h2>💎 Drops raros (${list.length})</h2><div class="card">
    ${list.map((d) => `<div class="row" data-item="${esc(d.key)}" style="padding:6px 0; border-bottom:1px solid var(--line); cursor:pointer">
      <span style="display:inline-flex; align-items:center; gap:8px">${itemImg((S.prices[d.key] || {}).name || d.key, 32)}
        <span><b>${d.count > 1 ? d.count + "x " : ""}${esc((S.prices[d.key] || {}).name || d.key)}</b>
        <span class="muted" style="font-size:13px"><br>${esc(d.boss)} · ${esc(dayLabel(d.started_at.slice(0, 10)))}${d.rarity ? " · " + esc(RARITY_PT[d.rarity] || d.rarity) : ""}${d.source === "hunt" ? " · numa hunt do Stacker" : ""}</span></span></span>
      <span class="gold">${d.value ? kk(d.value) : "sem preço"}</span></div>`).join("")}
    <div class="hint">Conta como raro o item "very rare" ou "extremely rare" na TibiaWiki, ou item do boss que vale 500 mil gp ou mais.</div></div>`;
}
function noNpcBlock(d) {
  if (!d.no_npc.length) return "";
  const rows = d.no_npc.map((k) => {
    const p = S.prices[k] || { name: k };
    return `<div style="padding:8px 0; border-bottom:1px solid var(--line)">
      <div class="row"><span style="display:inline-flex; align-items:center; gap:8px">${itemImg(p.name, 32)}<b>${esc(p.name)}</b></span>
        <span class="${p.unit_price ? "muted" : "neg"}" style="font-size:13px">${p.avg_price ? "média " + kk(p.avg_price) + (p.avg_count ? ` (${p.avg_count})` : "") : "sem preço"}</span></div>
      <form class="price-form row" data-price-item="${esc(k)}" style="margin-top:6px">
        <input type="number" min="0" step="1" inputmode="numeric" placeholder="Seu preço (gp)" value="${p.my_price ?? ""}" style="padding:8px 10px" aria-label="Seu preço para ${esc(p.name)}">
        <button class="btn2" type="submit">Salvar</button></form></div>`;
  }).join("");
  const open = d.unpriced > 0 ? " open" : "";
  return `<details class="card"${open}><summary class="row"><b>💰 Itens sem NPC comprador</b>
      <span class="${d.unpriced ? "neg" : "muted"}">${d.unpriced ? d.unpriced + " sem preço" : d.no_npc.length + (d.no_npc.length === 1 ? " item" : " itens")} ▾</span></summary>
    <p class="hint">Nenhum NPC compra estes itens, então o lucro de bosses usa a média do preço que os jogadores informam.
      ${d.unpriced ? "Itens sem preço contam como 0 gp: informe quanto você vende para o lucro ficar certo." : "Ajuste o seu preço quando quiser."}</p>${rows}</details>`;
}
async function loadBoss(opts = {}) {
  const el = $("#bossResult");
  if (!opts.quiet) el.innerHTML = skeleton("stack");
  let d;
  try { d = await api("GET", `/api/bosses/${encodeURIComponent(S.nick)}`); }
  catch (err) {
    if (err.status === 401) return;
    el.innerHTML = `<div class="banner bad"><b>${esc(err.message)}</b>${err.hint ? `<div class="hint">${esc(err.hint)}</div>` : ""}</div>`;
    $("#bossForm").classList.toggle("hidden", err.status === 403);
    return;
  }
  $("#bossForm").classList.remove("hidden");
  S.prices = { ...S.prices, ...(d.prices || {}) };
  S.boss = d;
  renderBoss();
  return d;
}
/** 0.22.2: a mesma tela, de dois jeitos. Solo: as suas sessões de boss. Party: os lootsplits de boss da PT. */
function renderBoss() {
  const d = S.boss, el = $("#bossResult");
  if (!d || S.page !== "boss") return;
  const t = d.totals, n = (v, suffix = "") => `<span data-count="${v}" data-suffix="${suffix}">${fmt(v)}${suffix}</span>`;
  if (S.mode === "party") {
    const sessions = d.sessions.filter((s) => s.mode === "party");
    if (!d.hunts.length && !sessions.length) {
      el.innerHTML = `<div class="card"><b>👑 Nenhum lootsplit de boss ainda</b>
        <p class="muted">Depois da luta, o líder abre o Party Hunt Analyser no Tibia, copia e cola aqui. O lootsplit aparece para todos da PT,
          e as sessões que cada um juntar no mesmo horário se ligam sozinhas.</p></div>`;
      return;
    }
    el.innerHTML = `<div class="card">
        <div class="muted">Sua parte nos lootsplits de boss · ${fmt(t.parties)} ${t.parties === 1 ? "lootsplit" : "lootsplits"}</div>
        <div class="big ${t.party_profit >= 0 ? "gold" : "neg"}">${n(t.party_profit, " gp")}</div></div>
      ${rotationsBlock(d.rotations, "party")}
      ${d.hunts.length ? `<h2>Lootsplits de bosses (${d.hunts.length})</h2>${d.hunts.map(bossHuntItem).join("")}` : ""}
      ${sessions.length ? `<h2>Suas sessões de boss em party (${sessions.length})</h2>${sessions.map(bossSessionItem).join("")}` : ""}`;
    countUp(el);
    const names = [...new Set(d.hunts.flatMap((h) => h.players.map((p) => p.name)))];
    if (names.length) ensureVocations(names).then((c) => { if (c && S.page === "boss") paintVocations(el); });
    return;
  }
  const solo = d.sessions.filter((s) => s.mode !== "party");
  if (!solo.length && !d.from_hunts.length) {
    el.innerHTML = `<div class="card"><b>👑 Nenhuma sessão de boss solo ainda</b>
      <p class="muted">Depois de matar um boss sozinho, abra o Hunt Analyser no Tibia, copie e cole aqui. A sessão fica só sua.</p></div>`;
    return;
  }
  const bal = solo.reduce((a, s) => a + s.balance, 0), secs = solo.reduce((a, s) => a + s.duration_seconds, 0);
  const kills = solo.reduce((a, s) => a + s.bosses.reduce((b, x) => b + x.count, 0), 0);
  el.innerHTML = `
    <div class="card">
      <div class="muted">Balance das sessões de boss solo · ${fmt(kills)} bosses mortos · ${dur(secs)}</div>
      <div class="big ${bal >= 0 ? "gold" : "neg"}">${n(bal, " gp")}</div>
      <div class="muted">${secs ? fmt(Math.round(bal * 3600 / secs)) + " gp/h · " : ""}${fmt(solo.length)} ${solo.length === 1 ? "sessão" : "sessões"}${t.hunts_value ? ` · bosses nas suas hunts ≈ ${kk(t.hunts_value)} gp` : ""}</div>
    </div>
    ${noNpcBlock(d)}
    ${rotationsBlock(d.rotations, "solo")}
    <h2>Bosses</h2>${bossTable(d.bosses)}
    ${rareBlock(d.rare_drops)}
    ${d.items.length ? `<h2>Itens dos bosses</h2><div class="card">${itemList(d.items)}</div>` : ""}
    ${solo.length ? `<h2>Sessões de boss (${solo.length})</h2>${solo.map(bossSessionItem).join("")}` : ""}
    ${fromHuntsBlock(d.from_hunts)}`;
  countUp(el);
}
function bossBanner(r) {
  const found = r.bosses.length ? `Bosses: ${r.bosses.map((b) => `<b>${esc(b.name)}</b>${b.count > 1 ? " ×" + b.count : ""}`).join(", ")}.`
    : `<span class="neg">Nenhum boss reconhecido nessa sessão.</span> Ela foi guardada mesmo assim; confira se colou a sessão certa.`;
  return `<div class="banner ok">${r.created ? "Sessão de boss salva ✔" : "Essa sessão já estava salva ✔"} ${found}</div>`;
}
$("#bossBtn").addEventListener("click", async () => {
  const raw = $("#bossText").value.trim();
  if (!raw) return;
  const btn = $("#bossBtn"); btn.disabled = true; $("#bossErr").textContent = ""; $("#bossAsk").innerHTML = "";
  const mode = S.btab;
  if (mode === "party") return bossPartySplit(raw).finally(() => { btn.disabled = false; });
  try {
    const r = await api("POST", "/api/bosses/session", { raw_text: raw, nickname: S.nick, mode });
    $("#bossText").value = "";
    S.bossLast = r;
    let ask = bossBanner(r);
    if (r.switched_from) {  // 0.23.0: era do personagem que estava na party de bosses do mesmo horário
      await switchActiveChar(r.saved_as);
      ask += `<div class="banner ok">🔁 ${esc(`Salva em ${r.saved_as}: ele tem um lootsplit de bosses no mesmo horário.`)}</div>`;
    }
    if (r.party) {
      ask += `<div class="banner ok">👥 Juntei com o lootsplit da party (${r.party.players_count} jogadores, ${kk(r.party.profit_each)} para cada) que alguém da PT já tinha enviado.</div>`;
    } else if (mode === "party") {
      ask += `<div class="card" id="bossSplitAsk"><b>Quer fazer o lootsplit da party?</b>
        <p class="muted" style="margin:4px 0 0">Se sim, cole o Party Hunt Analyser: a divisão vai para a aba de bosses de todos da PT.
          Se não, a sessão fica guardada só para você, como solo.</p>
        <div class="row" style="gap:8px; margin-top:10px; justify-content:flex-start">
          <button class="btn" style="width:auto; margin:0; flex:1" data-boss-split="yes">Sim, fazer lootsplit</button>
          <button class="btn2" style="flex:1" data-boss-split="no">Não</button></div></div>`;
    }
    $("#bossAsk").innerHTML = ask;
    celebrateRare(r.rare);
    celebrateRewards(r.rewards);
    await loadBoss({ quiet: true });
  } catch (err) {
    if (err.status === 0) { await queueDraft("/api/bosses/session", { raw_text: raw, nickname: S.nick, mode }, $("#bossErr")); $("#bossText").value = ""; }
    else if (err.status === 403) $("#bossErr").innerHTML = `${esc(err.message)}<div class="hint">${esc(err.hint || "")}</div>`;
    else if (err.status !== 401) $("#bossErr").textContent = err.message;
  } finally { btn.disabled = false; }
});
/** 0.22.2: Party → o Party Hunt Analyser do boss vira lootsplit na hora, igual ao 💰 Lootsplit. */
async function bossPartySplit(raw) {
  try {
    const r = await api("POST", "/api/bosses/lootsplit", { raw_text: raw, nickname: S.nick, session_id: null });
    r.hunt.kind = "boss";
    $("#bossText").value = "";
    if (r.switched_from) await switchActiveChar(r.saved_as);  // 0.23.0
    $("#bossAsk").innerHTML = `<div class="banner ok"><div>${r.for_owner ? esc(`Salvo para ${r.saved_as} (o dono do personagem), marcado como jogado por você ✔`)
        : r.created ? "Lootsplit de boss salvo ✔ Já aparece para todos da PT." : "Esse lootsplit já estava salvo ✔"}</div>
        ${r.linked > 1 ? `<div class="hint">${r.linked} sessões da PT foram juntadas.</div>` : ""}
        ${r.switched_from ? `<div class="hint">🔁 ${esc(`Salvo em ${r.saved_as}, que estava na PT (você estava em ${r.switched_from}).`)}</div>` : ""}</div>
      ${quickTransfers(r.hunt)}${partyMessages(r.hunt)}
      <details class="card"><summary class="link">＋ Juntar o meu Hunt Analyser desta luta (opcional) ▾</summary>
        <p class="muted" style="margin:6px 0 0">Assim os bosses, itens e criaturas da luta entram no seu histórico de bosses.</p>
        <textarea id="bossMineText" spellcheck="false" style="margin-top:6px" placeholder="Session data: From ... to ...&#10;Killed Monsters:&#10;  1x ..."></textarea>
        <button class="btn2 paste-btn" data-paste-into="bossMineText" data-paste-err="bossMineErr" type="button">📋 Colar da área de transferência</button>
        <button class="btn" id="bossMineBtn" type="button">Juntar minha sessão</button><div class="err" id="bossMineErr"></div></details>
      <h2>Detalhes</h2>${huntCard(r.hunt, S.nick, "Lootsplit do boss")}`;
    countUp($("#bossAsk")); paintVocations($("#bossAsk"));
    $("#bossAsk").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
    celebrateRewards(r.rewards);
    loadBoss({ quiet: true });
  } catch (err) {
    if (err.status === 0) { await queueDraft("/api/bosses/lootsplit", { raw_text: raw, nickname: S.nick }, $("#bossErr")); $("#bossText").value = ""; }
    else if (err.status === 403) $("#bossErr").innerHTML = `${esc(err.message)}<div class="hint">${esc(err.hint || "")}</div>`;
    else if (err.status !== 401) $("#bossErr").textContent = err.message;
  }
}
document.addEventListener("click", async (e) => {
  if (!e.target.closest("#bossMineBtn")) return;
  const raw = $("#bossMineText").value.trim(), btn = $("#bossMineBtn");
  if (!raw) { $("#bossMineErr").textContent = "Cole o Hunt Analyser primeiro."; return; }
  btn.disabled = true; $("#bossMineErr").textContent = "";
  try {
    const r = await api("POST", "/api/bosses/session", { raw_text: raw, nickname: S.nick, mode: "party" });
    btn.closest("details").outerHTML = bossBanner(r) + (r.party ? `<div class="banner ok">👥 Ligada ao lootsplit da party ✔</div>` : "");
    celebrateRare(r.rare);
    loadBoss({ quiet: true });
  } catch (err) { btn.disabled = false; if (err.status !== 401) $("#bossMineErr").textContent = err.message; }
});
document.addEventListener("click", async (e) => {
  const a = e.target.closest("[data-boss-split]");
  if (a) {
    const box = $("#bossSplitAsk");
    if (a.dataset.bossSplit === "no") { box.outerHTML = `<div class="banner ok">Guardada só para você, sem lootsplit.</div>`; return; }
    box.innerHTML = `<label class="muted" for="bossPartyText"><b>Cole o Party Hunt Analyser</b> da mesma luta</label>
      <textarea id="bossPartyText" spellcheck="false" style="margin-top:6px" placeholder="Session data: From ... to ...&#10;Loot Type: Leader&#10;..."></textarea>
      <button class="btn2 paste-btn" data-paste-into="bossPartyText" data-paste-err="bossPartyErr" type="button">📋 Colar da área de transferência</button>
      <button class="btn" id="bossSplitBtn">Fazer lootsplit</button><div class="err" id="bossPartyErr"></div>`;
    $("#bossPartyText").focus();
    return;
  }
  if (e.target.closest("#bossSplitBtn")) {
    const raw = $("#bossPartyText").value.trim();
    if (!raw) return;
    const btn = $("#bossSplitBtn"); btn.disabled = true; $("#bossPartyErr").textContent = "";
    try {
      const r = await api("POST", "/api/bosses/lootsplit", { raw_text: raw, nickname: S.nick, session_id: (S.bossLast || {}).session_id || null });
      r.hunt.kind = "boss";
      $("#bossSplitAsk").outerHTML = `<div class="banner ok"><div>${r.created ? "Lootsplit de boss enviado ✔ Já aparece na aba de bosses de todos da PT." : "Esse lootsplit já estava salvo ✔"}</div>
          ${r.linked > 1 ? `<div class="hint">${r.linked} sessões da PT foram juntadas.</div>` : ""}</div>` + huntCard(r.hunt, S.nick, "Lootsplit do boss");
      countUp($("#bossAsk")); paintVocations($("#bossAsk"));
      celebrateRewards(r.rewards);
      loadBoss({ quiet: true });
    } catch (err) {
      if (err.status === 0) { await queueDraft("/api/bosses/lootsplit", { raw_text: raw, nickname: S.nick }, $("#bossPartyErr")); return; }
      if (err.status === 403) $("#bossPartyErr").innerHTML = `${esc(err.message)}<div class="hint">${esc(err.hint || "")}</div>`;
      else if (err.status !== 401) $("#bossPartyErr").textContent = err.message;
      btn.disabled = false;
    }
    return;
  }
  const del = e.target.closest("[data-del-boss-session],[data-del-boss-hunt]");
  if (!del) return;
  e.preventDefault();
  const isHunt = !!del.dataset.delBossHunt;
  if (!confirm(isHunt ? "Apagar este lootsplit de boss para todos da PT? As sessões continuam salvas." : "Apagar esta sessão de boss? Isso não pode ser desfeito.")) return;
  del.disabled = true;
  try {
    await api("DELETE", isHunt ? `/api/bosses/hunt/${del.dataset.delBossHunt}` : `/api/bosses/session/${del.dataset.delBossSession}`);
    $("#bossAsk").innerHTML = "";
    loadBoss();
  } catch (err) { if (err.status !== 401) alert(err.message); del.disabled = false; }
});

function npcWhere(b) { return b ? `${esc(b.npc)}${b.city ? " (" + esc(b.city) + ")" : ""} por ${fmt(b.price)} gp cada` : "nenhum NPC compra (veja o preço médio)"; }
function alertsBlock(d) {
  return d.alerts.map((a) => {
    const p = S.prices[a.key] || { name: a.key };
    return `<div class="alert"><b>🔔 Você já tem ${fmt(a.count)}/${fmt(a.target)} ${esc(p.name)}</b>
      <div class="muted">Hora de vender: ${npcWhere(a.best)}.</div>
      ${d.is_owner ? `<button class="btn2" data-sold="${esc(a.key)}" style="margin-top:8px">Vendi — zerar contagem</button>` : ""}</div>`;
  }).join("");
}
const GOAL_LABEL = { day: "Hoje", week: "Esta semana" }, METRIC_LABEL = { xp: "XP", loot: "Loot" };
function goalsBlock(d) {
  if (!d.is_owner && !d.goals.length) return "";
  const bars = d.goals.map((g) => `<div class="goal">
      <div class="row"><span>${GOAL_LABEL[g.period]} · ${METRIC_LABEL[g.metric]}</span>
        <span><b>${kk(g.done)}</b> / ${kk(g.target)}${g.metric === "loot" ? " gp" : ""} <span class="muted">(${g.pct}%)</span></span></div>
      <div class="gbar ${g.pct >= 100 ? "done" : ""}" role="progressbar" aria-valuenow="${g.pct}" aria-valuemin="0" aria-valuemax="100"><div style="width:${g.pct}%"></div></div>
    </div>`).join("");
  const val = (p, m) => (d.goals.find((g) => g.period === p && g.metric === m) || {}).target || "";
  const form = d.is_owner ? `<details style="margin-top:10px"><summary class="link">${d.goals.length ? "Alterar metas" : "Definir metas"} ▾</summary>
      <form id="goalForm" style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:8px">
        ${[["day", "xp"], ["day", "loot"], ["week", "xp"], ["week", "loot"]].map(([p, m]) => `<label class="muted" style="font-size:13px">${GOAL_LABEL[p]} · ${METRIC_LABEL[m]}${m === "loot" ? " (gp)" : ""}
          <input type="number" min="0" inputmode="numeric" data-goal="${p}:${m}" value="${val(p, m)}" placeholder="sem meta" style="padding:8px; margin-top:4px"></label>`).join("")}
        <button class="btn" style="grid-column:1/-1; margin-top:4px">Salvar metas</button>
      </form><div class="hint">Semana conta de segunda a domingo. Loot = valor dos itens pelos preços de NPC.</div></details>` : "";
  return `<h2>🎯 Metas</h2><div class="card">${bars || `<p class="muted" style="margin:0">Nenhuma meta definida.</p>`}${form}</div>`;
}
function forecastBlock(f) {
  if (!f) return "";
  const days = (n) => n == null ? "—" : n < 1 ? "menos de 1 dia" : `~${fmt(Math.round(n))} dia${Math.round(n) === 1 ? "" : "s"}`;
  const exact = f.xp_source === "highscore";
  const pct = Math.max(0, Math.min(100, f.level_pct || 0));
  const rows = (f.table || []).map((r) => `<tr${r.level % 50 === 0 ? ' class="gold"' : ""}>
      <td>${r.level}</td><td class="num">${fmt(r.xp_left)}</td><td class="num">${r.hours ? "~" + fmt(r.hours) + "h" : "—"}</td><td class="num">${days(r.days)}</td></tr>`).join("");
  return `<h2>📈 Previsão de level</h2><div class="card">
    <div class="row"><span>Level <b>${f.level}</b> · ${exact ? `<b>${pct.toFixed(1)}%</b> do level` : `<span class="muted">% do level desconhecido</span>`}</span>
      <span class="muted" style="font-size:13px">${fmt(f.xp_per_day)} XP/dia</span></div>
    ${exact ? `<div class="gbar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><div style="width:${pct}%"></div></div>` : ""}
    <div class="muted" style="font-size:13px; margin-top:6px">XP atual: <b style="color:var(--text)">${fmt(f.xp_now)}</b>${exact ? " (highscore do mundo + sessões enviadas depois)" : " (início do level)"}</div>
    <div class="row" style="margin-top:10px"><span>Próximo level (${f.next_level})</span><b>${days(f.days_next_level)}</b></div>
    <div class="row"><span>Level ${f.mark}</span><b>${days(f.days_mark)}</b></div>
    <details style="margin-top:8px"><summary class="link">Tabela de levels ▾</summary>
      <table class="lvl-table"><thead><tr><th>Level</th><th class="num">XP que falta</th><th class="num">Horas de hunt</th><th class="num">Dias</th></tr></thead><tbody>${rows}</tbody></table>
    </details>
    <div class="hint">XP de cada level pela tabela oficial do tibia.com. Dias = ritmo dos últimos 7 dias; horas = seu XP/h médio.
      ${exact ? "" : "Seu personagem não está no top 1000 de experiência do mundo, então a conta parte do início do level (é o tempo máximo)."}${f.xp_per_day ? "" : " Envie sessões desta semana para calcular os dias."}</div>
  </div>`;
}
function recordsBlock(recs) {
  if (!recs.length) return `<p class="muted">Envie sessões para ver seus recordes.</p>`;
  return recs.map((r) => `<div class="row" style="padding:8px 0; border-top:1px solid var(--line)">
      <span>${esc(r.label)}<br><span class="muted" style="font-size:12px">${when(r.started_at)}${r.place ? " · " + esc(r.place) : ""}</span></span>
      <b class="gold">${r.unit === "tempo" ? dur(r.value) : fmt(r.value) + (r.unit === "XP" ? " XP" : r.unit === "XP/h" ? " XP/h" : " " + r.unit)}</b></div>`).join("")
    + `<div class="hint">Recordes por hora consideram só sessões de 10 minutos ou mais.</div>`;
}
function sellBlock(d) {
  if (!d.sell.length) return `<p class="muted">Nenhum item acumulado ainda.</p>`;
  return `<div class="hint" style="margin:6px 0 4px">Soma dos itens das suas sessões. Você pode ter isso para vender (não sabemos o que você já vendeu: use "Vendi" para zerar).</div>`
    + d.sell.map((it) => {
      const p = S.prices[it.key] || { name: it.key };
      return `<div class="item-row" style="cursor:default; flex-wrap:wrap">
        ${itemImg(p.name)}
        <span class="item-name" data-item="${esc(it.key)}" style="cursor:pointer"><b>${fmt(it.count)}x</b> ${esc(p.name)}${it.reached ? " 🔔" : ""}<br>
          <span class="muted">${it.best ? "Vender: " + npcWhere(it.best) : "sem NPC comprador"}</span></span>
        <span class="item-val">${it.value ? kk(it.value) + " gp" : "—"}</span>
        ${d.is_owner ? `<form class="row" data-sell-form="${esc(it.key)}" style="width:100%; justify-content:flex-end; gap:6px; margin-top:4px">
            <span class="muted" style="font-size:13px">Avisar com</span>
            <input type="number" min="0" inputmode="numeric" value="${it.target || ""}" placeholder="qtd" style="width:80px; padding:6px">
            <button class="btn2" type="submit">Salvar</button>
            ${it.count ? `<button class="btn2" type="button" data-sold="${esc(it.key)}">Vendi</button>` : ""}
          </form>` : ""}
      </div>`;
    }).join("");
}
document.addEventListener("submit", async (e) => {
  if (e.target.id === "goalForm") {
    e.preventDefault();
    try {
      for (const inp of e.target.querySelectorAll("[data-goal]")) {
        const [period, metric] = inp.dataset.goal.split(":");
        await api("POST", `/api/goals/${encodeURIComponent(S.nick)}`, { period, metric, target: inp.value ? parseInt(inp.value, 10) : null });
      }
      loadStack();
    } catch (err) { if (err.status !== 401) alert(err.message); }
  }
  const sf = e.target.closest("[data-sell-form]");
  if (sf) {
    e.preventDefault();
    const v = sf.querySelector("input").value;
    try { await api("POST", `/api/sell/${encodeURIComponent(S.nick)}`, { item: sf.dataset.sellForm, target: v ? parseInt(v, 10) : null }); loadStack(); }
    catch (err) { if (err.status !== 401) alert(err.message); }
  }
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-sold]");
  if (!b) return;
  if (!confirm("Marcar como vendido? A contagem deste item volta a zero (o histórico continua guardado).")) return;
  try { await api("POST", `/api/sell/${encodeURIComponent(S.nick)}/sold`, { item: b.dataset.sold }); loadStack(); }
  catch (err) { if (err.status !== 401) alert(err.message); }
});

/* ---------- seletor de hunt: digita e filtra; pode criar uma nova ---------- */
const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
async function ensurePlaces(force) {
  if (!S.places || force) S.places = await api("GET", "/api/places").catch(() => S.places || []);
  return S.places;
}
function pickerHTML(placeholder = "Digite para procurar a hunt (ex.: dragon)") {
  return `<div class="picker"><input class="pk-in" placeholder="${esc(placeholder)}" autocomplete="off" spellcheck="false"><div class="pk-list hidden"></div></div>`;
}
function initPicker(root, { onPick, value, allowCreate = true, onlyWithData = false } = {}) {
  const input = root.querySelector(".pk-in"), list = root.querySelector(".pk-list");
  let opts = [], hi = 0;
  if (value) { root.dataset.placeId = value.id; input.value = value.name; }
  const render = () => {
    const raw = input.value.trim(), q = norm(raw);
    const base = (S.places || []).filter((p) => !onlyWithData || p.sessions);
    opts = base.filter((p) => !q || norm(p.name).includes(q) || norm(p.city).includes(q))
      .sort((a, b) => ((b.sessions > 0) - (a.sessions > 0)) || (norm(b.name).startsWith(q) - norm(a.name).startsWith(q))
        || (b.sessions - a.sessions) || a.name.localeCompare(b.name))
      .slice(0, 8);
    hi = 0;
    const exact = base.some((p) => norm(p.name) === q);
    let html = opts.map((p, i) => `<div class="pk-opt ${i === hi ? "on" : ""}" data-i="${i}"><b>${esc(p.name)}</b>
      <span class="muted">${esc(p.city || "")}${p.level ? " · lvl " + p.level + "+" : ""}${p.sessions ? " · " + p.sessions + " sessões" : ""}</span></div>`).join("");
    if (allowCreate && raw.length >= 3 && !exact) html += `<div class="pk-opt pk-new" data-new="1">+ Criar hunt "${esc(raw)}"</div>`;
    list.innerHTML = html || `<div class="muted" style="padding:9px 12px">Nenhuma hunt encontrada.</div>`;
    list.classList.remove("hidden");
  };
  const pick = (p) => { root.dataset.placeId = p.id; input.value = p.name; list.classList.add("hidden"); onPick && onPick(p); };
  const choose = async (el) => {
    if (!el) return;
    if (el.dataset.new) {
      try { const p = await api("POST", "/api/places", { name: input.value.trim() }); await ensurePlaces(true); pick(p); }
      catch (err) { if (err.status !== 401) alert(err.message); }
    } else if (el.dataset.i) pick(opts[+el.dataset.i]);
  };
  input.addEventListener("input", () => { delete root.dataset.placeId; render(); });
  input.addEventListener("focus", () => { input.select(); render(); });
  input.addEventListener("blur", () => setTimeout(() => list.classList.add("hidden"), 200));
  input.addEventListener("keydown", (e) => {
    const items = list.querySelectorAll(".pk-opt");
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); hi = Math.max(0, Math.min(items.length - 1, hi + (e.key === "ArrowDown" ? 1 : -1)));
      items.forEach((o, i) => o.classList.toggle("on", i === hi));
    } else if (e.key === "Enter") { e.preventDefault(); choose(items[hi]); }
  });
  list.addEventListener("mousedown", (e) => { e.preventDefault(); choose(e.target.closest(".pk-opt")); });
  return root;
}

/* ---------- página Hunts: ranking por XP/h e gold/h, level médio, comparação ---------- */
S.htab = "xp"; S.cmp = [];
/* 0.22.0: Hunts segue a barra Solo/Party: solo compara com solo, party com party. */
const huntMode = () => (S.mode === "party" ? "party" : "solo");
const xpCell = (v) => (huntMode() === "party" && !v ? "—" : kk(v));  // party: XP/h só existe se alguém juntou a sessão
function paintHuntsHead() {
  const party = huntMode() === "party";
  $("#huntsTitle").textContent = party ? "Hunts em party" : "Hunts solo";
  $("#huntsIntro").textContent = party
    ? "Lootsplits com a hunt escolhida (10 min ou mais). Gold/h = lucro de cada um por hora; XP/h vem dos Hunt Analysers juntados ao lootsplit. Party só é comparada com party."
    : "Sessões do Hunt Session Stacker com a hunt escolhida (10 min ou mais). Gold/h = balance por hora. Solo só é comparada com solo.";
  $("#huntsAllTitle").textContent = party ? "Todas as hunts em party" : "Todas as hunts solo";
}
async function loadMyHunts() {
  const el = $("#huntMine"), party = huntMode() === "party";
  el.innerHTML = skeleton("list");
  let d;
  try { d = await api("GET", `/api/places/mine?mode=${huntMode()}&nick=${encodeURIComponent(S.nick)}`); }
  catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  if (d.mode !== huntMode()) return;  // trocou de aba enquanto carregava
  const title = `<h2>${party ? "👥 Minhas hunts em party" : "🧍 Minhas hunts solo"}</h2>`;
  if (!d.rows.length) {
    el.innerHTML = `${title}<div class="card muted">${party
      ? `Nenhum lootsplit seu com a hunt escolhida ainda. Depois de colar o Party Hunt Analyser em 💰 Lootsplit, toque em "📍 Inserir a hunt".
        <button class="btn2" style="display:block; margin-top:8px" data-page-link="loot" data-hl-go="noplace">📍 Ver as hunts sem local</button>`
      : `Nenhuma sessão sua com a hunt escolhida ainda. Salve pelo 📈 Hunt Session Stacker e diga em qual hunt foi.`}</div>`;
    return;
  }
  el.innerHTML = `${title}<div class="card" style="padding:6px 10px">${d.rows.map((r) => `<div class="rank" data-cmp-add="${r.id}" title="Toque para comparar">
      <span class="pos">📍</span>
      <span><b class="gold">${esc(r.name)}</b><br><span class="muted" style="font-size:13px">${esc(r.city || "")} · ${r.sessions} ${party ? (r.sessions === 1 ? "lootsplit" : "lootsplits") : (r.sessions === 1 ? "sessão" : "sessões")} · ${dur(r.seconds)}${party && r.avg_team ? ` · PT de ${String(r.avg_team).replace(".", ",")} em média` : ""}</span></span>
      <span style="text-align:right"><b>${xpCell(r.xp_per_hour)} XP/h</b><br><span class="${r.gold_per_hour >= 0 ? "pos" : "neg"}" style="font-size:13px">${kk(r.gold_per_hour)} gp/h</span></span>
    </div>`).join("")}</div><div class="hint">Toque numa hunt para comparar com outras ${party ? "hunts em party" : "hunts solo"}.</div>`;
}
async function loadHunts() {
  paintHuntsHead();
  loadMyHunts();
  await ensurePlaces(true);
  const cp = $("#cmpPicker");
  if (!cp.firstElementChild) {
    cp.innerHTML = pickerHTML("Digite o nome de uma hunt para adicionar");
    initPicker(cp.firstElementChild, {
      allowCreate: false,
      onPick: (p) => { if (!S.cmp.some((x) => x.id === p.id) && S.cmp.length < 3) S.cmp.push(p); cp.querySelector(".pk-in").value = ""; renderCompare(); },
    });
  }
  showHuntTab(S.htab);
}
function showHuntTab(tab, opts = {}) {
  if (opts.push && tab !== S.htab) pushNav();
  S.htab = tab;
  updateBack();
  document.querySelectorAll("[data-htab]").forEach((b) => b.classList.toggle("on", b.dataset.htab === tab));
  $("#huntRankingBox").classList.toggle("hidden", tab === "cmp");
  $("#huntCompareBox").classList.toggle("hidden", tab !== "cmp");
  if (tab === "cmp") renderCompare(); else loadRanking();
}
async function loadRanking() {
  const el = $("#huntRanking");
  const qs = new URLSearchParams({ sort: S.htab, mode: huntMode() });
  if ($("#lvlMin").value) qs.set("min_level", $("#lvlMin").value);
  if ($("#lvlMax").value) qs.set("max_level", $("#lvlMax").value);
  if ($("#vocFilter").value) qs.set("vocation", $("#vocFilter").value);
  el.innerHTML = skeleton("list");
  let d;
  try { d = await api("GET", "/api/places/ranking?" + qs); } catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  if (d.mode && d.mode !== huntMode()) return;  // trocou de aba enquanto carregava
  const party = huntMode() === "party";
  if (!d.rows.length) { el.innerHTML = `<p class="muted">Nenhuma hunt ${party ? "em party" : "solo"} com dados ${$("#lvlMin").value || $("#lvlMax").value || $("#vocFilter").value ? "nesse filtro (level ou vocação; só entram jogadores com vocação conhecida)" : "ainda"}. ${party ? "Cole o lootsplit e escolha a hunt." : "Envie sessões pelo Hunt Session Stacker escolhendo a hunt."}</p>`; return; }
  const gold = S.htab === "gold";
  el.innerHTML = `<div class="card" style="padding:6px 10px">${d.rows.map((r, i) => `<div class="rank" data-cmp-add="${r.id}" title="Toque para comparar">
      <span class="pos">#${i + 1}</span>
      <span><b>${esc(r.name)}</b><br><span class="muted" style="font-size:13px">${esc(r.city || "")} · level médio ${r.avg_level ?? "—"}${r.min_level != null && r.min_level !== r.max_level ? ` (${r.min_level}–${r.max_level})` : ""} · ${r.players} jogador${r.players === 1 ? "" : "es"} · ${r.sessions} ${party ? (r.sessions === 1 ? "lootsplit" : "lootsplits") : `sess${r.sessions === 1 ? "ão" : "ões"}`}</span></span>
      <span style="text-align:right"><b class="gold">${gold ? kk(r.gold_per_hour) : xpCell(r.xp_per_hour)}${gold ? " gp/h" : " XP/h"}</b><br>
        <span class="muted" style="font-size:13px">${gold ? xpCell(r.xp_per_hour) + " XP/h" : kk(r.gold_per_hour) + " gp/h"}</span></span>
    </div>`).join("")}</div><div class="hint">Toque numa hunt para colocá-la na comparação.</div>`;
}
function renderCompare() {
  $("#cmpChips").innerHTML = S.cmp.map((p) => `<span class="chip">${esc(p.name)}<button class="x" data-cmp-del="${p.id}" aria-label="Remover">✕</button></span>`).join("")
    || `<span class="muted">Nenhuma hunt escolhida.</span>`;
  const el = $("#cmpResult");
  if (!S.cmp.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<p class="muted">Carregando…</p>`;
  const mode = huntMode(), party = mode === "party";
  api("GET", `/api/places/compare?ids=${S.cmp.map((p) => p.id).join(",")}&nick=${encodeURIComponent(S.nick)}&mode=${mode}`).then((rows) => {
    if (mode !== huntMode()) return;
    const cell = (r, f) => r.stats ? f(r.stats) : "—";
    const mine = (r, f) => r.mine ? f(r.mine) : "—";
    const best = (vals) => Math.max(...vals.filter((v) => typeof v === "number"));
    const xs = rows.map((r) => r.stats ? r.stats.xp_per_hour : null), gs = rows.map((r) => r.stats ? r.stats.gold_per_hour : null);
    const dmgTypes = (d) => d && d.types.length ? d.types.slice(0, 3).map((t) => `${esc(t.name)} <span class="muted">${pctTxt(t.pct)}</span>`).join("<br>") : "—";
    const dmgMobs = (d) => d && d.mobs.length ? d.mobs.slice(0, 3).map((t) => `${esc(t.name)} <span class="muted">${pctTxt(t.pct)}</span>`).join("<br>")
      + (d.other_pct ? `<br><span class="muted">(other) ${pctTxt(d.other_pct)}</span>` : "") : "—";
    const anyMine = rows.some((r) => r.mine), hard = isHardcore();
    // básico: para qualquer hunt
    const basic = [
      ["XP/h (todos)", rows.map((r, i) => cell(r, (s) => `<b class="${xs[i] === best(xs) && rows.length > 1 && s.xp_per_hour ? "gold" : ""}">${xpCell(s.xp_per_hour)}</b>`))],
      [party ? "Gold/h por pessoa (todos)" : "Gold/h (todos)", rows.map((r, i) => cell(r, (s) => `<b class="${gs[i] === best(gs) && rows.length > 1 ? "gold" : ""}">${kk(s.gold_per_hour)}</b>`))],
      ["Level médio", rows.map((r) => cell(r, (s) => `${s.avg_level ?? "—"}${s.min_level != null && s.min_level !== s.max_level ? `<br><span class="muted">${s.min_level}–${s.max_level}</span>` : ""}`))],
      [party ? "Jogadores / lootsplits" : "Jogadores / sessões", rows.map((r) => cell(r, (s) => `${s.players} / ${s.sessions}`))],
      ...(party ? [["Tamanho médio da PT", rows.map((r) => cell(r, (s) => String(s.avg_team).replace(".", ",")))]] : []),
      ["Level recomendado (wiki)", rows.map((r) => r.place.level ? r.place.level + "+" : "—")],
    ];
    // detalhes: só das hunts em que o próprio player caçou
    const rich = anyMine ? [
      [party ? "Seus lootsplits" : "Suas sessões", rows.map((r) => mine(r, (s) => `${s.sessions} · ${dur(s.seconds)}`))],
      ["Seu XP/h", rows.map((r) => mine(r, (s) => `<b>${xpCell(s.xp_per_hour)}</b>`))],
      [party ? "Seu gold/h (sua parte)" : "Seu gold/h", rows.map((r) => mine(r, (s) => `<b>${kk(s.gold_per_hour)}</b>`))],
      ["Criaturas que você mais matou", rows.map((r) => r.top_kills.map((k) => `${esc(k.key)} <span class="muted">${fmt(k.count)}</span>`).join("<br>") || "—")],
      ["Itens que mais renderam para você", rows.map((r) => r.top_items.map((t) => `${esc(t.name)} <span class="muted">${kk(t.value)}</span>`).join("<br>") || "—")],
      ["Seu dano recebido: elemento", rows.map((r) => dmgTypes(r.my_damage))],
      ["Seu dano recebido: criaturas", rows.map((r) => dmgMobs(r.my_damage))],
    ] : [];
    // 🔥 Player Hardcore: Input Analysers públicos daquela hunt
    const pub = hard ? [
      ["Elemento que mais bate (todos)", rows.map((r) => dmgTypes(r.damage))],
      ["Criaturas que mais batem (todos)", rows.map((r) => dmgMobs(r.damage))],
    ] : [];
    const tr = ([label, cells]) => `<tr><td class="muted">${label}</td>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`;
    const sep = (t) => `<tr><td colspan="${rows.length + 1}" style="text-align:left; padding-top:12px"><b>${t}</b></td></tr>`;
    el.innerHTML = `<div class="card table-wrap"><table class="cmp"><tr><th></th>${rows.map((r) => `<th>${esc(r.place.name)}<br><span class="muted">${esc(r.place.city || "")}</span></th>`).join("")}</tr>
      ${basic.map(tr).join("")}
      ${rich.length ? sep(`⭐ Suas hunts (${esc(S.nick)})`) + rich.map(tr).join("") : ""}
      ${pub.length ? sep("🔥 Input Analyser público") + pub.map(tr).join("") : ""}</table></div>
      <div class="hint">${party ? "Comparando só hunts em party." : "Comparando só hunts solo."} Em dourado, a melhor de cada linha.</div>
      <div class="hint">${anyMine ? `Os detalhes (criaturas, itens e dano) aparecem só nas hunts em que ${esc(S.nick)} caçou${party ? " e juntou o Hunt Analyser" : ""}.`
        : `Os detalhes (criaturas, itens e dano) aparecem nas hunts em que ${esc(S.nick)} já caçou. Aqui você vê o básico.`}</div>
      ${hard ? `<div class="hint">🔥 Input Analyser público = % do dano recebido nos Input Analysers que os jogadores compartilharam ali.</div>` : ""}`;
  }).catch((err) => { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; });
}
document.addEventListener("click", (e) => {
  const tab = e.target.closest("[data-htab]");
  if (tab) return showHuntTab(tab.dataset.htab, { push: true });
  const add = e.target.closest("[data-cmp-add]");
  if (add) {
    const p = (S.places || []).find((x) => x.id === +add.dataset.cmpAdd);
    if (p && !S.cmp.some((x) => x.id === p.id)) { if (S.cmp.length >= 3) S.cmp.shift(); S.cmp.push(p); }
    return showHuntTab("cmp", { push: true });
  }
  const del = e.target.closest("[data-cmp-del]");
  if (del) { S.cmp = S.cmp.filter((p) => p.id !== +del.dataset.cmpDel); renderCompare(); }
});
$("#lvlApply").addEventListener("click", loadRanking);
$("#lvlMine").addEventListener("click", () => {
  const lv = (S.char && S.char.level) || 0;
  if (!lv) return;
  $("#lvlMin").value = Math.floor(lv * 0.8); $("#lvlMax").value = Math.ceil(lv * 1.2); loadRanking();
});

/* Janelinha do item: NPC(s) que pagam mais; passando no NPC mostra onde fica e o minimapa. */
function minimap(c) {
  const [x, y, z] = c, T = 256, SC = 2, V = 176;
  const tx = Math.floor(x / T) * T, ty = Math.floor(y / T) * T;
  const ox = V / 2 - (x - (tx - T)) * SC, oy = V / 2 - (y - (ty - T)) * SC;
  let tiles = "";
  for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++)
    tiles += `<img src="${MAP_TILE(tx + i * T, ty + j * T, z)}" alt="" style="left:${(i + 1) * T * SC}px; top:${(j + 1) * T * SC}px; width:${T * SC}px; height:${T * SC}px" data-err="remove">`;
  return `<div class="minimap" style="width:${V}px; height:${V}px"><div style="left:${ox}px; top:${oy}px">${tiles}</div><span class="pin"></span></div>
    <div class="muted" style="margin-top:4px">${x}, ${y}, andar ${z}</div>
    <div class="credit">🗺️ Mapa fornecido por <a href="https://tibiamaps.io/" target="_blank" rel="noopener">TibiaMaps.io</a></div>`;
}
function itemPopover(key) {
  const p = S.prices[key];
  if (!p) return "";
  let body;
  if (p.buyers && p.buyers.length) {
    body = `<div class="muted">Melhor preço de NPC: <b style="color:var(--text)">${fmt(p.npc_price)} gp</b></div>
      ${p.buyers.slice(0, 4).map((b, i) => `<div class="npc" data-npc="${i}">
          <img src="${WIKI_FILE(b.npc)}" alt="" width="40" height="40" style="image-rendering:pixelated" data-err="hide">
          <span><b>${esc(b.npc)}</b><br><span class="muted">${esc(b.city || "")}</span></span></div>
        <div class="npc-where hidden" data-npc-where="${i}">${esc(b.location || "")}${b.coords ? minimap(b.coords) : ""}</div>`).join("")}
      ${p.buyers.length > 4 ? `<div class="muted">+${p.buyers.length - 4} NPCs pagam o mesmo preço.</div>` : ""}
      <div class="hint">Passe o mouse (ou toque) na imagem do NPC para ver onde ele fica.</div>
      ${WIKI_CREDIT}`;
  } else if (p.source === "moeda") {
    body = `<div class="muted">Moeda: vale ${fmt(p.npc_price)} gp.</div>`;
  } else {
    body = `<div class="muted">Nenhum NPC compra este item.</div>
      <div class="muted" style="margin:6px 0">Preço médio dos usuários: <b style="color:var(--text)">${p.avg_price ? fmt(p.avg_price) + " gp" : "—"}</b>${p.avg_count ? ` (${p.avg_count} ${p.avg_count === 1 ? "pessoa" : "pessoas"})` : ""}</div>
      <form class="price-form row" data-price-item="${esc(key)}">
        <input type="number" min="0" step="1" inputmode="numeric" placeholder="Seu preço (gp)" value="${p.my_price ?? ""}" style="padding:8px 10px">
        <button class="btn2" type="submit">Salvar</button>
      </form>
      <div class="hint">Seu preço: ${p.my_price ? fmt(p.my_price) + " gp" : "não informado"}. Ele entra na média de todos.</div>`;
  }
  return `<div class="pop-head">${itemImg(p.name, 32)}<b>${esc(p.name)}</b></div>${body}`;
}
const pop = Object.assign(document.createElement("div"), { id: "pop", className: "pop hidden" });
document.body.appendChild(pop);
let popKey = null, popHideT = null;
function showPop(row) {
  clearTimeout(popHideT);
  const key = row.dataset.item;
  if (popKey !== key) { pop.innerHTML = itemPopover(key); popKey = key; }
  pop.classList.remove("hidden");
  const r = row.getBoundingClientRect(), w = Math.min(300, window.innerWidth - 24);
  pop.style.width = w + "px";
  pop.style.left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12)) + window.scrollX + "px";
  pop.style.top = r.bottom + window.scrollY + 4 + "px";
}
function hidePopSoon() { clearTimeout(popHideT); popHideT = setTimeout(() => { pop.classList.add("hidden"); popKey = null; }, 250); }
document.addEventListener("mouseover", (e) => {
  const row = e.target.closest("[data-item]");
  if (row) return showPop(row);
  if (e.target.closest("#pop")) { clearTimeout(popHideT); const n = e.target.closest("[data-npc]"); if (n) toggleWhere(n.dataset.npc, true); return; }
  if (!pop.classList.contains("hidden") && !pop.contains(document.activeElement)) hidePopSoon();
});
function toggleWhere(i, show) {
  pop.querySelectorAll("[data-npc-where]").forEach((w) => w.classList.toggle("hidden", !(w.dataset.npcWhere === String(i) && show)));
}
document.addEventListener("click", async (e) => {
  const row = e.target.closest("[data-item]");
  if (row) { showPop(row); return; }
  const npc = e.target.closest("#pop [data-npc]");
  if (npc) { toggleWhere(npc.dataset.npc, true); return; }  // toque no celular: mostra o local deste NPC
  if (!e.target.closest("#pop")) { pop.classList.add("hidden"); popKey = null; }
  const per = e.target.closest("[data-period]");
  if (per) { S.period = +per.dataset.period; loadStack(); }
  const lc = e.target.closest("[data-loot-chart]");
  if (lc) { const box = $("#lootChart"); box.classList.toggle("hidden"); lc.textContent = box.classList.contains("hidden") ? "📊 Gráfico" : "📊 Ocultar gráfico"; }
});
document.addEventListener("submit", async (e) => {
  const f = e.target.closest("[data-price-item]");
  if (!f) return;
  e.preventDefault();
  const v = f.querySelector("input").value.trim();
  try {
    S.prices[f.dataset.priceItem] = await api("POST", "/api/items/price", { item: f.dataset.priceItem, price: v === "" ? null : parseInt(v, 10) });
    pop.classList.add("hidden"); popKey = null;
    await (S.page === "boss" ? loadBoss() : loadStack());
  } catch (err) { if (err.status !== 401) alert(err.message); }
});
/* ---------- 0.20.0: salvar primeiro, perguntar depois (Stacker e Lootsplit) ---------- */
// Hardcore: hunt + (party: sessão) + Input Analyser · Comum: hunt (+ party: sessão) · Novato: só salva.
const pctTxt = (p) => Number(p || 0).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + "%";
const INPUT_LOCK_TIP = "Assim que adicionar, não há como editar.";
const PLACE_LOCKED_MSG = "Para alterar novamente entre em contato com o administrador.";
const Flow = { kind: null, id: null, steps: [], banner: "", after: null, compare: null };
const flowBase = () => (Flow.kind === "hunt" ? `/api/hunt/${Flow.id}` : `/api/stacker/session/${Flow.id}`);

function openStackFlow(text = "", autoSave = false) {
  openModal(`<h3>📈 Hunt Analyser</h3>
    <label class="muted" for="flowText">Cole aqui o Hunt Analyser (sessão individual)</label>
    <textarea id="flowText" spellcheck="false" style="margin-top:6px" placeholder="Session data: From ... to ...&#10;Session: 01:30h&#10;Raw XP Gain: ...&#10;XP Gain: ...">${esc(text)}</textarea>
    <button class="btn2 paste-btn" data-paste-into="flowText" data-paste-err="flowErr" type="button">📋 Colar da área de transferência</button>
    <div class="actions"><button class="btn" id="flowSave" type="button">Salvar</button><button class="btn2" data-close-modal type="button">Cancelar</button></div>
    <div class="err" id="flowErr"></div>`);
  if (autoSave && text) $("#flowSave").click(); else setTimeout(() => $("#flowText") && $("#flowText").focus(), 50);
}
$("#stackOpen").addEventListener("click", () => openStackFlow());

/* ---------- 0.30.0: ⏱️ Sessão ao vivo ----------
   O site não lê o jogo: a pessoa cola o Hunt Analyser de tempos em tempos e o site compara o ritmo com a meta
   e com a média dela. Nada é salvo no servidor; a sessão fica só neste aparelho até ela decidir salvar no Stacker. */
const LIVE_REMIND_MIN = 30;
const liveKey = () => "live:" + (S.nick || "");
async function liveLoad() { try { return JSON.parse((await kv.get(liveKey())) || "null"); } catch { return null; } }
async function liveStore(v) { await kv.set(liveKey(), v ? JSON.stringify(v) : null); }
function liveAverage() {
  const ss = ((S.stack && S.stack.sessions) || []).filter((s) => s.xp && s.duration_seconds >= 600 && !s.other_player);
  return ss.length ? Math.round(ss.reduce((a, s) => a + (s.xp * 3600) / s.duration_seconds, 0) / ss.length) : null;
}
async function paintLive() {
  const box = $("#liveBox");
  if (!box) return;
  const live = await liveLoad();
  if (!live) {
    box.innerHTML = `<div class="card"><b>⏱️ Sessão ao vivo</b>
      <p class="muted" style="margin:4px 0 8px">Acompanhe a hunt enquanto joga: cole o Hunt Analyser de tempos em tempos e veja se está no ritmo da sua meta.</p>
      <label class="muted" for="liveGoal">Meta de XP/h (opcional)</label>
      <input id="liveGoal" inputmode="numeric" autocomplete="off" placeholder="800000" style="margin-top:6px">
      <button class="btn2" data-live="start" style="margin-top:10px" type="button">▶ Começar sessão ao vivo</button></div>`;
    return;
  }
  const snaps = live.snaps || [], L = snaps[snaps.length - 1], P = snaps[snaps.length - 2];
  const lines = [];
  let bar = "";
  if (L) {
    const pace = Math.round((L.xp * 3600) / L.secs), avg = liveAverage();
    lines.push(`<div class="big gold" style="font-size:26px;font-weight:800" data-i18n-skip>${fmt(pace)} XP/h</div>`);
    lines.push(`<div class="muted" data-i18n-skip>${esc(tf("Ritmo da hunt até agora, em {0} de sessão.", dur(L.secs)))}</div>`);
    if (P && L.secs > P.secs) {
      const recent = Math.round(((L.xp - P.xp) * 3600) / (L.secs - P.secs));
      lines.push(`<div data-i18n-skip>${esc(tf("Desde a atualização anterior: {0} XP/h.", fmt(recent)))}</div>`);
    }
    if (live.goal) {
      const pct = Math.round((pace / live.goal) * 100);
      bar = `<div class="gbar" style="margin:8px 0"><div style="width:${Math.min(100, pct)}%"></div></div>`;
      lines.push(`<div data-i18n-skip>${esc(tf(pace >= live.goal ? "Meta de {0} XP/h batida 🎯 ({1}%)." : "Meta de {0} XP/h: você está em {1}%.", fmt(live.goal), pct))}</div>`);
    }
    if (avg) lines.push(`<div class="muted" data-i18n-skip>${esc(tf("Sua média nas sessões salvas: {0} XP/h ({1}).", fmt(avg),
      pace >= avg ? tf("{0}% acima", Math.round((pace / avg - 1) * 100)) : tf("{0}% abaixo", Math.round((1 - pace / avg) * 100))))}</div>`);
    const min = Math.floor((Date.now() - new Date(L.at).getTime()) / 60000);
    if (min >= LIVE_REMIND_MIN) lines.push(`<div class="banner" data-i18n-skip>${esc(tf("⏰ Última atualização há {0} min. Cole uma nova para o ritmo ficar certo.", min))}</div>`);
  } else lines.push(`<div class="muted">Cole o Hunt Analyser atual para ver o ritmo.</div>`);
  box.innerHTML = `<div class="card"><div class="row"><b>⏱️ Sessão ao vivo</b><span class="muted" data-i18n-skip>${live.goal ? esc(tf("Meta: {0} XP/h", fmt(live.goal))) : ""}</span></div>
    <div style="margin-top:6px">${lines.join("")}${bar}</div>
    <div class="row" style="justify-content:flex-start; gap:8px; margin-top:8px"><button class="btn2" data-live="paste" type="button">📋 Colar atualização</button>
      <button class="link" data-live="finish" type="button">⏹ Finalizar</button></div>
    <div class="hint">Nada disso é salvo no servidor. Ao finalizar, você escolhe se salva a sessão no Stacker.</div></div>`;
}
setInterval(() => { if (S.page === "stack") paintLive(); }, 60000);

function openLivePaste() {
  openModal(`<h3>⏱️ Atualizar sessão ao vivo</h3>
    <label class="muted" for="liveText">Cole aqui o Hunt Analyser atual</label>
    <textarea id="liveText" spellcheck="false" style="margin-top:6px" placeholder="Session data: From ... to ...&#10;Session: 00:40h&#10;XP Gain: ..."></textarea>
    <button class="btn2 paste-btn" data-paste-into="liveText" data-paste-err="liveErr" type="button">📋 Colar da área de transferência</button>
    <div class="actions"><button class="btn" data-live="snap" type="button">Atualizar</button><button class="btn2" data-close-modal type="button">Cancelar</button></div>
    <div class="err" id="liveErr"></div>`);
  setTimeout(() => $("#liveText") && $("#liveText").focus(), 50);
}
async function liveSnap(btn) {
  const raw = $("#liveText").value.trim(), err = $("#liveErr");
  if (!raw) { err.textContent = I18N.t("Cole o Hunt Analyser primeiro."); return; }
  btn.disabled = true; err.textContent = "";
  try {
    const p = await api("POST", "/api/stacker/preview", { raw_text: raw });
    const xp = p.xp != null ? p.xp : p.raw_xp;
    if (!p.duration_seconds || xp == null) { err.textContent = I18N.t("Não achei o XP nesse texto."); return; }
    const live = (await liveLoad()) || { goal: null, snaps: [] }, last = live.snaps[live.snaps.length - 1];
    if (last && live.started && live.started !== p.started_at) { err.textContent = I18N.t("Essa atualização é de outra hunt. Finalize a sessão ao vivo para começar outra."); return; }
    if (last && p.duration_seconds <= last.secs) { err.textContent = I18N.t("Essa atualização não é mais nova que a anterior."); return; }
    live.started = p.started_at;
    live.snaps.push({ at: new Date().toISOString(), secs: p.duration_seconds, xp });
    live.snaps = live.snaps.slice(-40);
    live.raw = raw.length <= 100000 ? raw : null;
    await liveStore(live);
    closeModal(); paintLive();
  } catch (e) { if (e.status !== 401) err.textContent = e.message; }
  finally { btn.disabled = false; }
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-live]");
  if (!b) return;
  e.preventDefault();
  const act = b.dataset.live;
  if (act === "start") {
    const g = parseInt(($("#liveGoal").value || "").replace(/\D/g, ""), 10);
    await liveStore({ goal: g > 0 ? g : null, snaps: [] });
    await paintLive(); openLivePaste();
  } else if (act === "paste") openLivePaste();
  else if (act === "snap") liveSnap(b);
  else if (act === "finish") {
    const live = await liveLoad();
    await liveStore(null);
    await paintLive();
    if (live && live.raw && confirm(I18N.t("Salvar esta sessão no Stacker?"))) openStackFlow(live.raw);
  }
});

async function saveStackSession() {
  const raw = $("#flowText").value.trim();
  if (!raw) { $("#flowErr").textContent = "Cole o Hunt Analyser primeiro."; return; }
  const btn = $("#flowSave"); btn.disabled = true; $("#flowErr").textContent = "";
  const before = S.stack;
  try {
    const r = await api("POST", "/api/stacker", { raw_text: raw, nickname: S.nick });
    if (r.switched_from) await switchActiveChar(r.saved_as);  // 0.23.0: a sessão era do personagem da PT do mesmo horário
    celebrateRare(r.rare);
    celebrateRewards(r.rewards);
    const after = await loadStack({ quiet: true });
    if (r.created && !r.switched_from) { celebrateProgress(before, after); checkAchievements(); }
    const s = (after && after.sessions.find((x) => x.id === r.session.id)) || r.session;
    // Feedback com número: o jogador vê o que entrou (XP e XP/h) em vez de só "Salvo".
    const resumo = r.created && s && s.xp != null && s.duration_seconds
      ? ` · ${kk(s.xp)} XP em ${dur(s.duration_seconds)} (${kk(Math.round((s.xp * 3600) / s.duration_seconds))} XP/h)` : "";
    startFlow("solo", r.session.id, {
      note: r.switched_from ? `Salva em ${r.saved_as}: ele tem um lootsplit no mesmo horário.` : "",
      banner: r.created ? `Sessão salva ✔${resumo}` : "Essa sessão já estava salva ✔",
      hasPlace: !!(s.place || s.place_id), hasInput: !!s.input,
      after: () => loadStack({ quiet: true }).then(() => {
        $("#stackResult").insertAdjacentHTML("afterbegin", `<div class="banner ok">${r.created ? `Sessão adicionada ✔${esc(resumo)}` : "Essa sessão já estava salva ✔"}</div>${compareBanner(Flow.compare || r.compare)}`);
      }),
    });
  } catch (err) {
    btn.disabled = false;
    if (err.status === 0) { await queueDraft("/api/stacker", { raw_text: raw, nickname: S.nick }, $("#flowErr")); $("#flowText").value = ""; }
    else if (err.status === 403 || err.status === 409) $("#flowErr").innerHTML = `${esc(err.message)}<div class="hint">${esc(err.hint || "")}</div>`;
    else if (err.status !== 401) $("#flowErr").textContent = err.message;
  }
}

/** Perguntas depois de salvar, de acordo com o tipo de player. */
function startFlow(kind, id, { banner = "", note = "", hasPlace = false, hasInput = false, hasSession = false, only = null, chain = null, after = null } = {}) {
  const t = ptype();
  let steps = [];
  if (chain) { steps = [...chain]; only = chain[0]; }  // 0.22.0: sequência guiada, cada passo já aberto
  else if (only) steps = [only];
  else if (t !== "novato") {
    if (!hasPlace) steps.push("place");
    if (kind === "hunt" && !hasSession) steps.push("session");
    if (isHardcore(t) && !hasInput) steps.push("input");
  }
  Object.assign(Flow, { kind, id, steps, banner, note, after, compare: null, direct: !!only, chained: !!chain });
  nextFlowStep();
}
function nextFlowStep() {
  const step = Flow.steps.shift();
  const head = Flow.banner ? `<div class="banner ok"><div>${esc(Flow.banner)}</div>${Flow.note ? `<div class="hint">🔁 ${esc(Flow.note)}</div>` : ""}</div>` : "";
  if (!step && Flow.note) {  // sem perguntas (Player Novato): o aviso da troca de personagem aparece na tela
    const note = Flow.note;
    setTimeout(() => $("#stackResult") && $("#stackResult").insertAdjacentHTML("afterbegin", `<div class="banner ok">🔁 ${esc(note)}</div>`), 600);
  }
  Flow.banner = ""; Flow.note = "";
  if (!step) { closeModal(); if (Flow.after) Flow.after(); return; }
  const skip = `<button class="btn2" data-flow="skip" type="button">Não</button>`;
  // na sequência guiada, "Pular" segue para o próximo passo (o que já foi salvo fica salvo)
  const cancel = Flow.direct && Flow.steps.length ? `<button class="btn2" data-flow="skip" type="button">Pular</button>`
    : Flow.chained ? `<button class="btn2" data-flow="end" type="button">Fechar</button>`
    : `<button class="btn2" data-close-modal type="button">Cancelar</button>`;
  if (step === "place") {
    openModal(`${head}<div class="flow-step"><b>${Flow.direct ? "Em qual hunt foi?" : "Deseja salvar em qual hunt você caçou?"}</b>
      <div id="flowPlaceBox" class="${Flow.direct ? "" : "hidden"}" style="margin-top:8px"></div>
      <div class="row2">${Flow.direct ? `<button class="btn" data-flow="place-save" type="button">Salvar</button>${cancel}`
        : `<button class="btn" data-flow="place-yes" type="button">Sim</button>${skip}`}</div>
      <div class="hint">${Flow.direct ? "" : "Se escolher Não, ela fica salva como \"hunt sem local\" e você diz onde foi quando quiser."}</div>
      <div class="err" id="flowErr"></div></div>`);
    if (Flow.direct) showFlowPicker();
  } else if (step === "session") {
    openModal(`${head}<div class="flow-step"><b>Deseja juntar o seu Hunt Analyser a este lootsplit?</b>
      <p class="muted" style="margin:4px 0 0">Todos da PT veem XP, balance, dano e cura da sua sessão. A quantidade de criaturas e de itens fica só com você.</p>
      ${flowTextBox("Session data: From ... to ...&#10;XP Gain: ...", Flow.direct)}
      <div class="row2">${Flow.direct ? `<button class="btn" data-flow="session-save" type="button">Salvar</button>${cancel}`
        : `<button class="btn" data-flow="text-yes" type="button">Sim</button>${skip}`}</div>
      <div class="err" id="flowErr"></div></div>`);
  } else if (step === "input") {
    openModal(`${head}<div class="flow-step"><b>Deseja compartilhar o Input Analyser?</b>
      <p class="muted" style="margin:4px 0 0">Fica salvo quanto você apanhou, o elemento e as criaturas que mais bateram.
        <b title="${INPUT_LOCK_TIP}">${INPUT_LOCK_TIP}</b></p>
      ${flowTextBox("Received Damage&#10;Total: ...&#10;Max-DPS: ...&#10;Damage Types&#10;...", Flow.direct)}
      <div class="row2">${Flow.direct ? `<button class="btn" data-flow="input-save" type="button">Salvar</button>${cancel}`
        : `<button class="btn" data-flow="text-yes" type="button">Sim</button>${skip}`}</div>
      <div class="err" id="flowErr"></div></div>`);
  }
  Flow.current = step;
}
function flowTextBox(placeholder, open) {
  return `<div id="flowTextBox" class="${open ? "" : "hidden"}" style="margin-top:8px">
    <textarea id="flowStepText" spellcheck="false" placeholder="${placeholder}"></textarea>
    <button class="btn2 paste-btn" data-paste-into="flowStepText" data-paste-err="flowErr" type="button">📋 Colar da área de transferência</button></div>`;
}
async function showFlowPicker() {
  const box = $("#flowPlaceBox");
  box.classList.remove("hidden");
  box.innerHTML = pickerHTML();
  await ensurePlaces();
  const lastId = +(await kv.get("last_place")) || 0;
  initPicker(box.firstElementChild, { value: (S.places || []).find((p) => p.id === lastId) });
  box.querySelector(".pk-in").focus();
}
document.addEventListener("click", async (e) => {
  if (e.target.closest("#flowSave")) return saveStackSession();
  const f = e.target.closest("[data-flow]");
  if (!f) return;
  const act = f.dataset.flow, err = $("#flowErr");
  if (act === "skip") return nextFlowStep();
  if (act === "end") { Flow.steps = []; return nextFlowStep(); }  // fecha a sequência e mostra o que ficou salvo
  if (act === "place-yes") {
    await showFlowPicker();
    f.closest(".row2").innerHTML = `<button class="btn" data-flow="place-save" type="button">Salvar</button><button class="btn2" data-flow="skip" type="button">Não</button>`;
    return;
  }
  if (act === "text-yes") {
    $("#flowTextBox").classList.remove("hidden"); $("#flowStepText").focus();
    f.closest(".row2").innerHTML = `<button class="btn" data-flow="${Flow.current}-save" type="button">Salvar</button><button class="btn2" data-flow="skip" type="button">Não</button>`;
    return;
  }
  f.disabled = true; if (err) err.textContent = "";
  try {
    if (act === "place-save") {
      const placeId = +($("#flowPlaceBox .picker") || {}).dataset?.placeId || 0;
      if (!placeId) { err.textContent = "Escolha a hunt na lista (digite para procurar)."; f.disabled = false; return; }
      const r = await api("POST", `${flowBase()}/place`, { place_id: placeId });
      kv.set("last_place", String(placeId));
      Flow.compare = r.compare || null;
    } else {
      const raw = ($("#flowStepText") || {}).value?.trim();
      if (!raw) { err.textContent = "Cole o texto primeiro."; f.disabled = false; return; }
      if (act === "input-save") await api("POST", `${flowBase()}/input`, Flow.kind === "hunt" ? { raw_text: raw, nickname: S.nick } : { raw_text: raw });
      if (act === "session-save") await api("POST", `${flowBase()}/session`, { raw_text: raw, nickname: S.nick });
    }
    nextFlowStep();
  } catch (ex) {
    f.disabled = false;
    if (ex.status === 401) return;
    if (err) err.innerHTML = `${esc(ex.message)}${ex.hint ? `<div class="hint">${esc(ex.hint)}</div>` : ""}`;
  }
});

/* "hunt sem local", "input vazio" e os botões da PT: abrem só a pergunta daquele item */
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-add]");
  if (!b) return;
  e.preventDefault();
  const [kind, id, step] = b.dataset.add.split(":");
  startFlow(kind, +id, { only: step, after: () => refreshAfterFlow(kind) });
});
function refreshAfterFlow(kind) {
  if (kind === "solo") return loadStack({ quiet: true });
  if (S.page === "home") return loadHome();
  if (S.page === "loot" && S.lastLoot) {
    return api("GET", `/api/hunts/${encodeURIComponent(S.nick)}`).then((d) => {
      const h = d.hunts.find((x) => x.id === S.lastLoot);
      if (h) { S.lootBanner = ""; renderLoot(h); }
    }).catch(() => {});
  }
}

/** Linha "📍 local" + "Input Analyser" de uma sessão / lootsplit. */
function placeTag(kind, x) {
  const owner = x.can_delete;
  if (!x.place) return owner ? `<button class="tagbtn warn" data-add="${kind}:${x.id}:place" title="Toque para dizer em qual hunt foi">📍 hunt sem local</button>`
    : `<span class="muted">📍 hunt sem local</span>`;
  if (!owner) return `<span class="muted">📍 ${esc(x.place.name)}</span>`;
  if (x.place_edits >= 2) return `<span class="muted">📍 ${esc(x.place.name)}</span> <span class="hint" style="margin:0">${PLACE_LOCKED_MSG}</span>`;
  return `<span>📍 ${esc(x.place.name)}</span> <button class="link" style="font-size:13px" data-add="${kind}:${x.id}:place">trocar</button>`;
}
function inputTag(kind, x) {
  if (!canShare() || x.input) return "";
  return `<button class="tagbtn warn" data-add="${kind}:${x.id}:input" title="${INPUT_LOCK_TIP}">🛡️ Input Analyser vazio · ＋ adicionar</button>`;
}
/** Dano recebido (Input Analyser): total, elemento e criatura que mais bateram; detalhes abrindo. */
function inputBlock(i, who = "") {
  if (!i) return "";
  const row = (r) => `<div class="row"><span>${esc(r.name)}</span><span class="muted">${fmt(r.value)} · ${pctTxt(r.pct)}</span></div>`;
  return `<div class="dmg"><b>🛡️ Dano recebido${who ? " · " + esc(who) : ""}</b>
    ${statGrid([["Total", fmt(i.total)], ["Max-DPS", fmt(i.max_dps)],
      ["Elemento que mais bateu", i.top_type ? `${esc(i.top_type.name)} (${pctTxt(i.top_type.pct)})` : "—"],
      ["Criatura que mais bateu", i.top_mob ? `${esc(i.top_mob.name)} (${pctTxt(i.top_mob.pct)})` : "—"]])}
    <details><summary class="link">Tipos de dano e de onde veio ▾</summary>
      <h2>Tipos de dano</h2>${i.types.map(row).join("") || `<p class="muted">—</p>`}
      <h2>De onde veio</h2>${i.sources.map(row).join("") || `<p class="muted">—</p>`}
      <div class="hint">(other) não é criatura: é dano de outras fontes e só entra no total.</div></details></div>`;
}
/** 0.20.0: sessão do mesmo período que não bate com o Party Hunt Analyser (Leader: só supplies; Market: tudo). Sem alarde. */
const DISC_TEXT = {
  "loot": "Houve discrepância no loot em relação ao Party Hunt Analyser.",
  "supplies": "Houve discrepância nos supplies em relação ao Party Hunt Analyser.",
  "balance": "Houve discrepância no balance em relação ao Party Hunt Analyser.",
  "loot,supplies": "Houve discrepância no loot e nos supplies em relação ao Party Hunt Analyser.",
  "loot,balance": "Houve discrepância no loot e no balance em relação ao Party Hunt Analyser.",
  "supplies,balance": "Houve discrepância nos supplies e no balance em relação ao Party Hunt Analyser.",
  "loot,supplies,balance": "Houve discrepância no loot, nos supplies e no balance em relação ao Party Hunt Analyser.",
};
function discrepancyNote(list) {
  const txt = list && list.length ? DISC_TEXT[list.join(",")] : "";
  return txt ? `<div class="hint" style="color:var(--gold)">⚠️ ${txt}</div>` : "";
}
/** O que cada membro da PT compartilhou e os botões para o próprio player juntar o dele. */
function partyShared(h) {
  if (!h.id || !h.in_party) return "";
  const sessions = (h.member_sessions || []).map((s) => `<div class="member-shared"><b>${vdot(s.name)}${esc(s.name)}</b>${s.other_player ? `<span class="who other">${s.played_by ? "🤝 " + esc(s.played_by) : "🤝 outra pessoa"}</span>` : ""}
      <span class="muted" style="font-size:13px"> · Hunt Analyser · ${dur(s.duration_seconds)}</span>
      ${statGrid([["XP", fmt(s.xp)], ["XP/h", fmt(s.xp_h)], ["Balance", fmt(s.balance) + " gp", s.balance >= 0 ? "pos" : "neg"],
        ["Balance/h", fmt(s.balance_h) + " gp"], ["Damage", fmt(s.damage)], ["Healing", fmt(s.healing)]])}
      ${discrepancyNote(s.discrepancy)}
      ${s.own && s.kills && s.kills.length ? `<details><summary class="link">Suas criaturas e itens (só você vê) ▾</summary>
        ${killChips(s.kills)}<div class="chips" style="margin-top:6px">${s.loot.map((l) => `<span class="chip">${fmt(l.count)}x ${esc(l.key)}</span>`).join("")}</div></details>` : ""}</div>`).join("");
  const inputs = (h.inputs || []).map((i) => inputBlock(i, i.name)).join("");
  const me = h.players.find((p) => p.name.toLowerCase() === (S.nick || "").toLowerCase() && isMine(p.name));
  const t = ptype();
  const hasMine = (list) => (list || []).some((x) => x.name.toLowerCase() === (S.nick || "").toLowerCase());
  const btns = me && t !== "novato" ? [
    !hasMine(h.member_sessions) ? `<button class="tagbtn" data-add="hunt:${h.id}:session">＋ Meu Hunt Analyser</button>` : "",
    canShare(t) && !hasMine(h.inputs) ? `<button class="tagbtn" data-add="hunt:${h.id}:input" title="${INPUT_LOCK_TIP}">＋ Meu Input Analyser</button>` : "",
  ].join("") : "";
  if (!sessions && !inputs && !btns) return "";
  return `<h2>📎 Compartilhado pela PT</h2>${sessions}${inputs}${btns ? `<div class="tagline-row">${btns}</div>` : ""}`;
}

/* ---------- gráfico (mostrar/esconder, trocar métrica) e apagar ---------- */
document.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-chart-toggle],[data-metric],[data-del-hunt],[data-del-solo]");
  if (!t) return;
  e.preventDefault();
  if (t.dataset.chartToggle) {
    const box = document.getElementById(t.dataset.chartToggle);
    const opening = box.classList.contains("hidden");
    if (opening && !box.innerHTML) renderChart(t.dataset.chartToggle);
    box.classList.toggle("hidden", !opening);
    t.textContent = opening ? "📊 Ocultar gráfico" : "📊 Gráfico";
    return;
  }
  if (t.dataset.metric) return renderChart(t.dataset.chart, t.dataset.metric);
  const isHunt = !!t.dataset.delHunt;
  if (!confirm(isHunt ? "Apagar esta hunt para todos da PT? Isso não pode ser desfeito." : "Apagar esta sessão do Stacker? Isso não pode ser desfeito.")) return;
  t.disabled = true;
  try {
    if (isHunt) {
      await api("DELETE", `/api/hunt/${t.dataset.delHunt}`);
      if (S.page === "loot") { $("#lootResult").innerHTML = `<div class="banner ok">Hunt apagada.</div>`; loadLootList(); }
      else loadHome();
    } else {
      await api("DELETE", `/api/stacker/session/${t.dataset.delSolo}`);
      loadStack();
    }
  } catch (err) { if (err.status !== 401) alert(err.message); t.disabled = false; }
});

/* ---------- copiar ---------- */
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch {}
  const ta = Object.assign(document.createElement("textarea"), { value: text });
  document.body.appendChild(ta); ta.select();
  const ok = document.execCommand("copy"); ta.remove(); return ok;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-copy]");
  if (!b) return;
  e.preventDefault();
  b.textContent = (await copyText(b.dataset.copy)) ? "Copiado!" : "Copie manualmente";
  setTimeout(() => (b.textContent = "Copiar"), 1500);
});

/* ---------- app desktop: servidor e atualização ---------- */
function setupDesktopExtras() {
  const line = $("#serverLine");
  line.classList.remove("hidden");
  line.innerHTML = `Servidor: <span id="srv">${esc(S.api)}</span> · <button class="link" id="srvEdit" style="font-size:13px">alterar</button>`;
  $("#srvEdit").addEventListener("click", async () => {
    const url = prompt("Endereço do servidor do 4rt3mi5:", S.api);
    if (!url) return;
    S.api = (await window.pywebview.api.set_server(url.trim())).replace(/\/$/, "");
    $("#srv").textContent = S.api;
  });
}
// 0.18.0: a tela nova entra sem fechar o app; o resto instala sozinho quando você fechar.
const UPDATE_EVERY_MS = 30 * 60 * 1000;
async function checkUpdate() {
  const info = await window.pywebview.api.check_update().catch(() => null);
  const box = $("#update");
  if (!info || info.ui === "current") { box.classList.add("hidden"); return; }
  if (info.ui === "ready") {
    box.innerHTML = `<div class="row"><span>Versão <b>${esc(info.version)}</b> pronta. A tela atualiza em 1 segundo, sem fechar o app.</span>
      <button class="copy" id="doUpdate" style="border-color:var(--gold)">Atualizar agora</button></div>`;
    $("#doUpdate").addEventListener("click", async () => {
      const err = await window.pywebview.api.reload_ui().catch((e) => String(e));
      if (err) { box.textContent = "Não foi possível atualizar: " + err; return; }
      try { sessionStorage.setItem("ui-reload", "1"); } catch {}
      location.reload();
    });
  } else {
    box.innerHTML = `<div class="row"><span>Versão <b>${esc(info.version)}</b> disponível. Ela instala sozinha quando você fechar o app.</span>
      <button class="copy" id="doUpdate">Reiniciar agora</button></div>`;
    $("#doUpdate").addEventListener("click", async () => {
      box.innerHTML = "Instalando… o app vai fechar e abrir de novo sozinho.";
      const err = await window.pywebview.api.install_update().catch((e) => String(e));
      if (err) box.textContent = "Não foi possível atualizar: " + err;
    });
  }
  box.classList.remove("hidden");
}

/* ---------- início ---------- */
async function boot() {
  splashShow();
  Embers.start();
  const detected = detectDesktop(1500).then(async (d) => {
    S.desktop = d;
    await Music.load();      // volume/mudo da última vez
    Music.play("anthem");    // a abertura começa com o Anthem, baixinho
    return d;
  });
  let quick = false; // voltou de "Atualizar agora": abertura curta
  try { quick = sessionStorage.getItem("ui-reload") === "1"; sessionStorage.removeItem("ui-reload"); } catch {}
  const [desktop] = await Promise.all([detected, sleep(quick ? 300 : 2600)]);
  S.desktop = desktop;
  await loadSavedLang();
  if (desktop) {
    const cfg = await window.pywebview.api.get_config();
    S.api = cfg.api_base.replace(/\/$/, "");
    S.version = cfg.version;
    setupDesktopExtras();
  } else {
    S.api = "";
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
    fetch("/api/health").then((r) => r.json()).then((d) => (S.version = d.version)).catch(() => {});
  }
  await waitOnline(true);
  // 0.16.0: primeiro a conta (login com senha); a chave vem da conta
  S.acct = await kv.get("acct");
  if (!S.acct) {
    showLogin();
  } else {
    const resume = async () => acctPost("/api/account/resume", { device_token: (await kv.get("token")) || "" });
    let r = await resume();
    while (r.status === 0) { await sleep(2000); await waitOnline(true); r = await resume(); }
    if (r.ok) await enterAccount(r.data);
    else {
      S.acct = null; await kv.set("acct", null);
      showLogin("login");
      $("#loginErr").textContent = MSG_SESSION_ENDED;
    }
  }
  await splashHide();
  startMonitor();
  if (desktop) { checkUpdate(); setInterval(checkUpdate, UPDATE_EVERY_MS); }
}
/* =====================================================================================
   0.10.0 — som, abertura, vocações, comemorações, conquistas, card, colar direto e ícone
   ===================================================================================== */
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const nk = (n) => String(n || "").trim().replace(/\s+/g, " ").toLowerCase();

/* ---------- música (tocada direto do site oficial do Tibia; nunca em loop) ---------- */
const MUSIC_BASE = "https://static.tibia.com/music/";
const TRACKS = {
  anthem: "TIBIA_Anthem.ogg",
  hunts: "TIBIA_17_Special_Boss_Lairs.ogg",
  stack: "TIBIA_14_King_Tibianus_Queen_Eloise_Emperor_Kruzak.ogg",
};
const PAGE_TRACK = { hunts: "hunts", stack: "stack" };
// 0.11.0: o som não é o foco. Barra no máximo = 12% do volume do aparelho; o padrão (25) fica em ~3%.
const MAX_GAIN = 0.12;
// iPhone/iPad ignoram o volume definido pela página (tocaria no volume do aparelho): lá a música fica desligada.
const VOLUME_LOCKED = (() => { try { const a = new Audio(); a.volume = 0.25; return Math.abs(a.volume - 0.25) > 0.01; } catch { return true; } })();
const Music = {
  vol: 25, muted: false, els: {}, ended: new Set(), current: null, blocked: false,
  async load() {
    const v = await kv.get("music_vol"), m = await kv.get("music_muted");
    if (v != null && v !== "" && !isNaN(+v)) this.vol = Math.max(0, Math.min(100, +v));
    this.muted = m === "1";
    this.ui();
  },
  save() { kv.set("music_vol", String(this.vol)); kv.set("music_muted", this.muted ? "1" : "0"); },
  gain() { return this.muted || VOLUME_LOCKED ? 0 : (this.vol / 100) * MAX_GAIN; },
  el(id) {
    if (!this.els[id]) {
      const a = new Audio();
      a.preload = "none"; a.loop = false; a.src = MUSIC_BASE + TRACKS[id];
      a.addEventListener("ended", () => { this.ended.add(id); if (this.current === id) this.current = null; });  // terminou, terminou
      a.addEventListener("error", () => { this.ended.add(id); if (this.current === id) this.current = null; });
      this.els[id] = a;
    }
    return this.els[id];
  },
  play(id) {
    if (this.ended.has(id) || this.current === id) return;
    if (this.current) this.fadeTo(this.els[this.current], 0, true);
    this.current = id;
    this.resume();
  },
  resume() {
    const id = this.current;
    if (!id || VOLUME_LOCKED || this.muted || this.vol === 0 || this.ended.has(id)) return;
    const a = this.el(id);
    clearInterval(a._fade);
    a.volume = 0;
    const p = a.play();
    if (p && p.then) p.then(() => { this.blocked = false; this.fadeTo(a, this.gain()); }).catch(() => { this.blocked = true; });
  },
  stop() { if (this.current) { this.fadeTo(this.els[this.current], 0, true); this.current = null; } },
  fadeTo(a, target, pauseAtEnd) {
    if (!a) return;
    clearInterval(a._fade);
    const from = a.volume, steps = 12;
    let i = 0;
    a._fade = setInterval(() => {
      i++;
      a.volume = Math.max(0, Math.min(1, from + (target - from) * (i / steps)));
      if (i >= steps) { clearInterval(a._fade); if (pauseAtEnd) a.pause(); }
    }, 50);
  },
  /** Hunts e Stacker têm trilha própria; nas outras telas só continua o Anthem da abertura. */
  forPage(page) {
    const t = PAGE_TRACK[page];
    if (t) return this.play(t);
    if (this.current && this.current !== "anthem") this.stop();
  },
  apply() {
    const a = this.current && this.els[this.current];
    if (this.muted || this.vol === 0) { if (a) { clearInterval(a._fade); a.pause(); } }
    else if (a && a.paused) this.resume();
    else if (a) { clearInterval(a._fade); a.volume = this.gain(); }
    this.ui();
  },
  ui() {
    const off = VOLUME_LOCKED || this.muted || this.vol === 0;
    const label = VOLUME_LOCKED ? "Música desligada neste aparelho" : off ? "Ligar a música" : "Silenciar a música";
    $("#sound").classList.toggle("locked", VOLUME_LOCKED);
    const b = $("#soundBtn");
    b.textContent = off ? "🔇" : this.vol < 35 ? "🔈" : this.vol < 70 ? "🔉" : "🔊";
    b.setAttribute("aria-label", label); b.title = label;
    b.setAttribute("aria-pressed", String(off));
    $("#soundVol").value = this.vol;
    $("#sound").classList.toggle("muted", off);
  },
};
$("#soundBtn").addEventListener("click", () => {  // um clique: muda na hora
  if (VOLUME_LOCKED) {
    const sheet = $("#sheet");
    sheet.innerHTML = `<b>🔇 Música desligada neste aparelho</b>
      <div class="muted" style="font-size:14px; margin-top:2px">Aqui o navegador não deixa o site baixar o volume da música,
        então ela ficaria alta demais. No PC e no Android ela toca bem baixinha.</div>
      <div class="actions"><button class="btn2" data-paste-cancel>Entendi</button></div>`;
    sheet.classList.remove("hidden");
    return;
  }
  Music.muted = !(Music.muted || Music.vol === 0);
  if (!Music.muted && Music.vol === 0) Music.vol = 25;
  Music.save(); Music.apply();
});
$("#soundVol").addEventListener("input", (e) => {
  Music.vol = +e.target.value;
  Music.muted = Music.vol === 0;
  Music.save(); Music.apply();
});
// Navegadores só deixam tocar som depois do primeiro toque/tecla: começa a trilha pendente aí.
["pointerdown", "keydown", "touchstart"].forEach((ev) =>
  document.addEventListener(ev, () => { if (Music.blocked) Music.resume(); }, { capture: true, passive: true }));
Music.ui();

/* ---------- abertura: partículas douradas e runa ---------- */
$("#runeMarks").innerHTML = Array.from({ length: 24 }, (_, i) => {
  const a = (i / 24) * Math.PI * 2, c = Math.cos(a), s = Math.sin(a);
  const p = (r) => `${(100 + c * r).toFixed(1)} ${(100 + s * r).toFixed(1)}`;
  const t = (r, d) => `${(100 + c * r - s * d).toFixed(1)} ${(100 + s * r + c * d).toFixed(1)}`;
  return i % 3 === 0 ? `<path d="M${p(86)} L${p(94)} M${p(90)} L${t(92, 3.5)}"/>`
       : i % 3 === 1 ? `<path d="M${t(86, -2.5)} L${t(94, 2.5)} M${t(86, 2.5)} L${t(94, -2.5)}"/>`
       : `<path d="M${p(86)} L${p(94)}"/>`;
}).join("");
const Embers = {
  running: false, raf: 0, parts: [],
  start() {
    const c = $("#embers");
    if (this.running || !c) return;
    this.running = true;
    const ctx = c.getContext("2d"), dpr = Math.min(2, window.devicePixelRatio || 1), still = reduceMotion();
    let w = 0, h = 0;
    const size = () => { w = c.clientWidth; h = c.clientHeight; c.width = w * dpr; c.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); };
    size();
    this.onResize = size; window.addEventListener("resize", size);
    const spawn = (anywhere) => ({ x: Math.random() * w, y: anywhere ? Math.random() * h : h + 8, r: 0.6 + Math.random() * 1.7,
                                   vy: 0.25 + Math.random() * 0.75, vx: (Math.random() - 0.5) * 0.25, ph: Math.random() * 6.28 });
    this.parts = Array.from({ length: still ? 16 : Math.round(Math.min(90, (w * h) / 9000)) }, () => spawn(true));
    const tick = () => {
      if (!this.running) return;
      ctx.clearRect(0, 0, w, h);
      for (const p of this.parts) {
        if (!still) { p.y -= p.vy; p.x += p.vx + Math.sin((p.ph += 0.02)) * 0.15; }
        if (p.y < -8) Object.assign(p, spawn(false));
        const a = Math.max(0, Math.min(1, p.y / (h * 0.35)) * (0.55 + 0.45 * Math.sin(p.ph * 3)));
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 4);
        g.addColorStop(0, `rgba(255,241,193,${a})`); g.addColorStop(0.35, `rgba(242,201,76,${a * 0.6})`); g.addColorStop(1, "rgba(242,201,76,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p.x, p.y, p.r * 4, 0, 6.283); ctx.fill();
      }
      if (!still) this.raf = requestAnimationFrame(tick);
    };
    tick();
  },
  stop() { this.running = false; cancelAnimationFrame(this.raf); window.removeEventListener("resize", this.onResize); },
};

/* ---------- cores por vocação ---------- */
S.voc = {};
const VOC_LABEL = { knight: "Knight", paladin: "Paladin", druid: "Druid", sorcerer: "Sorcerer", monk: "Monk" };
function vocKey(v) {
  v = String(v || "").toLowerCase();
  return v.includes("knight") ? "knight" : v.includes("paladin") ? "paladin" : v.includes("druid") ? "druid"
       : v.includes("sorcerer") ? "sorcerer" : v.includes("monk") ? "monk" : "none";
}
const VOC_HEX = { knight: "#e8705a", paladin: "#4fc39f", druid: "#5aa9f0", sorcerer: "#b382f2", monk: "#f0a04b", none: "#8a93a6" };
// 0.21.0: arte oficial das vocações (Fankit da CipSoft) no círculo do personagem; Monk ainda não tem arte: fica a sigla
const VOC_ART = new Set(["knight", "paladin", "druid", "sorcerer"]);
function paintAvatar(el, name, vocation) {
  const v = vocKey(vocation);
  el.classList.toggle("voc", VOC_ART.has(v));
  el.title = vocation || "";
  el.innerHTML = VOC_ART.has(v) ? `<img src="fk-voc-${v}.png" alt="" data-err="remove">` : esc(initials(name));
}
function vstyle(name) { const v = S.voc[nk(name)]; return v ? `--vc:var(--voc-${vocKey(v)})` : ""; }
function vdot(name) {
  const v = S.voc[nk(name)];
  return `<i class="vdot" data-vn="${esc(nk(name))}" style="${vstyle(name)}" title="${esc(v || "vocação desconhecida")}"></i>`;
}
function vocLegend() {
  return `<div class="voc-legend">${Object.entries(VOC_LABEL).map(([k, t]) => `<span><i class="vdot" style="--vc:var(--voc-${k})"></i>${t}</span>`).join("")}</div>`;
}
/** Busca a vocação de quem ainda não conhecemos. true = descobriu alguma (vale redesenhar). */
async function ensureVocations(names) {
  if (!S.token) return false;  // 0.22.3: sem conta (Lootsplit da tela de entrada) não consulta vocações
  if (S.char && S.nick) S.voc[nk(S.nick)] = S.char.vocation;
  const want = new Map();
  names.forEach((n) => { if (!(nk(n) in S.voc)) want.set(nk(n), n); });
  if (!want.size) return false;
  const list = [...want.values()].slice(0, 20);
  list.forEach((n) => (S.voc[nk(n)] = null));  // marca como "buscando" para não pedir duas vezes
  try {
    const r = await api("GET", "/api/vocations?names=" + encodeURIComponent(list.join(",")));
    let changed = false;
    for (const [n, v] of Object.entries(r)) if (v) { S.voc[nk(n)] = v; changed = true; }
    return changed;
  } catch { return false; }
}
function paintVocations(root) {
  root.querySelectorAll("[data-vn]").forEach((e) => {
    const v = S.voc[e.dataset.vn];
    if (v) { e.style.setProperty("--vc", `var(--voc-${vocKey(v)})`); e.title = v; }
  });
}

/* ---------- números que contam até o valor ---------- */
function countUp(root) {
  if (reduceMotion()) return;
  root.querySelectorAll("[data-count]").forEach((el) => {
    const target = Number(el.dataset.count) || 0, suf = el.dataset.suffix || "";
    if (!target) return;
    const t0 = performance.now(), D = 950;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / D), e = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(Math.round(target * e)) + suf;
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

/* ---------- carregamento com a forma do conteúdo ---------- */
function skeleton(kind) {
  const lines = (n) => Array.from({ length: n }, (_, i) => `<div class="sk sk-line" style="width:${[70, 92, 55, 80][i % 4]}%"></div>`).join("");
  const card = (n, big) => `<div class="card">${lines(1)}${big ? `<div class="sk sk-big"></div>` : ""}${lines(n)}</div>`;
  if (kind === "list") return `<div aria-busy="true" aria-label="Carregando">${card(2)}${card(2)}${card(2)}${card(2)}</div>`;
  const stats = `<div class="stats">${Array.from({ length: kind === "home" ? 6 : 4 }, () => `<div class="sk sk-stat"></div>`).join("")}</div>`;
  return `<div aria-busy="true" aria-label="Carregando">${card(2, true)}<div class="sk sk-line" style="width:120px; margin:26px 0 12px"></div>${stats}<div style="height:12px"></div>${card(3)}${card(3)}</div>`;
}

/* ---------- tela que convida a usar ---------- */
const MARK_SVG = `<svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" aria-hidden="true">
  <circle cx="50" cy="50" r="33"/><path d="M22 78 L70 30"/><path d="M80 20 L60 27 L73 40 Z" fill="currentColor" stroke-linejoin="round"/>
  <path d="M25 75 h-8 M25 75 v8 M31 69 h-8 M31 69 v8" stroke-width="3.5"/></svg>`;
function emptyState(kind) {
  if (kind === "home") return `<div class="card empty">${MARK_SVG}
    <h3>Sua primeira hunt começa aqui</h3>
    <p class="muted" style="margin:0">Divida o loot da PT em segundos, guarde cada hunt e veja quem mais bateu e curou.</p>
    <ol><li>No Tibia, abra o <b>Party Hunt Analyser</b> e clique em <b>Copy to clipboard</b>.</li>
      <li>Volte aqui e aperte <b>Ctrl+V</b> em qualquer tela (no celular, toque em <b>📋 Colar</b>).</li>
      <li>Pronto: a divisão aparece e fica salva para toda a PT.</li></ol>
    <button class="btn" data-page-link="loot">💰 Dividir minha primeira hunt</button>
    <div class="hint" style="margin-top:10px">Caça sozinho? Use o <button class="link" data-page-link="stack">📈 Hunt Session Stacker</button>.</div></div>`;
  return `<div class="card empty">${MARK_SVG}
    <h3>Comece seu histórico de caçadas</h3>
    <p class="muted" style="margin:0">Cada sessão vira XP/h, lucro real, recordes, metas, lista de venda e ranking das hunts.</p>
    <ol><li>No Tibia, abra o <b>Hunt Analyser</b> e clique em <b>Copy to clipboard</b>.</li>
      <li>Toque em ＋ Colar Hunt Analyser e em Salvar (ou aperte Ctrl+V em qualquer tela).</li>
      <li>Diga em qual hunt foi agora ou depois, tocando em "hunt sem local".</li></ol>
    <button class="btn" data-open-stack>📋 Colar minha primeira sessão</button></div>`;
}
document.addEventListener("keydown", (e) => {  // cartões clicáveis (role=button) também abrem com Enter/Espaço
  const c = e.target.closest && e.target.closest('[role="button"][data-page-link]');
  if (c && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); c.click(); }
});
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-open-stack]")) return openStackFlow();
  const f = e.target.closest("[data-focus]");
  if (f) { const t = document.getElementById(f.dataset.focus); window.scrollTo(0, 0); t.focus(); }
});

/* ---------- itens: mais valiosos x mais dropados ---------- */
S.itemSort = "value";
function sortItems(items) {
  return [...items].sort(S.itemSort === "count" ? (a, b) => b.count - a.count || b.value - a.value
                                                : (a, b) => b.value - a.value || b.count - a.count);
}
function itemSortSeg() {
  return `<div class="seg" role="tablist" id="itemSortSeg">${[["value", "💎 Mais valiosos"], ["count", "📦 Mais dropados"]].map(([k, t]) =>
    `<button data-item-sort="${k}" class="${S.itemSort === k ? "on" : ""}" role="tab" aria-selected="${S.itemSort === k}">${t}</button>`).join("")}</div>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-item-sort]");
  if (!b || !S.stack) return;
  S.itemSort = b.dataset.itemSort;
  $("#itemSortSeg").outerHTML = itemSortSeg();
  $("#itemsBox").innerHTML = itemList(sortItems(S.stack.period.items));
});

/* ---------- evolução semanal de XP e lucro ---------- */
function weekKey(isoDay) {
  const d = new Date(isoDay.slice(0, 10) + "T12:00:00");
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));  // segunda-feira
  return d.toISOString().slice(0, 10);
}
function wkChart(vals, labels, { color, diverging }) {
  const W = 500, top = 16, base = 106, H = base - top;
  const hi = Math.max(0, ...vals), lo = Math.min(0, ...vals);
  const span = diverging ? (hi - lo || 1) : (hi || 1);
  const zero = diverging ? top + H * (hi / span) : base;
  const slot = W / vals.length, bw = slot * 0.62;
  const bars = vals.map((v, i) => {
    const h = (Math.abs(v) / span) * H, x = i * slot + (slot - bw) / 2, y = v >= 0 ? zero - h : zero;
    const fill = diverging ? (v >= 0 ? "var(--green)" : "var(--red)") : color;
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(v ? 1.5 : 0, h).toFixed(1)}" rx="2"
      style="fill:${fill}; opacity:${i === vals.length - 1 ? 1 : 0.72}"><title>Semana de ${labels[i]}: ${fmt(v)}</title></rect>`;
  }).join("");
  const lbls = labels.map((l, i) => (i % 2 === (labels.length - 1) % 2 ? `<text class="lbl" x="${(i * slot + slot / 2).toFixed(1)}" y="122" text-anchor="middle">${l}</text>` : "")).join("");
  return `<svg viewBox="0 0 ${W} 128" role="img" aria-label="Gráfico semanal">
    <line class="grid" x1="0" x2="${W}" y1="${zero.toFixed(1)}" y2="${zero.toFixed(1)}"/>
    <text class="lbl" x="0" y="10">${kk(hi)}</text>${diverging && lo < 0 ? `<text class="lbl" x="0" y="${base + 2}">−${kk(-lo)}</text>` : ""}
    ${bars}${lbls}</svg>`;
}
function weeklyBlock(sessions) {
  const N = 12, keys = [], d = new Date();
  for (let i = N - 1; i >= 0; i--) { const x = new Date(d); x.setDate(x.getDate() - i * 7); keys.push(weekKey(x.toISOString())); }
  const xp = Object.fromEntries(keys.map((k) => [k, 0])), profit = Object.fromEntries(keys.map((k) => [k, 0]));
  for (const s of sessions) { const k = weekKey(s.started_at); if (k in xp) { xp[k] += s.xp; profit[k] += s.net_profit ?? s.balance; } }
  const xv = keys.map((k) => xp[k]), pv = keys.map((k) => profit[k]);
  if (!xv.some(Boolean) && !pv.some(Boolean)) return "";
  const labels = keys.map((k) => k.slice(8, 10) + "/" + k.slice(5, 7));
  return `<h2>📊 Evolução semanal</h2><div class="card wk">
    <div class="wk-title"><span>XP por semana</span><span>esta semana: <b>${kk(xv[N - 1])}</b></span></div>
    ${wkChart(xv, labels, { color: "var(--bar)" })}
    <div class="wk-title" style="margin-top:14px"><span>Lucro líquido por semana</span><span>esta semana: <b class="${pv[N - 1] >= 0 ? "pos" : "neg"}">${kk(pv[N - 1])}</b></span></div>
    ${wkChart(pv, labels, { diverging: true })}
    <div class="hint">Últimas 12 semanas (segunda a domingo). Lucro líquido = loot pelos preços de NPC − supplies.</div></div>`;
}

/* ---------- ranking da PT (dano, cura e balance) ---------- */
S.ptMetric = "damage"; S.ptDays = 30;
function renderPtRank() {
  const box = $("#ptRank");
  if (!box) return;
  const cutoff = S.ptDays ? Date.now() - S.ptDays * 864e5 : 0;
  const hunts = (S.homeHunts || []).filter((h) => !cutoff || new Date(h.started_at).getTime() >= cutoff);
  const acc = new Map();
  for (const h of hunts) for (const p of h.players) {
    const r = acc.get(nk(p.name)) || { name: p.name, hunts: 0, damage: 0, healing: 0, balance: 0 };
    r.hunts++; r.damage += p.damage || 0; r.healing += p.healing || 0; r.balance += p.balance || 0;
    acc.set(nk(p.name), r);
  }
  const m = S.ptMetric, rows = [...acc.values()].sort((a, b) => b[m] - a[m]);
  const max = Math.max(1, ...rows.map((r) => Math.abs(r[m]))), me = nk(S.nick);
  const seg = (attr, cur, opts) => `<div class="seg" role="tablist">${opts.map(([k, t]) =>
    `<button ${attr}="${k}" class="${String(cur) === String(k) ? "on" : ""}" role="tab" aria-selected="${String(cur) === String(k)}">${t}</button>`).join("")}</div>`;
  box.innerHTML = `${seg("data-pt-metric", m, [["damage", "⚔️ Dano"], ["healing", "✨ Cura"], ["balance", "💰 Balance"]])}
    ${seg("data-pt-days", S.ptDays, [[7, "7 dias"], [30, "30 dias"], [0, "Tudo"]])}
    ${rows.length ? rows.slice(0, 10).map((r, i) => {
      const mine = nk(r.name) === me, v = r[m];
      return `<div class="rank" style="cursor:default">
        <span class="pos" style="font-size:${i < 3 ? 20 : 14}px">${i < 3 ? ["🥇", "🥈", "🥉"][i] : "#" + (i + 1)}</span>
        <span style="min-width:0"><b class="${mine ? "gold" : ""}">${vdot(r.name)}${esc(r.name)}${mine ? " (você)" : ""}</b><br>
          <span class="muted" style="font-size:13px">${r.hunts} hunt${r.hunts === 1 ? "" : "s"} · média ${kk(Math.round(v / r.hunts))}/hunt</span>
          <div class="track" style="margin-top:6px"><div class="fill voc ${mine ? "me" : ""}" style="width:${(Math.max(0, v) / max) * 100}%; ${vstyle(r.name)}"></div></div></span>
        <span style="text-align:right; min-width:64px"><b class="${m === "balance" && v < 0 ? "neg" : ""}">${kk(v)}</b></span></div>`;
    }).join("") : `<p class="muted">Nenhuma party hunt nesse período.</p>`}
    <div class="hint">Soma das party hunts em que ${esc(S.nick)} esteve. Balance = loot − supplies de cada um, antes da divisão.</div>${vocLegend()}`;
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-pt-metric]"), b = e.target.closest("[data-pt-days]");
  if (a) { S.ptMetric = a.dataset.ptMetric; renderPtRank(); }
  if (b) { S.ptDays = +b.dataset.ptDays; renderPtRank(); }
});

/* ---------- comemoração ---------- */
const Burst = {
  raf: 0,
  fire() {
    if (reduceMotion()) return;
    const c = $("#burst"), ctx = c.getContext("2d"), dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = c.clientWidth, h = c.clientHeight;
    c.width = w * dpr; c.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const cx = w / 2, cy = h * 0.4, cols = ["#fff1c1", "#f2c94c", "#b8861b", "#ffffff", "#ffd86b"];
    const ps = Array.from({ length: 120 }, () => {
      const a = Math.random() * 6.283, s = 3 + Math.random() * 8;
      return { x: cx, y: cy, vx: Math.cos(a) * s, vy: Math.sin(a) * s - 2.5, r: 2 + Math.random() * 3.2, rot: Math.random() * 6,
               vr: (Math.random() - 0.5) * 0.3, c: cols[(Math.random() * cols.length) | 0], sq: Math.random() < 0.55 };
    });
    const t0 = performance.now();
    cancelAnimationFrame(this.raf);
    const tick = (t) => {
      const k = (t - t0) / 1900;
      ctx.clearRect(0, 0, w, h);
      if (k >= 1) return;
      ctx.globalAlpha = 1 - k * k;
      for (const p of ps) {
        p.vx *= 0.985; p.vy = p.vy * 0.985 + 0.13; p.x += p.vx; p.y += p.vy; p.rot += p.vr;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.fillStyle = p.c;
        if (p.sq) ctx.fillRect(-p.r, -p.r / 2, p.r * 2, p.r); else { ctx.beginPath(); ctx.arc(0, 0, p.r * 0.7, 0, 6.283); ctx.fill(); }
        ctx.restore();
      }
      ctx.globalAlpha = 1;
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  },
};
const Cel = { q: [], busy: false, t: 0 };
function celebrate(item) { Cel.q.push(item); if (!Cel.busy) nextCel(); }
function nextCel() {
  clearTimeout(Cel.t);
  const it = Cel.q.shift(), box = $("#celebrate");
  if (!it) { Cel.busy = false; box.classList.add("hidden"); return; }
  Cel.busy = true;
  $("#celEmoji").textContent = it.emoji; $("#celKicker").textContent = it.kicker;
  $("#celTitle").textContent = it.title; $("#celSub").textContent = it.sub || "";
  box.classList.remove("hidden");
  const card = box.querySelector(".cel-card");
  card.style.animation = "none"; void card.offsetWidth; card.style.animation = "";
  Burst.fire();
  Cel.t = setTimeout(nextCel, 5500);
  $("#celOk").focus({ preventScroll: true });
}
$("#celOk").addEventListener("click", nextCel);
$("#celebrate").addEventListener("click", (e) => { if (e.target.id === "celebrate") nextCel(); });

function celebrateRewards(list) {
  for (const r of list || []) {
    S.keyExpires = r.expires_at;
    if (S.me) S.me.expires_at = r.expires_at;
    updateDrawerFoot();
    celebrate({ emoji: "🎁", kicker: "Recompensa desbloqueada", title: `+${r.days} dias de acesso!`,
                sub: `30 dias seguidos alimentando o 4rt3mi5. Seu código agora vale até ${new Date(r.expires_at).toLocaleDateString("pt-BR")}.` });
  }
}
const RARITY_PT = { "very rare": "muito raro", "extremely rare": "extremamente raro" };
/** 💎 Drop raro de boss na sessão que acabou de ser enviada. */
function celebrateRare(list) {
  for (const d of (list || []).slice(0, 3)) {
    celebrate({ emoji: "💎", kicker: `Drop raro de ${d.boss}!`, title: `${d.count > 1 ? d.count + "x " : ""}${d.name || d.item}`,
                sub: [d.rarity ? `${RARITY_PT[d.rarity] || d.rarity} na TibiaWiki` : "", d.value ? `vale ${fmt(d.value)} gp` : ""].filter(Boolean).join(" · ") });
  }
}
function recordText(r) {
  return r.unit === "tempo" ? dur(r.value) : fmt(r.value) + (r.unit === "XP" ? " XP" : r.unit === "XP/h" ? " XP/h" : " " + r.unit);
}
/** Depois de enviar uma sessão: novo recorde pessoal ou meta batida. */
function celebrateProgress(before, after) {
  if (!before || !after || !before.sessions.length) return;
  for (const r of after.records) {
    const old = before.records.find((x) => x.label === r.label);
    if (old && r.value > old.value && r.session_id !== old.session_id)
      celebrate({ emoji: "🏆", kicker: "Novo recorde pessoal", title: r.label, sub: `${recordText(r)} (antes: ${recordText(old)})` });
  }
  for (const g of after.goals) {
    const old = before.goals.find((x) => x.period === g.period && x.metric === g.metric);
    if (g.pct >= 100 && (!old || old.pct < 100))
      celebrate({ emoji: "🎯", kicker: "Meta batida", title: `${GOAL_LABEL[g.period]} · ${METRIC_LABEL[g.metric]}`,
                  sub: `${kk(g.done)} de ${kk(g.target)}${g.metric === "loot" ? " gp" : " XP"}` });
  }
}
/** Compara com as conquistas já vistas neste aparelho e comemora as novas. */
async function diffAchievements(d) {
  const store = "ach:" + nk(d.name);
  const seen = JSON.parse((await kv.get(store)) || "null");
  const now = d.achievements.filter((a) => a.unlocked).map((a) => a.id);
  await kv.set(store, JSON.stringify(now));
  if (seen) for (const a of d.achievements) if (a.unlocked && !seen.includes(a.id))
    celebrate({ emoji: a.emoji, kicker: "Conquista desbloqueada", title: a.title, sub: a.description });
  celebrateRewards(d.granted);
}
async function checkAchievements() {
  try { await diffAchievements(await api("GET", `/api/achievements/${encodeURIComponent(S.nick)}`)); } catch {}
}

/* ---------- página de conquistas e sequência de dias ---------- */
function streakDays(s) {
  const today = new Date();
  const frozen = s.calendar_frozen || [];
  return s.calendar.map((on, i) => {
    const d = new Date(today); d.setDate(d.getDate() - (s.calendar.length - 1 - i));
    const ice = !on && frozen[i];  // 0.17.0: chave vencida nesse dia — a sequência ficou congelada, não perdida
    return `<i class="${on ? "on" : ""} ${ice ? "ice" : ""} ${i === s.calendar.length - 1 ? "today" : ""}" title="${d.toLocaleDateString("pt-BR")}${on ? ": enviou" : ice ? ": congelado (chave vencida)" : ""}"></i>`;
  }).join("");
}
// 0.20.0: a chave não vence mais, então a sequência de dias não dá mais dias de validade; ela continua como desafio.
function streakCard(s) {
  return `<div class="card streak">
    <div><div class="muted">🔥 Sequência de dias</div><div class="count">${s.current} <span class="muted" style="font: 600 15px system-ui">${s.current === 1 ? "dia seguido" : "dias seguidos"}</span></div></div>
    <div class="days" aria-label="Últimos 30 dias">${streakDays(s)}</div>
    <p style="margin:10px 0 0; font-size:14px">Envie pelo menos uma party hunt (Lootsplit) ou sessão (Stacker) por dia para manter a sequência.</p>
    <div class="hint">${s.active_today ? "Hoje já conta ✔" : "Hoje ainda não conta: envie algo até a meia-noite (horário de Brasília) para manter a sequência."}</div></div>`;
}
function streakTeaser(s) {
  return `<div class="card streak teaser" data-page-link="ach" role="button" tabindex="0" aria-label="Ver conquistas e sequência">
    <div class="count">${s.current}</div>
    <div style="min-width:0; flex:1"><b>🔥 ${s.current === 1 ? "1 dia seguido" : `${s.current} dias seguidos`}</b>
      <div class="muted" style="font-size:13px">Envie uma hunt ou sessão por dia para manter a sequência. ${s.active_today ? "Hoje já conta ✔" : "Falta enviar hoje."}</div></div></div>`;
}
function achProgress(a) {
  const f = a.id === "marathon" ? dur : ["loot_kk", "xp_kk", "slayer"].includes(a.id) ? kk : fmt;
  return `${f(a.value)} / ${f(a.target)}`;
}
/** Início: criatura e boss do dia (boosted). Sem dado, não mostra nada. */
function boostedCard(b) {
  if (!b || (!b.creature && !b.boss)) return "";
  const one = (label, name, hint) => name ? `<div style="display:flex;align-items:center;gap:8px;min-width:0">${creatureImg(name, 32)}
    <span style="min-width:0"><span class="muted" style="font-size:12px;display:block">${label}</span><b data-i18n-skip>${esc(name)}</b></span></div>` : "";
  return `<div class="card"><b>🔥 Boost de hoje</b>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:8px">
      ${one("Criatura", b.creature)}${one("Boss", b.boss)}</div>
    <div class="hint">Criatura boosted dá mais XP e loot; boss boosted, mais chance de loot. Vale até o próximo server save. ${TN_CREDIT}</div></div>`;
}
/** Início: resumo de conquistas e a próxima mais perto de sair. Falha em silêncio (não atrapalha a tela). */
function achievementsFor(nick) {
  return api("GET", `/api/achievements/${encodeURIComponent(nick)}`).catch(() => null);
}
function achHomeCard(d) {
  if (!d || !Array.isArray(d.achievements) || !d.achievements.length) return "";
  const got = d.achievements.filter((a) => a.unlocked).length, total = d.achievements.length;
  const next = d.achievements.filter((a) => !a.unlocked).sort((a, b) => b.pct - a.pct)[0];
  return `<div class="card"><div class="row"><b>🏅 Conquistas</b><span class="muted">${got} de ${total}</span></div>
    ${next ? `<div style="margin-top:8px"><b>${next.emoji} ${esc(next.title)}</b> <span class="muted" style="font-size:13px">próxima</span>
      <div class="gbar"><div style="width:${next.pct}%"></div></div><div class="hint">${achProgress(next)}</div></div>`
      : `<p class="muted" style="margin:6px 0 0">Todas desbloqueadas 🎉</p>`}
    <button class="link" data-page-link="ach" style="margin-top:6px">Ver todas as conquistas →</button></div>`;
}
function achCard(a) {
  return `<div class="ach ${a.unlocked ? "on" : "lock"}"><div class="em">${a.emoji}</div><b>${esc(a.title)}</b><p>${esc(a.description)}</p>
    ${a.unlocked ? `<div class="done-tag">✔ Desbloqueada</div>`
                 : `<div class="gbar"><div style="width:${a.pct}%"></div></div><div class="hint">${achProgress(a)}</div>`}</div>`;
}
async function loadAch() {
  const el = $("#achBody");
  el.innerHTML = skeleton("list");
  let d;
  try { d = await api("GET", `/api/achievements/${encodeURIComponent(S.nick)}`); }
  catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  el.innerHTML = `${streakCard(d.streak)}
    <h2>${esc(d.name)} · ${d.unlocked} de ${d.total} conquistas</h2>
    <div class="ach-grid">${[...d.achievements].sort((a, b) => b.unlocked - a.unlocked || b.pct - a.pct).map(achCard).join("")}</div>
    <div class="hint" style="margin-top:10px">As conquistas são do personagem (quem tem acesso ao app pode ver). A sequência de dias é do seu código de acesso.</div>`;
  await diffAchievements(d);
}

/* ---------- card para compartilhar ---------- */
const SHARE = new Map();
let shareSeq = 0;
function shareButton(kind, obj) {
  const id = "s" + (++shareSeq);
  SHARE.set(id, { kind, obj });
  return `<button class="link" data-share="${id}" style="margin-top:10px">🖼️ Card para compartilhar</button>`;
}
function rr(ctx, x, y, w, h, r) {
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}
function fitFont(ctx, text, weight, max, maxW, family = "system-ui, Segoe UI, sans-serif") {
  let size = max;
  do { ctx.font = `${weight} ${size}px ${family}`; size -= 4; } while (ctx.measureText(text).width > maxW && size > 20);
}
function drawBase(ctx, W, H, kicker, when) {
  ctx.fillStyle = "#0b0d12"; ctx.fillRect(0, 0, W, H);
  let g = ctx.createRadialGradient(W / 2, 250, 0, W / 2, 250, 900);
  g.addColorStop(0, "rgba(242,201,76,0.13)"); g.addColorStop(1, "rgba(242,201,76,0)");
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  g = ctx.createRadialGradient(W / 2, H + 100, 0, W / 2, H + 100, 800);
  g.addColorStop(0, "rgba(124,140,255,0.08)"); g.addColorStop(1, "rgba(124,140,255,0)");
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  // runa de fundo
  ctx.save(); ctx.translate(W - 150, H - 230); ctx.rotate(0.3); ctx.strokeStyle = "rgba(242,201,76,0.07)"; ctx.lineWidth = 3;
  for (const r of [300, 262, 180]) { ctx.beginPath(); ctx.arc(0, 0, r, 0, 6.283); ctx.stroke(); }
  for (let i = 0; i < 24; i++) { const a = (i / 24) * 6.283; ctx.beginPath(); ctx.moveTo(Math.cos(a) * 268, Math.sin(a) * 268); ctx.lineTo(Math.cos(a) * 294, Math.sin(a) * 294); ctx.stroke(); }
  ctx.restore();
  // moldura
  ctx.strokeStyle = "rgba(242,201,76,0.22)"; ctx.lineWidth = 2; rr(ctx, 36, 36, W - 72, H - 72, 36); ctx.stroke();
  // marca
  ctx.font = "800 64px Cinzel, Georgia, serif";
  if ("letterSpacing" in ctx) ctx.letterSpacing = "6px";
  g = ctx.createLinearGradient(0, 100, 0, 160);
  g.addColorStop(0, "#fff1c1"); g.addColorStop(0.55, "#f2c94c"); g.addColorStop(1, "#b8861b");
  ctx.fillStyle = g; ctx.textAlign = "left"; ctx.fillText("4rt3mi5", 84, 158);
  ctx.font = "600 24px system-ui, Segoe UI, sans-serif";
  if ("letterSpacing" in ctx) ctx.letterSpacing = "5px";
  ctx.fillStyle = "#f2c94c"; ctx.textAlign = "right"; ctx.fillText(kicker, W - 84, 122);
  ctx.fillStyle = "#98a1b3"; if ("letterSpacing" in ctx) ctx.letterSpacing = "1px"; ctx.fillText(when, W - 84, 160);
  if ("letterSpacing" in ctx) ctx.letterSpacing = "0px";
}
function drawHero(ctx, W, label, value, positive, sub) {
  ctx.textAlign = "left";
  ctx.font = "600 26px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = "#98a1b3";
  if ("letterSpacing" in ctx) ctx.letterSpacing = "4px";
  ctx.fillText(label, 84, 292);
  if ("letterSpacing" in ctx) ctx.letterSpacing = "0px";
  fitFont(ctx, value, 800, 124, W - 168);
  const g = ctx.createLinearGradient(0, 310, 0, 430);
  if (positive) { g.addColorStop(0, "#fff1c1"); g.addColorStop(1, "#f2c94c"); } else { g.addColorStop(0, "#ffb3a8"); g.addColorStop(1, "#ff7a6b"); }
  ctx.fillStyle = g; ctx.fillText(value, 80, 418);
  ctx.font = "500 30px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = "#c9cfdb"; ctx.fillText(sub, 84, 474);
  const line = ctx.createLinearGradient(84, 0, W - 84, 0);
  line.addColorStop(0, "rgba(242,201,76,0.7)"); line.addColorStop(1, "rgba(242,201,76,0)");
  ctx.fillStyle = line; ctx.fillRect(84, 520, W - 168, 2);
}
function drawFooter(ctx, W, H) {
  ctx.textAlign = "center"; ctx.font = "500 24px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = "#98a1b3";
  ctx.fillText("4rt3mi5 · divida o loot e guarde suas hunts", W / 2, H - 78);
}
function drawHuntCard(ctx, W, H, h) {
  const me = nk(S.nick);
  drawBase(ctx, W, H, "PARTY HUNT", `${new Date(h.started_at).toLocaleDateString("pt-BR")} · ${dur(h.duration_seconds)}`);
  drawHero(ctx, W, "RENDEU PARA CADA UM", `${h.profit_each >= 0 ? "+" : "−"}${fmt(Math.abs(h.profit_each))} gp`, h.profit_each >= 0,
           `${fmt(h.profit_each_per_hour)} gp/h por pessoa · PT de ${h.players_count}`);
  const totalDmg = h.players.reduce((a, p) => a + Math.max(0, p.damage || 0), 0) || 1;
  const totalHeal = h.players.reduce((a, p) => a + Math.max(0, p.healing || 0), 0) || 1;
  const rows = [...h.players].sort((a, b) => (b.damage || 0) - (a.damage || 0)).slice(0, 5);
  ctx.textAlign = "left"; ctx.font = "600 24px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = "#98a1b3";
  if ("letterSpacing" in ctx) ctx.letterSpacing = "4px";
  ctx.fillText("QUEM FEZ O QUÊ", 84, 590);
  if ("letterSpacing" in ctx) ctx.letterSpacing = "0px";
  rows.forEach((p, i) => {
    const y = 650 + i * 116, mine = nk(p.name) === me, col = VOC_HEX[vocKey(S.voc[nk(p.name)])];
    const dmg = Math.round((Math.max(0, p.damage || 0) / totalDmg) * 100), heal = Math.round((Math.max(0, p.healing || 0) / totalHeal) * 100);
    ctx.fillStyle = col; ctx.beginPath(); ctx.arc(96, y - 11, 10, 0, 6.283); ctx.fill();
    ctx.textAlign = "left"; ctx.font = `${mine ? 800 : 700} 36px system-ui, Segoe UI, sans-serif`; ctx.fillStyle = mine ? "#f2c94c" : "#e9ecf2";
    ctx.fillText(p.name + (p.is_leader ? " 👑" : ""), 120, y);
    ctx.textAlign = "right"; ctx.font = "600 28px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = "#e9ecf2";
    ctx.fillText(`${dmg}% do dano`, W - 84, y);
    ctx.fillStyle = "#232836"; rr(ctx, 84, y + 18, W - 168, 14, 7); ctx.fill();
    ctx.fillStyle = col; rr(ctx, 84, y + 18, Math.max(14, (W - 168) * dmg / 100), 14, 7); ctx.fill();
    if (mine) { ctx.strokeStyle = "#f2c94c"; ctx.lineWidth = 2; rr(ctx, 84, y + 18, Math.max(14, (W - 168) * dmg / 100), 14, 7); ctx.stroke(); }
    ctx.textAlign = "left"; ctx.font = "500 24px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = "#98a1b3";
    ctx.fillText(`cura ${heal}% · balance ${kk(p.balance)} · ${S.voc[nk(p.name)] || ""}`, 84, y + 66);
  });
  if (h.players.length > 5) { ctx.fillStyle = "#98a1b3"; ctx.font = "500 24px system-ui, Segoe UI, sans-serif"; ctx.fillText(`+${h.players.length - 5} jogadores`, 84, 650 + 5 * 116 - 20); }
  drawFooter(ctx, W, H);
}
function drawSoloCard(ctx, W, H, s) {
  drawBase(ctx, W, H, "HUNT SESSION", `${new Date(s.started_at).toLocaleDateString("pt-BR")} · ${dur(s.duration_seconds)}`);
  const xph = s.duration_seconds ? Math.round(s.xp * 3600 / s.duration_seconds) : 0;
  drawHero(ctx, W, "LUCRO LÍQUIDO", `${s.net_profit >= 0 ? "+" : "−"}${fmt(Math.abs(s.net_profit))} gp`, s.net_profit >= 0,
           `${S.nick}${s.place ? " · " + s.place.name : ""}`);
  const stats = [["XP", kk(s.xp)], ["XP/h", kk(xph)], ["Damage/h", kk(s.damage_h)], ["Healing/h", kk(s.healing_h)]];
  const bw = (W - 168 - 24) / 2;
  stats.forEach(([k, v], i) => {
    const x = 84 + (i % 2) * (bw + 24), y = 570 + Math.floor(i / 2) * 150;
    ctx.fillStyle = "#1d212d"; rr(ctx, x, y, bw, 126, 22); ctx.fill();
    ctx.strokeStyle = "#2a2f3d"; ctx.lineWidth = 2; ctx.stroke();
    ctx.textAlign = "left"; ctx.font = "600 24px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = "#98a1b3"; ctx.fillText(k, x + 28, y + 46);
    ctx.font = "800 48px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = i < 2 ? "#f2c94c" : "#e9ecf2"; ctx.fillText(v, x + 28, y + 102);
  });
  const top = (s.loot || []).filter((i) => i.value > 0).slice(0, 4);
  let y = 900;
  if (top.length) {
    ctx.font = "600 24px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = "#98a1b3";
    if ("letterSpacing" in ctx) ctx.letterSpacing = "4px";
    ctx.fillText("LOOT QUE MAIS RENDEU", 84, y);
    if ("letterSpacing" in ctx) ctx.letterSpacing = "0px";
    top.forEach((it, i) => {
      const yy = y + 56 + i * 54, name = (S.prices[it.key] || {}).name || it.key;
      ctx.textAlign = "left"; ctx.font = "600 30px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = "#e9ecf2";
      ctx.fillText(`${fmt(it.count)}x ${name}`, 84, yy);
      ctx.textAlign = "right"; ctx.fillStyle = "#f2c94c"; ctx.fillText(kk(it.value) + " gp", W - 84, yy);
    });
    y += 56 + top.length * 54;
  }
  if (s.kills && s.kills.length) {
    ctx.textAlign = "left"; ctx.font = "500 26px system-ui, Segoe UI, sans-serif"; ctx.fillStyle = "#98a1b3";
    const txt = "Mais mortos: " + s.kills.slice(0, 3).map((k) => `${fmt(k.count)}x ${k.key}`).join(" · ");
    fitFont(ctx, txt, 500, 26, W - 168); ctx.fillText(txt, 84, Math.min(y + 30, H - 140));
  }
  drawFooter(ctx, W, H);
}
async function openShare(id) {
  const { kind, obj } = SHARE.get(id) || {};
  if (!kind) return;
  openModal(`<h3>🖼️ Card para compartilhar</h3><canvas id="shareCanvas" width="1080" height="1350" aria-label="Prévia do card"></canvas>
    <div class="actions" id="shareActions"></div><div class="hint" id="shareMsg"></div>`);
  if (kind === "hunt") await ensureVocations(obj.players.map((p) => p.name));
  try { await document.fonts.load("800 64px Cinzel"); } catch {}
  const c = $("#shareCanvas");
  if (!c) return;
  const ctx = c.getContext("2d");
  (kind === "hunt" ? drawHuntCard : drawSoloCard)(ctx, c.width, c.height, obj);
  const blob = await new Promise((r) => c.toBlob(r, "image/png"));
  const file = new File([blob], `4rt3mi5-${kind === "hunt" ? "party" : "sessao"}-${obj.started_at.slice(0, 10)}.png`, { type: "image/png" });
  const acts = [];
  if (navigator.canShare && navigator.canShare({ files: [file] })) acts.push(`<button class="btn" data-share-act="share">Compartilhar</button>`);
  if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) acts.push(`<button class="btn2" data-share-act="copy">Copiar imagem</button>`);
  acts.push(`<button class="btn2" data-share-act="save">Baixar PNG</button>`, `<button class="btn2" data-close-modal>Fechar</button>`);
  $("#shareActions").innerHTML = acts.join("");
  $("#shareActions").onclick = async (e) => {
    const b = e.target.closest("[data-share-act]");
    if (!b) return;
    const msg = $("#shareMsg");
    try {
      if (b.dataset.shareAct === "share") await navigator.share({ files: [file], title: "4rt3mi5" });
      if (b.dataset.shareAct === "copy") { await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]); msg.textContent = "Imagem copiada. Cole no Discord ou no WhatsApp."; }
      if (b.dataset.shareAct === "save") {
        const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: file.name });
        document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
        msg.textContent = "Imagem salva na pasta de downloads.";
      }
    } catch (err) { if (err && err.name !== "AbortError") msg.textContent = "Não deu certo por aqui. Tente outra opção."; }
  };
}
document.addEventListener("click", (e) => { const b = e.target.closest("[data-share]"); if (b) { e.preventDefault(); openShare(b.dataset.share); } });

/* ---------- 0.29.0: 📤 Compartilhar (um só lugar para resumo, comandos, imagem e link público) ---------- */
const SHARE_MENU = new Map();
function shareMenuButton(h) {
  const id = "m" + (++shareSeq);
  SHARE_MENU.set(id, h);
  return `<button class="copy" data-share-menu="${id}">📤 Compartilhar</button>`;
}
function shareOption(title, desc, action) {
  return `<div class="row" style="padding:10px 0; border-top:1px solid var(--line); align-items:flex-start">
    <div style="flex:1 1 200px"><b>${title}</b><div class="hint">${desc}</div></div><div>${action}</div></div>`;
}
function openShareMenu(id) {
  const h = SHARE_MENU.get(id);
  if (!h) return;
  const cmds = h.transfers.map((t) => `${t.payer}: ${t.command}`).join("\n");
  const imgId = "s" + (++shareSeq); SHARE.set(imgId, { kind: "hunt", obj: h });
  const canLink = !!h.id && !(S.me && S.me.readonly);
  openModal(`<h3>📤 Compartilhar este lootsplit</h3>
    ${shareOption("📋 Resumo para Discord/WhatsApp", "Texto curto com o resultado e quem paga quem. Para colar no grupo.",
      `<button class="btn2" data-copy="${esc(splitSummary(h))}">Copiar</button>`)}
    ${h.transfers.length ? shareOption("💸 Só os comandos de transferência", "Uma linha por pagador, para quem vai fazer os pagamentos.",
      `<button class="btn2" data-copy="${esc(cmds)}">Copiar</button>`) : ""}
    ${shareOption("🖼️ Imagem para postar", "Um card pronto com o resultado da hunt.", `<button class="btn2" data-share="${imgId}">Abrir</button>`)}
    ${shareOption("🔗 Link público", canLink
      ? "Quem abrir vê o resultado e as transferências, sem criar conta. Vale 30 dias e você pode cancelar."
      : "Salve este lootsplit na sua conta para poder criar um link.",
      canLink ? `<button class="btn2" data-link-create="${h.id}">Criar link</button>` : "")}
    <div id="shareLinkBox"></div>
    <div class="actions"><button class="btn2" data-close-modal>Fechar</button></div>`);
}
async function shareLinkAction(btn) {
  const box = $("#shareLinkBox"), id = btn.dataset.linkCreate || btn.dataset.linkRevoke;
  btn.disabled = true;
  try {
    if (btn.dataset.linkRevoke) {
      await api("DELETE", `/api/hunt/${id}/link`);
      box.innerHTML = `<div class="hint">Link cancelado. Quem tinha o endereço não consegue mais abrir.</div>`;
      return;
    }
    const r = await api("POST", `/api/hunt/${id}/link`);
    const url = (S.api || location.origin) + r.path;
    box.innerHTML = `<div class="msgbox" data-i18n-skip>${esc(url)}</div>
      <div class="row" style="justify-content:flex-end; gap:8px"><button class="btn2" data-link-revoke="${esc(id)}">Cancelar link</button>
      <button class="btn2" data-copy="${esc(url)}">Copiar link</button></div>
      <div class="hint">O link mostra os nomes, os valores e as transferências desta hunt para quem o receber.</div>`;
  } catch (err) { if (err.status !== 401) box.innerHTML = `<div class="err" data-i18n-skip>${esc(err.message)}</div>`; }
  finally { btn.disabled = false; }
}
document.addEventListener("click", (e) => {
  const m = e.target.closest("[data-share-menu]");
  if (m) { e.preventDefault(); openShareMenu(m.dataset.shareMenu); return; }
  const l = e.target.closest("[data-link-create],[data-link-revoke]");
  if (l) { e.preventDefault(); shareLinkAction(l); }
});

/* ---------- janelas ---------- */
function openModal(html) { $("#modalBox").innerHTML = html; $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); $("#modalBox").innerHTML = ""; }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal" || e.target.closest("[data-close-modal]")) closeModal(); });
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("#modal").classList.contains("hidden")) closeModal();
  $("#sheet").classList.add("hidden");
});

/* ---------- colar direto (Ctrl+V em qualquer tela, ou o botão 📋) ---------- */
function detectPaste(t) {
  if (!t || t.length > 200000 || !/Session data:/i.test(t)) return null;
  if (/Loot Type:/i.test(t)) return "party";
  if (/XP Gain:/i.test(t)) return "solo";
  return null;
}
function pasteSummary(t) {
  const s = (t.match(/Session:\s*([\d:]+h?)/i) || [])[1], d = (t.match(/From\s+(\d{4}-\d{2}-\d{2})/i) || [])[1];
  return [s && "Sessão de " + s, d && "em " + dayLabel(d)].filter(Boolean).join(" ") || "Texto do Analyser";
}
async function offerPaste(kind, t) {
  S.pasteText = t;
  const sheet = $("#sheet");
  if (kind === "party") {
    sheet.innerHTML = `<b>📋 Party Hunt Analyser detectado</b>
      <div class="muted" style="font-size:14px; margin-top:2px">${esc(pasteSummary(t))}. Enviar para o Lootsplit em nome de ${esc(S.nick)}?</div>
      <div class="actions"><button class="btn" data-paste-go="party">Enviar agora</button><button class="btn2" data-paste-cancel>Cancelar</button></div>`;
  } else {
    sheet.innerHTML = `<b>📋 Hunt Analyser (sessão solo) detectado</b>
      <div class="muted" style="font-size:14px; margin-top:2px">${esc(pasteSummary(t))}. Salvar no Hunt Session Stacker de ${esc(S.nick)}?</div>
      <div class="actions"><button class="btn" data-paste-go="solo">Salvar agora</button>
        <button class="btn2" data-paste-go="boss">👑 Foi boss</button>
        <button class="btn2" data-paste-cancel>Cancelar</button></div>`;
  }
  sheet.classList.remove("hidden");
}
document.addEventListener("paste", (e) => {
  if ($("#app").classList.contains("hidden")) return;
  if (e.target && e.target.closest && e.target.closest("input, textarea, [contenteditable]")) return;  // colando numa caixa: normal
  const t = (e.clipboardData || window.clipboardData).getData("text");
  const kind = detectPaste(t);
  if (!kind) return;
  e.preventDefault();
  offerPaste(kind, t);
});
document.addEventListener("click", async (e) => {
  if (e.target.closest("[data-paste-cancel]")) { $("#sheet").classList.add("hidden"); return; }
  const g = e.target.closest("[data-paste-go]");
  if (g) {
    $("#sheet").classList.add("hidden");
    const t = S.pasteText;
    if (g.dataset.pasteGo === "party") { await setMode("party", { nav: false }); go("loot"); $("#lootText").value = t; $("#lootBtn").click(); return; }
    if (g.dataset.pasteGo === "boss") { go("boss"); $("#bossText").value = t; $("#bossText").focus(); return; }
    await setMode("solo", { nav: false });
    go("stack");
    openStackFlow(t, true);
    return;
  }
  const p = e.target.closest("[data-paste-into]");
  if (p) {
    const box = document.getElementById(p.dataset.pasteInto);
    const err = p.dataset.pasteErr ? document.getElementById(p.dataset.pasteErr)
              : $("#lootErr");
    try {
      const t = await navigator.clipboard.readText();
      if (!t.trim()) { err.textContent = "A área de transferência está vazia. Copie o texto no Tibia primeiro."; return; }
      box.value = t; err.textContent = "";
    } catch { err.textContent = "O navegador não deixou ler a área de transferência. Toque e segure na caixa e escolha Colar."; box.focus(); }
  }
});

/* ---------- ícone na tela inicial (só com "Sim" da pessoa) ---------- */
let deferredInstall = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredInstall = e; updateInstallItem(); });
window.addEventListener("appinstalled", () => { deferredInstall = null; kv.set("install_state", "done"); updateInstallItem(); });
const isStandalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const canInstall = () => !S.desktop && !isStandalone() && (!!deferredInstall || isIOS());
function updateInstallItem() { $("#installItem").classList.toggle("hidden", !canInstall()); }
async function offerInstall() {
  updateInstallItem();
  if (!canInstall() || $("#app").classList.contains("hidden") || !$("#modal").classList.contains("hidden")) return;
  if ((await kv.get("install_state")) === "done") return;
  if (Date.now() - (+(await kv.get("install_later")) || 0) < 30 * 864e5) return;  // "agora não": pergunta de novo em 30 dias
  showInstallDialog();
}
function showInstallDialog() {
  openModal(`<h3>📲 Adicionar o 4rt3mi5 à tela inicial?</h3>
    <p class="muted" style="margin:0 0 4px">Se você tocar em <b style="color:var(--text)">Sim, adicionar</b>:</p>
    <ul>
      <li>Um ícone do 4rt3mi5 (o anel dourado com a flecha) aparece na tela inicial do celular, ou no menu Iniciar do PC.</li>
      <li>Tocando no ícone, o 4rt3mi5 abre em tela cheia, sem a barra do navegador.</li>
      <li>É só um atalho para este site: nada mais é instalado, nenhuma permissão é pedida e você remove quando quiser, como qualquer ícone.</li>
      ${isIOS() ? "<li>No iPhone e no iPad, quem cria o ícone é o Safari: vamos mostrar os 2 toques necessários.</li>"
                : "<li>O navegador ainda mostra uma confirmação dele antes de criar o ícone.</li>"}
    </ul>
    <p class="muted" style="font-size:13px; margin:6px 0 0">Tocando em "Agora não", nada é criado. Dá para fazer depois em ☰ → 📲 Adicionar à tela inicial.</p>
    <div class="actions"><button class="btn" id="instYes">Sim, adicionar</button><button class="btn2" id="instNo">Agora não</button></div>`);
  $("#instYes").addEventListener("click", async () => {
    if (deferredInstall) {
      closeModal();
      deferredInstall.prompt();
      const r = await deferredInstall.userChoice.catch(() => null);
      deferredInstall = null;
      if (r && r.outcome === "accepted") kv.set("install_state", "done");
      updateInstallItem();
    } else if (isIOS()) {
      $("#modalBox").innerHTML = `<h3>Adicionar no iPhone ou iPad</h3>
        <ol class="steps" style="color:var(--text); font-size:15px"><li>Toque em <b>Compartilhar</b> (o quadrado com a seta ↑) na barra do Safari.</li>
        <li>Escolha <b>Adicionar à Tela de Início</b> e confirme.</li></ol>
        <div class="actions"><button class="btn2" data-close-modal>Entendi</button></div>`;
    }
  });
  $("#instNo").addEventListener("click", () => { kv.set("install_later", String(Date.now())); closeModal(); });
}
$("#installItem").addEventListener("click", () => { closeDrawer(); showInstallDialog(); });

/* ---------- 0.21.0: telas por cima de tudo (contato e créditos), abertas pelo rodapé ----------
   Funcionam antes do login (a CipSoft precisa conseguir falar com a gente sem criar conta). */
const Overlay = {
  stack: [],
  open(id) {
    const el = $("#" + id);
    if (!el.classList.contains("hidden")) return;
    closeDrawer();
    el.classList.remove("hidden"); el.scrollTop = 0;
    document.body.classList.add("overpage-open");
    this.stack.push(id);
    try { history.pushState({ over: id }, ""); } catch {}
  },
  /** Fecha a de cima; devolve true se havia alguma aberta. */
  closeTop() {
    const id = this.stack.pop();
    if (!id) return false;
    $("#" + id).classList.add("hidden");
    if (!this.stack.length) document.body.classList.remove("overpage-open");
    return true;
  },
  back() { if (this.stack.length) { try { history.back(); } catch { this.closeTop(); } } },
};
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && Overlay.stack.length && $("#modal").classList.contains("hidden")) Overlay.back();
});
document.querySelectorAll("[data-over-close]").forEach((b) => b.addEventListener("click", () => Overlay.back()));
$("#openCredits").addEventListener("click", () => Overlay.open("creditsScreen"));

/* Bandeiras desenhadas aqui mesmo (o Windows não desenha bandeira em emoji). */
const FLAGS = {
  "pt-BR": '<rect width="30" height="20" fill="#009b3a"/><path d="M15 2.5 27.5 10 15 17.5 2.5 10z" fill="#fedf00"/><circle cx="15" cy="10" r="4.6" fill="#002776"/>',
  en: '<rect width="30" height="20" fill="#fff"/>' + [0, 2, 4, 6, 8, 10, 12].map((i) => `<rect y="${i * 20 / 13}" width="30" height="${20 / 13}" fill="#b22234"/>`).join("")
    + '<rect width="13" height="10.77" fill="#3c3b6e"/>',
  es: '<rect width="30" height="20" fill="#aa151b"/><rect y="5" width="30" height="10" fill="#f1bf00"/>',
  ja: '<rect width="30" height="20" fill="#fff"/><circle cx="15" cy="10" r="5.5" fill="#bc002d"/>',
  de: '<rect width="30" height="6.67" fill="#000"/><rect y="6.67" width="30" height="6.67" fill="#dd0000"/><rect y="13.33" width="30" height="6.67" fill="#ffce00"/>',
  pl: '<rect width="30" height="10" fill="#fff"/><rect y="10" width="30" height="10" fill="#dc143c"/>',
  fr: '<rect width="10" height="20" fill="#0055a4"/><rect x="10" width="10" height="20" fill="#fff"/><rect x="20" width="10" height="20" fill="#ef4135"/>',
  ru: '<rect width="30" height="6.67" fill="#fff"/><rect y="6.67" width="30" height="6.67" fill="#0039a6"/><rect y="13.33" width="30" height="6.67" fill="#d52b1e"/>',
};
const flagSvg = (code) => `<svg class="flag" viewBox="0 0 30 20" width="24" height="16" aria-hidden="true">${FLAGS[code] || ""}</svg>`;
function flagPicker(el) {
  el.setAttribute("data-i18n-skip", "");
  el.innerHTML = I18N.LANGS.map((l) => `<button type="button" data-lang="${l.code}" class="${l.code === I18N.lang ? "on" : ""}"
      title="${esc(l.name)}">${flagSvg(l.code)}<span lang="${l.code}">${esc(l.name)}</span></button>`).join("");
  el.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", async () => {
    const code = await I18N.use(b.dataset.lang);
    saveLang(code);
  }));
  I18N.onChange((code) => el.querySelectorAll("[data-lang]").forEach((x) => x.classList.toggle("on", x.dataset.lang === code)));
}
flagPicker($("#contactLang"));

/* ---------- contato com o administrador ---------- */
const CONTACT_MAX = 3000;
const EMAIL_RE = /^[^@\s<>"',;]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})+$/;
async function openContact() {
  $("#contactForm").classList.remove("hidden");
  $("#contactDone").classList.add("hidden");
  $("#contactErr").textContent = "";
  Overlay.open("contactScreen");
  setTimeout(() => $("#contactEmail").focus(), 60);
  const info = await fetch(S.api + "/api/contact", { headers: NGROK }).then((r) => r.json()).catch(() => null);
  if (info && info.to) $("#contactTo").value = $("#contactTo").defaultValue = info.to;
}
$("#openContact").addEventListener("click", openContact);
function paintContactCount() {
  const n = $("#contactMsg").value.length;
  $("#contactCount").textContent = `${n.toLocaleString("pt-BR")} / ${CONTACT_MAX.toLocaleString("pt-BR")}`;
  $("#contactCount").classList.toggle("neg", n >= CONTACT_MAX);
}
$("#contactMsg").addEventListener("input", paintContactCount);
paintContactCount();

/** Acha o número que o servidor sorteou (prova de trabalho). Devolve null se a pessoa cancelar. */
async function solveCaptcha(ch, onProgress, cancelled) {
  if (!(window.crypto && crypto.subtle)) throw new Error("subtle");
  const enc = new TextEncoder();
  const target = new Uint8Array(ch.challenge.match(/../g).map((h) => parseInt(h, 16)));
  for (let n = 0; n <= ch.maxnumber; n++) {
    const h = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(ch.salt + n)));
    let same = true;
    for (let i = 0; i < 32; i++) if (h[i] !== target[i]) { same = false; break; }
    if (same) return n;
    if (n % 1500 === 0) { onProgress(n / ch.maxnumber); if (cancelled()) return null; }
  }
  return null;
}
function captchaDialog() {
  return new Promise((resolve) => {
    let done = false, cancelled = false;
    openModal(`<h3>🛡️ Confirme que você não é um robô</h3>
      <p class="muted" style="margin-top:0">Isso protege o site de robôs que enviam mensagens em massa. Leva só alguns segundos.</p>
      <label class="capRow"><input type="checkbox" id="capCheck"><span>Não sou um robô</span></label>
      <div class="capBar hidden" id="capBar"><i id="capFill"></i></div>
      <div class="hint" id="capMsg"></div>
      <div class="actions"><button class="btn2" type="button" id="capCancel">Cancelar</button></div>`);
    const finish = (v) => { if (done) return; done = true; obs.disconnect(); resolve(v); };
    // fechou a janela (fora dela, Esc ou Cancelar): desiste
    const obs = new MutationObserver(() => { if ($("#modal").classList.contains("hidden")) { cancelled = true; finish(null); } });
    obs.observe($("#modal"), { attributes: true, attributeFilter: ["class"] });
    $("#capCancel").addEventListener("click", () => { cancelled = true; closeModal(); });
    $("#capCheck").addEventListener("change", async (e) => {
      const box = e.target;
      if (!box.checked) return;
      box.disabled = true;
      $("#capBar").classList.remove("hidden");
      $("#capMsg").textContent = "Conferindo…";
      try {
        const r = await fetch(S.api + "/api/contact/challenge", { headers: NGROK, cache: "no-store" });
        if (!r.ok) throw new Error("http");
        const ch = await r.json();
        const n = await solveCaptcha(ch, (p) => { $("#capFill").style.width = Math.min(96, Math.round(p * 100)) + "%"; }, () => cancelled);
        if (n === null) { if (!cancelled) { $("#capMsg").textContent = "Não deu certo. Feche e tente de novo."; } return; }
        $("#capFill").style.width = "100%";
        $("#capMsg").textContent = "✅ Confirmado!";
        await sleep(350);
        finish({ salt: ch.salt, number: n, challenge: ch.challenge, signature: ch.signature });
        closeModal();
      } catch {
        $("#capMsg").textContent = "Não consegui confirmar agora. Confira a internet e tente de novo.";
        box.disabled = false; box.checked = false;
      }
    });
  });
}
$("#contactForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("#contactErr"), btn = $("#contactSend");
  const email = $("#contactEmail").value.trim(), subject = $("#contactSubject").value.trim(), message = $("#contactMsg").value.trim();
  err.textContent = "";
  if (!EMAIL_RE.test(email)) { err.textContent = "Digite o seu e-mail completo, por exemplo nome@gmail.com."; $("#contactEmail").focus(); return; }
  if (message.length < 10) { err.textContent = "Escreva a sua mensagem (pelo menos 10 caracteres)."; $("#contactMsg").focus(); return; }
  const answer = await captchaDialog();
  if (!answer) return;
  btn.disabled = true;
  try {
    const res = await timedFetch(S.api + "/api/contact", {
      method: "POST", headers: { ...NGROK, "Content-Type": "application/json" },
      body: JSON.stringify({ email, subject, message, lang: I18N.lang, captcha: answer, ":boom:": $("#contactBoom").value }),
    }, 30000);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const d = data.detail; err.textContent = (d && d.message) || d || "Não consegui enviar agora. Tente de novo."; return; }
    $("#contactForm").reset(); paintContactCount();
    $("#contactForm").classList.add("hidden");
    $("#contactDone").classList.remove("hidden");
  } catch {
    err.textContent = "Sem conexão com o servidor. Tente de novo quando voltar.";
  } finally { btn.disabled = false; }
});
$("#contactAgain").addEventListener("click", () => {
  $("#contactDone").classList.add("hidden"); $("#contactForm").classList.remove("hidden");
});

boot();

/* ---------- 0.27.0: ⭐ VIP List (quem eu acompanho, o que cada um liberou e os convites que recebi) e aba Amigos ---------- */
const VIP_LABEL = { xp: "Gráficos de XP (diária, mensal, trimestral)", skills: "Skills, achievements e charm points",
  hunts: "Lista de hunts (local e data)", hunt_details: "Detalhes de cada hunt (balance, sua parte e XP solo)" };
const brDateTime = (s) => (s ? `${s.slice(0, 10).split("-").reverse().join("/")} ${s.slice(11, 16)}` : "");
const SKILL_LABEL = { magiclevel: "Magic Level", shielding: "Shielding", distancefighting: "Distance", clubfighting: "Club",
  swordfighting: "Sword", axefighting: "Axe", fistfighting: "Fist", fishing: "Fishing", achievements: "Achievements",
  charmpoints: "Charm Points", goshnarstaint: "Goshnar's Taint", loyaltypoints: "Loyalty", dromescore: "Drome",
  bosspoints: "Boss Points", bountypoints: "Bounty", weeklytasks: "Weekly Tasks", phosphorusrecord: "Phosphorus" };
S.vip = { sort: "level", days: 30 };

function vipStateText(e, nome) {
  if (e.state === "pending") return `Aguardando a resposta de ${esc(nome)}.`;
  if (e.state === "declined") return `${esc(nome)} não aceitou compartilhar. Você pode pedir de novo.`;
  if (e.state === "on") return `Compartilhando com você: ${e.effective.map((s) => esc(VIP_LABEL[s])).join(" · ")}.`;
  return "Nada pedido ainda.";
}

function vipEntryCard(e, scopes) {
  const c = e.calc;
  const nome = e.name;
  const boxes = scopes.map((s) => `<label class="check-row"><input type="checkbox" data-vsc="${s}" ${e.requested.includes(s) || e.state === "off" ? "checked" : ""}> ${esc(VIP_LABEL[s])}</label>`).join("");
  const acao = e.state === "on"
    ? `<button class="btn2" data-voff="${e.id}" style="margin:0">Desligar</button>`
    : e.state === "pending" ? ""
    : `<button class="btn" data-vreq="${e.id}" style="margin:0">Pedir permissão</button>`;
  return `<div class="card" style="margin-bottom:10px" data-vcard="${e.id}">
    <div class="row" style="justify-content:space-between;flex-wrap:wrap">
      <a href="#" data-vview="${esc(nome)}" style="font-weight:700;color:inherit;text-decoration:underline dotted">${esc(nome)}</a>
      <button class="btn2" data-vdel="${esc(nome)}" style="margin:0;padding:4px 10px;font-size:12px">Remover</button>
    </div>
    <div class="muted" style="font-size:13px;margin-top:4px">${e.vocation ? esc(e.vocation) : "–"}${e.level ? " · level " + e.level : ""}${c ? ` · HP ${fmt(c.hp)} · Mana ${fmt(c.mana)} · Cap ${fmt(c.cap)} oz` : ""}</div>
    <div class="row" style="gap:16px;margin-top:8px;flex-wrap:wrap">
      <div><div class="muted" style="font-size:12px">XP ganha 30 dias</div><b>${e.xp.d30.gain == null ? "–" : fmt(e.xp.d30.gain)}</b></div>
      <div><div class="muted" style="font-size:12px">XP ganha 90 dias</div><b>${e.xp.d90.gain == null ? "–" : fmt(e.xp.d90.gain)}</b></div>
      ${e.hunts30 != null ? `<div><div class="muted" style="font-size:12px">Hunts em 30 dias</div><b>${e.hunts30}</b></div>` : ""}
    </div>
    <div class="hint" style="margin-top:8px">${vipStateText(e, nome)}</div>
    ${e.state === "pending" ? "" : `<div style="margin-top:6px">${boxes}</div>`}
    <div class="row" style="margin-top:8px">${acao}</div>
  </div>`;
}

// 0.27.1: quando o personagem adicionado não tem cadastro no site, oferece convidar pelo WhatsApp.
// O DDD e o número são usados só para montar o link wa.me na hora; nada é guardado nem enviado pelo site.
function inviteMessage(nome) {
  return `Oi! Estou usando o 4rt3mi5 (artemishunt.com.br) para acompanhar hunts e XP no Tibia. ` +
    `Faz o seu cadastro e vincula o seu personagem ${nome}, assim a gente consegue ver as hunts juntos. Bora?`;
}

function closeInviteBox() {
  document.getElementById("inviteBox")?.remove();
}

function openInviteBox(nome) {
  closeInviteBox();
  const box = document.createElement("div");
  box.id = "inviteBox";
  box.setAttribute("style", "position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:70;overflow:auto;padding:16px");
  box.innerHTML = `<div class="card" style="max-width:460px;margin:40px auto;position:relative">
      <b>${esc(nome)} ainda não tem cadastro no site</b>
      <p class="hint" style="white-space:normal;margin-top:6px">Quer convidar essa pessoa para o 4rt3mi5? Ela vai poder ver as hunts, a divisão de loot e os rankings de vocês, e responder ao pedido de VIP assim que vincular o personagem.</p>
      <div data-inv-step="ask" class="row" style="margin-top:10px;gap:8px;flex-wrap:wrap">
        <button class="btn" data-inv-yes style="margin:0">Sim, convidar</button>
        <button class="btn2" data-inv-close style="margin:0">Não, obrigado</button>
      </div>
      <div data-inv-step="phone" class="hidden" style="margin-top:12px">
        <label class="muted" style="font-size:13px">Celular com WhatsApp</label>
        <div class="row" style="gap:8px;margin-top:4px">
          <input id="invDdd" inputmode="numeric" maxlength="2" placeholder="DDD" style="width:72px">
          <input id="invNum" inputmode="numeric" maxlength="11" placeholder="Número" class="grow">
        </div>
        <div class="err hidden" id="invErr" style="margin-top:6px"></div>
        <label class="muted" style="font-size:13px;display:block;margin-top:12px">Mensagem pronta (pode editar)</label>
        <textarea id="invMsg" rows="4" style="width:100%;margin-top:4px">${esc(inviteMessage(nome))}</textarea>
        <div class="row" style="margin-top:10px;gap:8px;flex-wrap:wrap">
          <button class="btn" data-inv-wa style="margin:0">Abrir WhatsApp com a mensagem</button>
          <button class="btn2" data-inv-copy style="margin:0">Copiar mensagem</button>
        </div>
        <p class="hint" style="white-space:normal;margin-top:8px">O WhatsApp abre com a mensagem pronta; você confere e envia por lá.</p>
      </div>
    </div>`;
  box.addEventListener("click", (ev) => {
    if (ev.target === box || ev.target.closest("[data-inv-close]")) return closeInviteBox();
    if (ev.target.closest("[data-inv-yes]")) {
      box.querySelector('[data-inv-step="ask"]').classList.add("hidden");
      box.querySelector('[data-inv-step="phone"]').classList.remove("hidden");
      return box.querySelector("#invDdd").focus();
    }
    if (ev.target.closest("[data-inv-copy]")) {
      const txt = box.querySelector("#invMsg").value;
      const btn = ev.target.closest("[data-inv-copy]");
      const marca = () => { btn.textContent = "Copiado!"; };
      navigator.clipboard?.writeText(txt).then(marca, () => box.querySelector("#invMsg").select());
      return;
    }
    if (ev.target.closest("[data-inv-wa]")) {
      const ddd = box.querySelector("#invDdd").value.replace(/\D/g, "");
      const num = box.querySelector("#invNum").value.replace(/\D/g, "");
      const err = box.querySelector("#invErr");
      if (!/^\d{2}$/.test(ddd) || !/^\d{8,9}$/.test(num)) {
        err.textContent = "Informe o DDD (2 números) e o celular (8 ou 9 números).";
        err.classList.remove("hidden");
        return;
      }
      err.classList.add("hidden");
      const texto = encodeURIComponent(box.querySelector("#invMsg").value);
      window.open(`https://wa.me/55${ddd}${num}?text=${texto}`, "_blank", "noopener");
    }
  });
  document.body.appendChild(box);
}

async function loadVip() {
  let d;
  try { d = await api("GET", "/api/vip/list"); }
  catch (err) { if (err.status !== 401) $("#vipList").innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  $("#vipIncoming").innerHTML = d.incoming.map((c) => `
    <div class="card" style="margin-bottom:10px" data-inv="${c.id}">
      <b>${esc(c.owner_char || "Alguém")}</b> quer ver estas informações de ${esc(c.target_name)}:
      <div style="margin-top:8px">${d.scopes.filter((s) => c.requested.includes(s)).map((s) =>
        `<label class="check-row"><input type="checkbox" data-isc="${s}" checked> ${esc(VIP_LABEL[s])}</label>`).join("")}</div>
      <div class="hint">Desmarque o que não quer compartilhar. Você pode mudar isso depois.</div>
      <div class="row" style="margin-top:8px"><button class="btn" data-vacc="${c.id}" style="margin:0">Aceitar</button><button class="btn2" data-vdec="${c.id}" style="margin:0">Recusar</button></div>
    </div>`).join("");
  $("#vipList").innerHTML = d.entries.length
    ? d.entries.map((e) => vipEntryCard(e, d.scopes)).join("")
    : `<p class="muted">Sua VIP List está vazia. Adicione um nick acima.</p>`;
}

async function loadAmigos() {
  const body = $("#amigosBody");
  document.querySelectorAll("[data-asort]").forEach((b) => b.classList.toggle("on", b.dataset.asort === S.vip.sort));
  document.querySelectorAll("[data-adays]").forEach((b) => b.classList.toggle("on", +b.dataset.adays === S.vip.days));
  body.innerHTML = skeleton("stack");
  let d;
  try { d = await api("GET", `/api/rank/amigos?days=${S.vip.days}&sort=${S.vip.sort}&world=${encodeURIComponent(S.rworld)}`); }
  catch (err) { if (err.status !== 401) body.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  paintWorldSelect($("#amigosWorld"), d.worlds || []);
  if (!d.rows.length) { body.innerHTML = `<p class="muted">${d.world ? esc(tf("Nenhum personagem de {0} aqui ainda.", d.world)) : "Nenhum personagem ainda."}</p>`; return; }
  const W = "white-space:normal";
  body.innerHTML = `<div class="table-wrap"><table style="table-layout:fixed;width:100%"><tr><th style="width:44px;${W}">#</th><th style="${W};text-align:left">Personagem</th><th style="text-align:right;width:112px;${W}">XP ${d.days} dias</th></tr>
    ${d.rows.map((r, i) => `<tr><td style="${W}">${i + 1}</td>
      <td style="${W};text-align:left"><a href="#" data-amigo="${esc(r.name)}" data-origem="${r.origin}" style="font-weight:600;color:inherit;text-decoration:underline dotted">${esc(r.name)}</a>
        <div class="muted" style="font-size:12px">${r.vocation ? esc(r.vocation) : "–"}${r.level ? " · level " + r.level : ""}</div>
        <div class="muted" style="font-size:11px">${Object.entries(r.values).map(([k, v]) => `${esc(SKILL_LABEL[k] || k)} ${fmt(v)}`).join(" · ")}</div></td>
      <td style="text-align:right;${W}">${r.xp_gain == null ? "–" : `<b>${fmt(r.xp_gain)}</b>`}</td></tr>`).join("")}</table></div>`;
}

async function openVipView(nome) {
  $("#playerModal").classList.remove("hidden");
  $("#pmTitle").textContent = nome;
  $("#pmBody").innerHTML = skeleton("stack");
  let d;
  try { d = await api("GET", `/api/vip/view/${encodeURIComponent(nome)}`); }
  catch (err) { $("#pmBody").innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  const c = d.calc, t = d.details;
  let html = `<div class="row" style="flex-wrap:wrap;gap:14px">
      <div><div class="muted">Vocação</div><b>${esc(d.vocation || "–")}</b></div>
      <div><div class="muted">Level</div><b>${d.level ?? "–"}</b></div>
      <div><div class="muted">Mundo</div><b>${esc(d.world || "–")}</b></div>
      ${c ? `<div><div class="muted">HP</div><b>${fmt(c.hp)}</b></div><div><div class="muted">Mana</div><b>${fmt(c.mana)}</b></div><div><div class="muted">Cap</div><b>${fmt(c.cap)} oz</b></div>` : ""}
    </div>
    <div class="row" style="gap:14px;margin-top:12px;flex-wrap:wrap">
      <div><div class="muted">XP ganha 30 dias</div><b>${d.xp.d30.gain == null ? "–" : fmt(d.xp.d30.gain)}</b></div>
      <div><div class="muted">XP ganha 90 dias</div><b>${d.xp.d90.gain == null ? "–" : fmt(d.xp.d90.gain)}</b></div>
      ${d.hunts30 != null ? `<div><div class="muted">Hunts em 30 dias</div><b>${d.hunts30}</b></div>` : ""}
    </div>`;
  if (t.xp) {
    html += `<div class="seg" style="margin-top:14px"><button data-pmc="daily" class="on">Diária</button><button data-pmc="monthly">Mensal</button><button data-pmc="quarterly">Trimestral</button></div><div id="pmSvg" style="margin-top:8px"></div>`;
    S.pm = { charts: t.xp };
  }
  if (t.skills) {
    html += `<h3 style="margin-top:16px">Skills e achievements</h3><div class="hint" style="white-space:normal">${Object.entries(t.skills).map(([k, v]) => `${esc(SKILL_LABEL[k] || k)}: <b>${fmt(v)}</b>`).join(" · ")}</div>`;
  }
  if (t.hunts) {
    const det = !!t.solo_sessions;
    html += `<h3 style="margin-top:16px">Hunts (30 dias)</h3>` + (t.hunts.length
      ? `<div class="table-wrap"><table><tr><th>Quando</th><th>Local</th>${det ? "<th style='text-align:right'>Sua parte</th><th style='text-align:right'>Balance</th>" : ""}</tr>
          ${t.hunts.map((h) => `<tr><td style="white-space:normal">${brDateTime(h.started_at)}</td><td style="white-space:normal">${esc(h.place || "sem local")}</td>${det ? `<td style="text-align:right">${h.profit_each == null ? "–" : fmt(h.profit_each)}</td><td style="text-align:right">${h.balance == null ? "–" : fmt(h.balance)}</td>` : ""}</tr>`).join("")}</table></div>`
      : `<p class="muted">Nenhuma hunt nos últimos 30 dias.</p>`);
  }
  if (t.solo_sessions) {
    html += `<h3 style="margin-top:16px">Hunts solo (30 dias)</h3>` + (t.solo_sessions.length
      ? `<div class="table-wrap"><table><tr><th>Quando</th><th style="text-align:right">XP</th><th style="text-align:right">Balance</th></tr>
          ${t.solo_sessions.map((s) => `<tr><td style="white-space:normal">${brDateTime(s.started_at)}</td><td style="text-align:right">${fmt(s.xp)}</td><td style="text-align:right">${fmt(s.balance)}</td></tr>`).join("")}</table></div>`
      : `<p class="muted">Nenhuma sessão solo nos últimos 30 dias.</p>`);
  }
  if (!Object.keys(t).length) {
    html += `<p class="muted" style="margin-top:14px">Ainda não há detalhes liberados por ${esc(nome)}.</p>`;
  }
  $("#pmBody").innerHTML = html;
  if (t.xp) paintPmChart("daily");
}

document.addEventListener("click", async (e) => {
  const add = e.target.closest("#vipAddBtn"), del = e.target.closest("[data-vdel]"), req = e.target.closest("[data-vreq]"),
    off = e.target.closest("[data-voff]"), acc = e.target.closest("[data-vacc]"), dec = e.target.closest("[data-vdec]"),
    vv = e.target.closest("[data-vview]"), am = e.target.closest("[data-amigo]"), so = e.target.closest("[data-asort]"),
    ad = e.target.closest("[data-adays]");
  try {
    if (add) {
      const nome = ($("#vipAddName").value || "").trim();
      if (!nome) return;
      const feito = await api("POST", "/api/vip/add", { character: nome });
      $("#vipAddName").value = "";
      if (feito && feito.has_account === false) openInviteBox(nome);
      return loadVip();
    }
    if (del) {
      if (!confirm(`Remover ${del.dataset.vdel} da sua VIP List?`)) return;
      await api("DELETE", `/api/vip/${encodeURIComponent(del.dataset.vdel)}`);
      return loadVip();
    }
    if (req) {
      const card = req.closest("[data-vcard]");
      const scopes = [...card.querySelectorAll("[data-vsc]:checked")].map((x) => x.dataset.vsc);
      if (!scopes.length) return alert("Escolha pelo menos uma informação para pedir.");
      const nome = card.querySelector("[data-vview]").dataset.vview;
      await api("POST", `/api/vip/${encodeURIComponent(nome)}/share`, { on: true, scopes });
      return loadVip();
    }
    if (off) {
      const nome = off.closest("[data-vcard]").querySelector("[data-vview]").dataset.vview;
      if (!confirm(`Tem certeza que quer desligar o compartilhamento com ${nome}? Os detalhes somem da sua tela agora. Se ligar de novo, vai precisar pedir permissão outra vez.`)) return;
      await api("POST", `/api/vip/${encodeURIComponent(nome)}/share`, { on: false, scopes: [] });
      return loadVip();
    }
    if (acc || dec) {
      const card = (acc || dec).closest("[data-inv]");
      const id = (acc || dec).dataset.vacc || (acc || dec).dataset.vdec;
      const scopes = [...card.querySelectorAll("[data-isc]:checked")].map((x) => x.dataset.isc);
      await api("POST", `/api/vip/invites/${id}/answer`, { accept: !!acc, scopes: acc ? scopes : [] });
      return loadVip();
    }
    if (vv) { e.preventDefault(); return openVipView(vv.dataset.vview); }
    if (am) { e.preventDefault(); return am.dataset.origem === "mine" ? openPlayer(am.dataset.amigo) : openVipView(am.dataset.amigo); }
    if (so) { S.vip.sort = so.dataset.asort; return loadAmigos(); }
    if (ad) { S.vip.days = +ad.dataset.adays; return loadAmigos(); }
  } catch (err) {
    if (err.status !== 401) alert(err.message);
  }
});
