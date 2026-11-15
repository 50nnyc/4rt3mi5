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
}
$("#showLogin").addEventListener("click", () => showLogin("login"));
$("#showRegister").addEventListener("click", () => showLogin("register"));

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
    $("#freeDays").textContent = s.free_days;
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
  showVerify();
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
  const label = () => { btn.innerHTML = `<span class="flag">${flagOf(cur.iso)}</span> +${esc(cur.dial)} <span class="muted">▾</span>`; btn.title = cur.name; };
  let shown = [];
  const draw = () => {
    const q = plain(search.value.trim()), digits = q.replace(/\D/g, "");
    // procura em QUALQUER parte do nome ("ile" acha Chile, Brasil não), na sigla e no código do país
    shown = COUNTRIES.filter((c) => !q || plain(c.name).includes(q) || c.iso.toLowerCase() === q || (digits && c.dial.startsWith(digits)));
    list.innerHTML = shown.length ? shown.map((c, i) => `<button type="button" role="option" data-cc="${i}" class="${c === cur ? "on" : ""}">
        <span class="flag">${flagOf(c.iso)}</span> <span class="ccName">${esc(c.name)}</span> <span class="muted">+${esc(c.dial)}</span></button>`).join("")
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
    if (e.key === "Enter") { e.preventDefault(); if (shown[0]) pick(shown[0]); }
    if (e.key === "Escape") { close(); btn.focus(); }
  });
  list.addEventListener("click", (e) => { const b = e.target.closest("[data-cc]"); if (b) pick(shown[+b.dataset.cc]); });
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
      Enviaremos uma mensagem ao administrador para entrar em contato com você para recuperação ${lostLogin ? "da sua conta" : "do código"}.
      Favor colocar seu número de WhatsApp para podermos entrar em contato.
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
    <div class="hint">Vale até ${esc(new Date(d.expires_at).toLocaleDateString("pt-BR"))} e já está guardada na sua conta.
      Agora confirme o seu personagem.</div>
    <button class="btn" id="storeUse" type="button">Continuar</button></div>`;
  $("#storeUse").onclick = async () => {
    S.key = d.key; S.keyExpires = d.expires_at; S.token = null;
    await kv.set("key", d.key); await kv.set("token", null);
    showVerify();
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
function verifyWidget(el, { title, intro = "", onDone, placeholder = "Ex.: Atx Buubo" }) {
  let timer = null;
  const stop = () => { if (timer) clearInterval(timer); timer = null; };
  stop();
  el.innerHTML = `
    <form class="vf">
      <label class="muted">${esc(title)}</label>
      ${intro ? `<div class="hint" style="margin:4px 0 0">${esc(intro)}</div>` : ""}
      <input class="vchar" placeholder="${esc(placeholder)}" autocomplete="off" autocapitalize="words" spellcheck="false" style="margin-top:6px">
      <button class="btn" type="submit">Gerar código de verificação</button>
      <div class="err verr"></div>
      <div class="vrec"></div>
    </form>`;
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
        recoveryForm(rec, { reason: "char_taken", character: name, intro: "Este character já possui código de acesso." });
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
          recoveryForm(err, { reason: "char_taken", character: v.character, intro: "Este character já possui código de acesso." });
        }
        else if (e.status === 409) { status.textContent = `Última conferência: ${new Date().toLocaleTimeString("pt-BR")}`; if (manual) err.innerHTML = `${esc(e.message)}<div class="hint">${esc(e.hint || "")}</div>`; }
        else if (e.status !== 401) { status.textContent = ""; if (manual) err.textContent = e.message; }
      } finally { busy = false; btn.disabled = false; }
    }
    btn.addEventListener("click", () => check(true));
    el.querySelector(".vother").addEventListener("click", () => { stop(); verifyWidget(el, { title, intro, onDone, placeholder }); });
    timer = setInterval(() => check(false), 30000);
  }
}

/* ---------- nickname ---------- */
async function showNick(prefill = true) {
  showOnly("nickScreen");
  $("#nickErr").textContent = "";
  $("#nickBack").classList.toggle("hidden", !S.char);
  const last = prefill ? ((await kv.get("nick")) || (S.me && S.me.main_char)) : null;
  if (last && !$("#nickInput").value) $("#nickInput").value = last;
  setTimeout(() => $("#nickInput").focus(), 50);
}
$("#nickForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#nickInput").value.trim().replace(/\s+/g, " ");
  if (!name) return;
  const btn = e.currentTarget.querySelector("button"); btn.disabled = true; $("#nickErr").textContent = "";
  try {
    S.char = await api("GET", `/api/character/${encodeURIComponent(name)}`);
    S.nick = S.char.name;
    await kv.set("nick", S.nick);
    openApp();
  } catch (err) {
    if (err.status !== 401) $("#nickErr").textContent = err.message;
  } finally { btn.disabled = false; }
});

/* ---------- app / menu ---------- */
function showOnly(id) {
  for (const s of ["loginScreen", "expiredScreen", "keyScreen", "verifyScreen", "nickScreen", "app"]) $("#" + s).classList.toggle("hidden", s !== id);
  // botão de som: no cabeçalho dentro do app; flutuando no canto nas outras telas
  const snd = $("#sound"), inApp = id === "app";
  snd.classList.toggle("floating", !inApp);
  (inApp ? $("#soundSlot") : document.body).appendChild(snd);
  if (!inApp) Music.forPage(null);
}
function openApp() {
  $("#topWho").textContent = S.nick;
  $("#brandHome").dataset.nick = S.nick;
  $("#drawerName").textContent = S.nick;
  $("#drawerInfo").textContent = `Level ${S.char.level} · ${S.char.vocation} · ${S.char.world}`;
  updateDrawerFoot();
  $("#lootResult").innerHTML = ""; $("#stackResult").innerHTML = ""; $("#bossResult").innerHTML = ""; $("#bossAsk").innerHTML = "";
  showOnly("app");
  S.navStack = [];
  S.page = null;
  go("home", { noPush: true });
  setTimeout(offerInstall, 2500);
  setTimeout(flushDrafts, 1500);
}
function openDrawer() { $("#drawer").classList.add("open"); $("#scrim").classList.add("open"); }
function closeDrawer() { $("#drawer").classList.remove("open"); $("#scrim").classList.remove("open"); }
$("#burger").addEventListener("click", openDrawer);
$("#scrim").addEventListener("click", closeDrawer);
document.querySelectorAll("[data-page]").forEach((b) => b.addEventListener("click", () => {
  closeDrawer();
  if (b.dataset.btab && b.dataset.btab !== "all") S.btab = b.dataset.btab;
  if (b.dataset.page === "boss" && S.page === "boss") { showBossTab(S.btab); return; }
  go(b.dataset.page);
}));
$("#changeNick").addEventListener("click", () => { closeDrawer(); $("#nickInput").value = ""; showNick(false); });
$("#nickBack").addEventListener("click", () => showOnly("app"));
$("#brandHome").addEventListener("click", () => { closeDrawer(); if (S.page !== "home") go("home"); else window.scrollTo(0, 0); });
$("#backBtn").addEventListener("click", goBack);

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
  if (st.htab) S.htab = st.htab;
  go(st.page, { noPush: true });
}
window.addEventListener("popstate", () => {
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
  updateBack();
  document.querySelectorAll("[data-page]").forEach((b) => b.classList.toggle("active", b.dataset.page === page
    && (!b.dataset.btab || b.dataset.btab === "all" || b.dataset.btab === S.btab)));
  $("#pageHome").classList.toggle("hidden", page !== "home");
  $("#pageBoss").classList.toggle("hidden", page !== "boss");
  $("#pageLoot").classList.toggle("hidden", page !== "loot");
  $("#pageStack").classList.toggle("hidden", page !== "stack");
  $("#pageChars").classList.toggle("hidden", page !== "chars");
  $("#pageHunts").classList.toggle("hidden", page !== "hunts");
  $("#pageNews").classList.toggle("hidden", page !== "news");
  $("#pageAch").classList.toggle("hidden", page !== "ach");
  $("#pageRank").classList.toggle("hidden", page !== "rank");
  Music.forPage(page);
  if (page === "rank") loadRank();
  if (page === "news") loadNews();
  if (page === "ach") loadAch();
  window.scrollTo(0, 0);
  if (page === "home") loadHome();
  if (page === "stack") { initStackPicker(); loadStack(); }
  if (page === "boss") { showBossTab(S.btab); loadBoss(); }
  if (page === "hunts") loadHunts();
  if (page === "chars") loadChars();
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
  const ref = huntRef(h), canMark = isMine(t.payer) || isMine(t.receiver);
  if (t.paid_at) return `<span class="pos" style="font-size:13px">✔ pago ${esc(new Date(t.paid_at).toLocaleDateString("pt-BR"))}</span>
    ${canMark ? `<button class="link" style="font-size:13px" data-paid="${ref}" data-payer="${esc(t.payer)}" data-receiver="${esc(t.receiver)}" data-set="0">desfazer</button>` : ""}`;
  if (!canMark) return `<span class="muted" style="font-size:13px">⏳ falta pagar</span>`;
  return `<button class="btn2" style="padding:4px 10px; font-size:13px" data-paid="${ref}" data-payer="${esc(t.payer)}" data-receiver="${esc(t.receiver)}" data-set="1">${t.receiver.toLowerCase() !== (S.nick || "").toLowerCase() && isMine(t.payer) ? "✔ Já paguei" : "✔ Recebi"}</button>`;
}
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
    + h.transfers.map((t) => `<div class="tx"><div class="row"><span><b>${esc(t.payer)}</b> → <b>${esc(t.receiver)}</b></span><b class="gold">${fmt(t.amount)}</b></div>
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
  if (S.page === "loot") { $("#lootResult").innerHTML = huntCard(h, S.nick, "Resultado"); paintVocations($("#lootResult")); }
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
  } catch (err) {
    btn.disabled = false;
    if (err.status === 401) return;
    const box = document.querySelector(`[data-rules-err="${ref}"]`);
    if (save && box) box.textContent = err.message; else alert(err.message);
  }
});
function partyTable(h, name) {
  const key = (name || "").toLowerCase();
  return `<div class="table-wrap"><table><tr><th>Jogador</th><th>Loot</th><th>Supplies</th><th>Balance</th><th>Damage</th><th>Healing</th><th>Acerto</th></tr>
    ${h.players.map((p) => `<tr class="${p.name.toLowerCase() === key ? "me" : ""}">
      <td>${vdot(p.name)}${esc(p.name)}${p.is_leader ? " 👑" : ""}</td><td>${kk(p.loot)}</td><td>${kk(p.supplies)}</td><td>${kk(p.balance)}</td>
      <td>${kk(p.damage)}</td><td>${kk(p.healing)}</td>
      <td class="${p.diff > 0 ? "neg" : p.diff < 0 ? "pos" : ""}">${p.diff > 0 ? "paga " + kk(p.diff) : p.diff < 0 ? "recebe " + kk(-p.diff) : "—"}</td></tr>`).join("")}
  </table></div>`;
}
function huntCard(h, name, title) {
  const cls = h.profit_each >= 0 ? "gold" : "neg";
  return `<div class="card">
    <div class="muted">${esc(title)} · ${when(h.started_at)} · ${dur(h.duration_seconds)} · ${h.players_count} jogadores</div>
    <div style="margin-top:10px" class="muted">Rendeu para cada um</div>
    <div class="big ${cls}" data-count="${h.profit_each}" data-suffix=" gp">${fmt(h.profit_each)} gp</div>
    <div class="muted"><b class="${cls}">${fmt(h.profit_each_per_hour)} gp/h</b> por pessoa · total da PT ${fmt(h.balance)} gp</div>
    ${rulesLine(h)}
    ${actionBox(view(h, name), h)}
    ${chartToggle(h, name)} ${shareButton("hunt", h)}
    <details style="margin-top:4px"><summary class="link">Transferências e detalhes da PT ▾</summary>
      <h2>Transferências</h2>${transfersBox(h)}
      <h2>Jogadores</h2>${partyTable(h, name)}
      <div class="muted" style="margin-top:8px">Loot ${fmt(h.loot)} · Supplies ${fmt(h.supplies)} · Loot type ${esc(h.loot_type || "—")}</div>
      ${rulesBox(h)}
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
function historyItem(h, name) {
  const v = view(h, name);
  return `<details class="card"><summary>
      <div class="row"><b>${when(h.started_at)}</b>${settleTag(v)}</div>
      <div class="row muted"><span>${dur(h.duration_seconds)} · ${h.players_count} jogadores${h.pending ? ` · ⏳ ${h.pending} a pagar` : ""}</span>
        <span class="${h.profit_each >= 0 ? "gold" : "neg"}">${kk(h.profit_each)} cada (${kk(h.profit_each_per_hour)}/h)</span></div>
    </summary>${rulesLine(h)}${actionBox(v, h)}${chartToggle(h, name)} ${shareButton("hunt", h)}<h2>Transferências</h2>${transfersBox(h)}${partyTable(h, name)}${rulesBox(h)}${deleteButton(h)}</details>`;
}
function statGrid(items) {
  return `<div class="stats">${items.map(([k, v, cls]) => `<div class="stat"><span class="muted">${k}</span><b class="${cls || ""}">${v}</b></div>`).join("")}</div>`;
}

/* ---------- novidades (changelog) ---------- */
async function fetchNews() {
  if (!S.news) S.news = await api("GET", "/api/changelog").catch(() => null);
  return S.news;
}
function releaseCard(r, highlight) {
  const d = r.date ? new Date(r.date + "T12:00:00").toLocaleDateString("pt-BR") : "";
  return `<div class="card${highlight ? " news-new" : ""}">
    <div class="row"><b>Versão ${esc(r.version)}${r.title ? " · " + esc(r.title) : ""}</b><span class="muted" style="font-size:13px">${esc(d)}</span></div>
    <ul class="news-list">${r.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></div>`;
}
async function loadNews() {
  const d = await fetchNews();
  if (!d) { $("#newsList").innerHTML = `<div class="err">Não foi possível carregar as novidades.</div>`; return; }
  $("#newsList").innerHTML = d.releases.map((r, i) => releaseCard(r, i === 0)).join("");
  await markNewsSeen();
}
async function markNewsSeen() {
  const d = await fetchNews();
  if (d && d.releases.length) await kv.set("seen_version", d.releases[0].version);
  $("#newsDot").classList.add("hidden");
}
/** Aviso no Início quando há versão nova que o usuário ainda não viu. */
async function newsNotice() {
  const d = await fetchNews();
  if (!d || !d.releases.length) return "";
  const latest = d.releases[0];
  const seen = await kv.get("seen_version");
  if (seen === latest.version) return "";
  $("#newsDot").classList.remove("hidden");
  return `<div class="card news-new" id="newsNotice">
    <div class="row"><b>🎉 Novidades da versão ${esc(latest.version)}</b><button class="link" id="newsClose" aria-label="Fechar aviso">✕</button></div>
    <ul class="news-list">${latest.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
    <button class="link" data-page-link="news">Ver todas as versões →</button></div>`;
}
document.addEventListener("click", async (e) => {
  if (e.target.closest("#newsClose")) { $("#newsNotice").remove(); await markNewsSeen(); }
  const link = e.target.closest("[data-page-link]");
  if (link) go(link.dataset.pageLink);
});

/* ---------- página inicial ---------- */
const EXPIRY_WARN_DAYS = 3;
/** Aviso de código de acesso vencendo (3 dias antes). */
function expiryNotice(streak) {
  const exp = (streak && streak.expires_at) || (S.me && S.me.expires_at) || S.keyExpires;
  if (!exp) return "";
  const ms = new Date(exp) - Date.now();
  if (ms > EXPIRY_WARN_DAYS * 86400000) return "";
  const days = Math.floor(ms / 86400000);
  const whenTxt = days <= 0 ? "em menos de 24 horas" : days === 1 ? "em 1 dia" : `em ${days} dias`;
  return `<div class="banner bad"><b>⏰ Seu código de acesso vence ${whenTxt}</b> (${esc(new Date(exp).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }))}).
    <div class="hint">Renove grátis por mais 7 dias no menu ☰ → <b>🔑 Renove 7 dias grátis da sua chave</b>. Depois que vence, o código e os aparelhos liberados são apagados
      (suas hunts e sessões continuam salvas). Enviar uma hunt por dia também ajuda: a cada 30 dias seguidos o código ganha +7 dias.</div></div>`;
}
async function loadHome() {
  const el = $("#pageHome");
  el.innerHTML = skeleton("home");
  let data;
  try { data = await api("GET", `/api/hunts/${encodeURIComponent(S.nick)}`); }
  catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
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
  const pendingCard = owe || due ? `<div class="card"><b>💸 Acertos pendentes</b>
    ${owe ? `<div class="neg" style="margin-top:4px">Você ainda deve ${fmt(owe)} gp em ${oweN} ${oweN === 1 ? "lootsplit" : "lootsplits"}.</div>` : ""}
    ${due ? `<div class="pos" style="margin-top:4px">Falta receber ${fmt(due)} gp de ${dueN} ${dueN === 1 ? "lootsplit" : "lootsplits"}.</div>` : ""}
    <div class="hint">Depois de transferir no banco, toque em "✔ Já paguei" na hunt. Quem recebe também pode marcar "✔ Recebi".</div></div>` : "";
  const [notice, streak] = await Promise.all([newsNotice().catch(() => ""), api("GET", "/api/streak").catch(() => null)]);
  const n = (v, suffix = "") => `<span data-count="${v}" data-suffix="${suffix}">${fmt(v)}${suffix}</span>`;
  el.innerHTML = `${expiryNotice(streak)}${notice}
    ${pendingCard}
    ${streak ? streakTeaser(streak) : ""}
    ${hunts.length ? huntCard(hunts[0], S.nick, "Última hunt") : emptyState("home")}
    ${hunts.length ? `<h2>Totais</h2>
    ${statGrid([["Hunts", n(hunts.length)], ["Profit total", n(total, " gp"), total >= 0 ? "gold" : "neg"],
                ["Tempo de hunt", dur(secs)], ["Média por hora", n(secs ? Math.round(total * 3600 / secs) : 0, " gp")],
                ["Total transferido", n(toPay, " gp"), toPay ? "neg" : ""], ["Total recebido", n(toGet, " gp"), toGet ? "pos" : ""]])}
    <h2>🏅 Ranking da PT</h2><div class="card" id="ptRank"></div>
    <h2>Todas as hunts (${hunts.length})</h2>
    ${hunts.length > 1 ? hunts.slice(1).map((h) => historyItem(h, S.nick)).join("") : `<p class="muted">Nenhuma hunt anterior.</p>`}` : ""}`;
  countUp(el);
  if (hunts.length) {
    renderPtRank();
    const names = [...new Set(hunts.flatMap((h) => h.players.map((p) => p.name)))];
    ensureVocations(names).then((changed) => { if (changed && S.page === "home") { renderPtRank(); paintVocations(el); } });
  }
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
$("#lootBtn").addEventListener("click", async () => {
  const raw = $("#lootText").value.trim();
  if (!raw) return;
  const btn = $("#lootBtn"); btn.disabled = true; $("#lootErr").textContent = ""; $("#lootResult").innerHTML = "";
  try {
    const r = await api("POST", "/api/lootsplit", { raw_text: raw, nickname: S.nick });
    $("#lootResult").innerHTML = `<div class="banner ok">${r.created ? "Hunt enviada ✔ Todos da PT já podem ver no app." : "Essa hunt já estava salva ✔"}</div>`
      + huntCard(r.hunt, S.nick, "Resultado");
    countUp($("#lootResult"));
    paintVocations($("#lootResult"));
    ensureVocations(r.hunt.players.map((p) => p.name)).then((c) => c && paintVocations($("#lootResult")));
    $("#lootText").value = "";
    celebrateRewards(r.rewards);
    if (r.created) checkAchievements();
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
  const placeLine = s.place ? `📍 ${esc(s.place.name)}` : (s.can_delete ? `<span class="neg">📍 sem hunt definida</span>` : "📍 —");
  return `<details class="card"><summary>
      <div class="row"><b>${when(s.started_at)}</b><span class="gold">${kk(s.xp)} XP</span></div>
      <div class="row muted"><span>${dur(s.duration_seconds)}${s.loot_value ? " · loot ≈ " + kk(s.loot_value) : ""}</span>
        <span class="${s.balance >= 0 ? "pos" : "neg"}">balance ${kk(s.balance)}</span></div>
      <div class="muted" style="font-size:13px">${placeLine} · lucro líquido real <b class="${s.net_profit >= 0 ? "pos" : "neg"}">${kk(s.net_profit)}</b></div>
    </summary>
    ${s.can_delete ? `<div style="margin-top:10px"><span class="muted">${s.place ? "Trocar hunt" : "Definir hunt"}:</span>
      <div class="picker-slot" data-session-place="${s.id}" style="margin-top:4px"></div></div>` : ""}
    <div style="margin-top:10px">${statGrid([
      ["XP", fmt(s.xp)], ["Raw XP", fmt(s.raw_xp)], ["Balance", fmt(s.balance) + " gp"], ["Supplies", fmt(s.supplies) + " gp"],
      ["Damage", fmt(s.damage)], ["Damage/h", fmt(s.damage_h)], ["Healing", fmt(s.healing)], ["Healing/h", fmt(s.healing_h)],
    ])}</div>
    ${s.loot.length ? `<h2>Itens coletados</h2>${itemList(s.loot, 999)}` : ""}
    ${s.kills.length ? `<h2>Criaturas mortas</h2>${killChips(s.kills)}` : ""}
    <div style="margin-top:10px">${shareButton("solo", s)}</div>
    ${s.can_delete ? `<div style="margin-top:10px"><button class="danger-link" data-del-solo="${s.id}">🗑 Apagar esta sessão</button></div>` : ""}</details>`;
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
  const title = String(name).split(" ").map((w, i) => (i && small.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1))).join(" ");
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
  let d;
  try { d = await api("GET", `/api/stacker/${encodeURIComponent(S.nick)}?period=${S.period}`); }
  catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  S.prices = d.prices || {};
  S.stack = d;
  if (!d.sessions.length) {
    el.innerHTML = emptyState("stack");
    return d;
  }
  el.innerHTML = `
    ${alertsBlock(d)}
    ${goalsBlock(d)}
    ${weeklyBlock(d.sessions)}
    <h2>Loot e criaturas</h2>${periodBlock(d.period)}
    ${forecastBlock(d.forecast)}
    <details class="card"><summary class="row"><b>🏆 Recordes pessoais</b><span class="muted">▾</span></summary>${recordsBlock(d.records)}</details>
    <details class="card"><summary class="row"><b>🧺 Lista de venda</b><span class="muted">${d.sell.filter((i) => i.count).length} itens ▾</span></summary>${sellBlock(d)}</details>
    <h2>Totais do dia ${d.day ? dayLabel(d.day) : ""}</h2>${soloStats(d.day_totals)}
    <details style="margin-top:12px"><summary class="link">Totais de toda a vida ▾</summary>${soloStats(d.lifetime)}</details>
    <h2>Sessões enviadas (${d.sessions.length})</h2>
    ${d.sessions.length ? d.sessions.map(soloItem).join("") : `<p class="muted">Nenhuma sessão enviada para ${esc(S.nick)} ainda.</p>`}`;
  await ensurePlaces();
  el.querySelectorAll("[data-session-place]").forEach((slot) => {
    const sid = +slot.dataset.sessionPlace;
    const s = d.sessions.find((x) => x.id === sid);
    slot.innerHTML = pickerHTML();
    initPicker(slot.firstElementChild, {
      value: s.place, onPick: async (p) => { await api("POST", `/api/stacker/session/${sid}/place`, { place_id: p.id }); loadStack(); },
    });
  });
  countUp(el);
  return d;
}

/* ---------- 🥇 ranking entre amigos (só quem aceitar entrar) ---------- */
S.rank = { metric: "xp", period: 7 };
const RANK_FMT = { xp: (r) => fmt(r.xp) + " XP", xp_h: (r) => fmt(r.xp_h) + " XP/h", profit: (r) => fmt(r.profit) + " gp",
                   profit_h: (r) => fmt(r.profit_h) + " gp/h", hours: (r) => String(r.hours).replace(".", ",") + " h" };
async function loadRank() {
  const body = $("#rankBody");
  body.innerHTML = skeleton("stack");
  let d;
  try { d = await api("GET", `/api/ranking?period=${S.rank.period}&metric=${S.rank.metric}&nick=${encodeURIComponent(S.nick)}`); }
  catch (err) { if (err.status !== 401) body.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  const owner = isMine(S.nick);
  $("#rankJoin").innerHTML = !owner ? `<div class="card muted">Você está vendo ${esc(S.nick)}. Só o dono do personagem decide se ele entra no ranking.</div>`
    : d.joined ? `<div class="card row"><span>✔ <b>${esc(S.nick)}</b> está no ranking.</span><button class="btn2" data-rank-join="0">Sair do ranking</button></div>`
    : `<div class="card"><b>Quer entrar no ranking?</b>
        <p class="muted" style="margin:4px 0 8px">Seus totais do Stacker (XP, lucro e horas da semana e do mês) passam a aparecer aqui para
          todos que usam o 4rt3mi5. Você pode sair quando quiser.</p>
        <button class="btn" style="margin:0" data-rank-join="1">Entrar com ${esc(S.nick)}</button></div>`;
  document.querySelectorAll("[data-rmetric]").forEach((b) => b.classList.toggle("on", b.dataset.rmetric === d.metric));
  document.querySelectorAll("[data-rperiod]").forEach((b) => b.classList.toggle("on", +b.dataset.rperiod === d.period));
  if (!d.rows.length) { body.innerHTML = `<p class="muted">Ninguém entrou no ranking ainda. Seja o primeiro!</p>`; return; }
  const me = S.nick.toLowerCase(), medal = ["🥇", "🥈", "🥉"];
  body.innerHTML = `<div class="table-wrap"><table><tr><th>#</th><th>Jogador</th><th>${esc($(`[data-rmetric="${d.metric}"]`).textContent)}</th><th>Sessões</th></tr>
    ${d.rows.map((r, i) => `<tr class="${r.name.toLowerCase() === me ? "me" : ""}"><td>${medal[i] || i + 1}</td>
      <td>${vdot(r.name)}${esc(r.name)}${r.level ? `<div class="muted" style="font-size:12px">level ${r.level}${r.vocation ? " · " + esc(r.vocation) : ""}</div>` : ""}</td>
      <td>${RANK_FMT[d.metric](r)}</td><td>${r.sessions}</td></tr>`).join("")}</table></div>
    <div class="hint">XP/h e lucro/h = total do período dividido pelas horas de hunt. Lucro = Balance das sessões.</div>`;
  ensureVocations(d.rows.map((r) => r.name)).then((c) => { if (c && S.page === "rank") paintVocations(body); });
}
document.addEventListener("click", async (e) => {
  const m = e.target.closest("[data-rmetric]"), p = e.target.closest("[data-rperiod]"), j = e.target.closest("[data-rank-join]");
  if (m) { S.rank.metric = m.dataset.rmetric; loadRank(); }
  if (p) { S.rank.period = +p.dataset.rperiod; loadRank(); }
  if (j) {
    j.disabled = true;
    try { await api("POST", `/api/ranking/${encodeURIComponent(S.nick)}`, { join: j.dataset.rankJoin === "1" }); loadRank(); }
    catch (err) { j.disabled = false; if (err.status !== 401) alert(err.message); }
  }
});

/** Sessão recém-enviada x sua média na mesma hunt. */
function compareBanner(c) {
  if (!c) return "";
  if (!c.sessions) return `<div class="card">📊 Primeira sessão sua em <b>${esc(c.place)}</b> (com 10 min ou mais):
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
  document.querySelectorAll(".drawer [data-btab]").forEach((b) =>
    b.classList.toggle("active", S.page === "boss" && (b.dataset.btab === "all" || b.dataset.btab === S.btab)));
  $("#bossLabel").textContent = S.btab === "party"
    ? "Cole aqui o SEU Hunt Session Analyser do boss em party (depois você escolhe se faz o lootsplit)"
    : "Cole aqui o Hunt Session Analyser do boss (solo)";
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
    </summary>${rulesLine(h)}${actionBox(v, h)}${chartToggle(h, S.nick)}<h2>Transferências</h2>${transfersBox(h)}${partyTable(h, S.nick)}${rulesBox(h)}${deleteButton(h)}</details>`;
}
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
  const t = d.totals;
  if (!t.sessions && !d.hunts.length && !d.from_hunts.length) {
    el.innerHTML = `<div class="card"><b>👑 Nenhum boss ainda</b>
      <p class="muted">Depois de matar um boss, abra o Hunt Analyser no Tibia, copie e cole aqui. Em <b>Solo</b> a sessão fica só sua.
        Em <b>Party</b> o app pergunta se você quer fazer o lootsplit: aí ele aparece para todos da PT, e as sessões que eles
        enviarem no mesmo horário se juntam sozinhas.</p></div>`;
    return d;
  }
  const n = (v, suffix = "") => `<span data-count="${v}" data-suffix="${suffix}">${fmt(v)}${suffix}</span>`;
  el.innerHTML = `
    <div class="card">
      <div class="muted">Lucro com bosses · ${fmt(t.boss_kills)} bosses mortos · ${dur(t.duration_seconds)} em sessões de boss</div>
      <div class="big ${t.profit >= 0 ? "gold" : "neg"}">${n(t.profit, " gp")}</div>
      <div class="muted">${t.profit_per_hour ? fmt(t.profit_per_hour) + " gp/h nas sessões de boss · " : ""}${fmt(t.sessions)} sessões (${t.solo} solo, ${t.party} party) · ${fmt(t.parties)} lootsplits</div>
      <div style="margin-top:10px">${statGrid([
        ["Sessões sem lootsplit", fmt(t.sessions_profit) + " gp", t.sessions_profit >= 0 ? "pos" : "neg"],
        ["Sua parte nos lootsplits", fmt(t.party_profit) + " gp", t.party_profit >= 0 ? "pos" : "neg"],
        ["Bosses nas hunts (estimado)", fmt(t.hunts_value) + " gp", "gold"],
        ["Loot das sessões", fmt(t.loot_value) + " gp"], ["Supplies", fmt(t.supplies) + " gp"], ["XP", fmt(t.xp)],
      ])}</div>
      <div class="hint">Sessão sem lootsplit conta pelo Balance dela. Com lootsplit conta a sua parte da divisão (sem contar duas vezes).</div>
    </div>
    ${noNpcBlock(d)}
    <h2>Bosses</h2>${bossTable(d.bosses)}
    ${rareBlock(d.rare_drops)}
    ${d.items.length ? `<h2>Itens dos bosses</h2><div class="card">${itemList(d.items)}</div>` : ""}
    ${d.hunts.length ? `<h2>Lootsplits de bosses (${d.hunts.length})</h2>${d.hunts.map(bossHuntItem).join("")}` : ""}
    ${d.sessions.length ? `<h2>Sessões de boss (${d.sessions.length})</h2>${d.sessions.map(bossSessionItem).join("")}` : ""}
    ${fromHuntsBlock(d.from_hunts)}`;
  countUp(el);
  const names = [...new Set(d.hunts.flatMap((h) => h.players.map((p) => p.name)))];
  if (names.length) ensureVocations(names).then((c) => { if (c && S.page === "boss") paintVocations(el); });
  return d;
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
  try {
    const r = await api("POST", "/api/bosses/session", { raw_text: raw, nickname: S.nick, mode });
    $("#bossText").value = "";
    S.bossLast = r;
    let ask = bossBanner(r);
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
      $("#bossSplitAsk").outerHTML = `<div class="banner ok">${r.created ? "Lootsplit de boss enviado ✔ Já aparece na aba de bosses de todos da PT." : "Esse lootsplit já estava salvo ✔"}
          ${r.linked > 1 ? ` ${r.linked} sessões da PT foram juntadas.` : ""}</div>` + huntCard(r.hunt, S.nick, "Lootsplit do boss");
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
function initStackPicker() {  // uma vez só; quem precisa do seletor pronto (colar direto) espera a mesma promessa
  if (!S.stackPickerReady) S.stackPickerReady = (async () => {
    const slot = $("#stackPlace");
    slot.innerHTML = pickerHTML();
    await ensurePlaces();
    const lastId = +(await kv.get("last_place")) || 0;
    initPicker(slot.firstElementChild, {
      value: (S.places || []).find((p) => p.id === lastId),
      onPick: (p) => kv.set("last_place", String(p.id)),
    });
  })();
  return S.stackPickerReady;
}

/* ---------- página Hunts: ranking por XP/h e gold/h, level médio, comparação ---------- */
S.htab = "xp"; S.cmp = [];
async function loadHunts() {
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
  const qs = new URLSearchParams({ sort: S.htab });
  if ($("#lvlMin").value) qs.set("min_level", $("#lvlMin").value);
  if ($("#lvlMax").value) qs.set("max_level", $("#lvlMax").value);
  el.innerHTML = skeleton("list");
  let d;
  try { d = await api("GET", "/api/places/ranking?" + qs); } catch (err) { el.innerHTML = `<div class="err">${esc(err.message)}</div>`; return; }
  if (!d.rows.length) { el.innerHTML = `<p class="muted">Nenhuma hunt com sessões ${$("#lvlMin").value || $("#lvlMax").value ? "nessa faixa de level" : "ainda"}. Envie sessões pelo Hunt Session Stacker escolhendo a hunt.</p>`; return; }
  const gold = S.htab === "gold";
  el.innerHTML = `<div class="card" style="padding:6px 10px">${d.rows.map((r, i) => `<div class="rank" data-cmp-add="${r.id}" title="Toque para comparar">
      <span class="pos">#${i + 1}</span>
      <span><b>${esc(r.name)}</b><br><span class="muted" style="font-size:13px">${esc(r.city || "")} · level médio ${r.avg_level ?? "—"}${r.min_level != null && r.min_level !== r.max_level ? ` (${r.min_level}–${r.max_level})` : ""} · ${r.players} jogador${r.players === 1 ? "" : "es"} · ${r.sessions} sess${r.sessions === 1 ? "ão" : "ões"}</span></span>
      <span style="text-align:right"><b class="gold">${kk(gold ? r.gold_per_hour : r.xp_per_hour)}${gold ? " gp/h" : " XP/h"}</b><br>
        <span class="muted" style="font-size:13px">${gold ? kk(r.xp_per_hour) + " XP/h" : kk(r.gold_per_hour) + " gp/h"}</span></span>
    </div>`).join("")}</div><div class="hint">Toque numa hunt para colocá-la na comparação.</div>`;
}
function renderCompare() {
  $("#cmpChips").innerHTML = S.cmp.map((p) => `<span class="chip">${esc(p.name)}<button class="x" data-cmp-del="${p.id}" aria-label="Remover">✕</button></span>`).join("")
    || `<span class="muted">Nenhuma hunt escolhida.</span>`;
  const el = $("#cmpResult");
  if (!S.cmp.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<p class="muted">Carregando…</p>`;
  api("GET", `/api/places/compare?ids=${S.cmp.map((p) => p.id).join(",")}&nick=${encodeURIComponent(S.nick)}`).then((rows) => {
    const cell = (r, f) => r.stats ? f(r.stats) : "—";
    const mine = (r, f) => r.mine ? f(r.mine) : "—";
    const best = (vals) => Math.max(...vals.filter((v) => typeof v === "number"));
    const xs = rows.map((r) => r.stats ? r.stats.xp_per_hour : null), gs = rows.map((r) => r.stats ? r.stats.gold_per_hour : null);
    const lines = [
      ["XP/h (todos)", rows.map((r, i) => cell(r, (s) => `<b class="${xs[i] === best(xs) && rows.length > 1 ? "gold" : ""}">${kk(s.xp_per_hour)}</b>`))],
      ["Gold/h (todos)", rows.map((r, i) => cell(r, (s) => `<b class="${gs[i] === best(gs) && rows.length > 1 ? "gold" : ""}">${kk(s.gold_per_hour)}</b>`))],
      ["Level médio", rows.map((r) => cell(r, (s) => `${s.avg_level ?? "—"}${s.min_level != null && s.min_level !== s.max_level ? `<br><span class="muted">${s.min_level}–${s.max_level}</span>` : ""}`))],
      ["Jogadores / sessões", rows.map((r) => cell(r, (s) => `${s.players} / ${s.sessions}`))],
      ["Level recomendado (wiki)", rows.map((r) => r.place.level ? r.place.level + "+" : "—")],
      ["Seu XP/h", rows.map((r) => mine(r, (s) => kk(s.xp_per_hour)))],
      ["Seu gold/h", rows.map((r) => mine(r, (s) => kk(s.gold_per_hour)))],
      ["Criaturas mais mortas", rows.map((r) => r.top_kills.map((k) => `${kk(k.count)}x ${esc(k.key)}`).join("<br>") || "—")],
      ["Itens que mais renderam", rows.map((r) => r.top_items.map((t) => `${esc(t.name)} <span class="muted">${kk(t.value)}</span>`).join("<br>") || "—")],
    ];
    el.innerHTML = `<div class="card table-wrap"><table class="cmp"><tr><th></th>${rows.map((r) => `<th>${esc(r.place.name)}<br><span class="muted">${esc(r.place.city || "")}</span></th>`).join("")}</tr>
      ${lines.map(([label, cells]) => `<tr><td class="muted">${label}</td>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</table></div>
      <div class="hint">"Seu" = sessões de ${esc(S.nick)} nessa hunt. Em dourado, a melhor de cada linha.</div>`;
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
    <div class="muted" style="margin-top:4px">${x}, ${y}, andar ${z}</div>`;
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
      <div class="hint">Passe o mouse (ou toque) na imagem do NPC para ver onde ele fica.</div>`;
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
$("#stackBtn").addEventListener("click", async () => {
  const raw = $("#stackText").value.trim();
  if (!raw) return;
  const placeId = +($("#stackPlace .picker") || {}).dataset?.placeId || null;
  if (!placeId) { $("#stackErr").textContent = "Escolha em qual hunt foi a sessão (digite para procurar)."; return; }
  const btn = $("#stackBtn"); btn.disabled = true; $("#stackErr").textContent = "";
  try {
    const before = S.stack;
    const r = await api("POST", "/api/stacker", { raw_text: raw, nickname: S.nick, place_id: placeId });
    $("#stackText").value = "";
    const after = await loadStack();
    $("#stackResult").insertAdjacentHTML("afterbegin",
      `<div class="banner ok">${r.created ? "Sessão adicionada ✔" : "Essa sessão já estava salva ✔"}</div>${compareBanner(r.compare)}`);
    celebrateRare(r.rare);
    celebrateRewards(r.rewards);
    if (r.created) { celebrateProgress(before, after); checkAchievements(); }
  } catch (err) {
    if (err.status === 0) { await queueDraft("/api/stacker", { raw_text: raw, nickname: S.nick, place_id: placeId }, $("#stackErr")); $("#stackText").value = ""; }
    else if (err.status === 403) $("#stackErr").innerHTML = `${esc(err.message)}<div class="hint">${esc(err.hint || "")}</div>`;
    else if (err.status !== 401) $("#stackErr").textContent = err.message;
  } finally { btn.disabled = false; }
});

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
      if (S.page === "loot") $("#lootResult").innerHTML = `<div class="banner ok">Hunt apagada.</div>`;
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
async function checkUpdate() {
  const info = await window.pywebview.api.check_update().catch(() => null);
  if (!info) return;
  const box = $("#update");
  box.innerHTML = `<div class="row"><span>Nova versão <b>${esc(info.version)}</b> disponível.</span>
    <button class="copy" id="doUpdate" style="border-color:var(--gold)">Atualizar</button></div>`;
  box.classList.remove("hidden");
  $("#doUpdate").addEventListener("click", async () => {
    box.innerHTML = "Baixando atualização… o app vai fechar e abrir de novo sozinho.";
    const err = await window.pywebview.api.install_update().catch((e) => String(e));
    if (err) box.textContent = "Não foi possível atualizar: " + err;
  });
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
  const [desktop] = await Promise.all([detected, sleep(2600)]);
  S.desktop = desktop;
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
  if (desktop) checkUpdate();
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
      <li>Cole na caixa acima (ou aperte <b>Ctrl+V</b> em qualquer tela).</li>
      <li>Escolha em qual hunt foi e toque em <b>Adicionar sessão</b>.</li></ol>
    <button class="btn" data-focus="stackText">📋 Colar minha primeira sessão</button></div>`;
}
document.addEventListener("keydown", (e) => {  // cartões clicáveis (role=button) também abrem com Enter/Espaço
  const c = e.target.closest && e.target.closest('[role="button"][data-page-link]');
  if (c && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); c.click(); }
});
document.addEventListener("click", (e) => {
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
  for (const s of sessions) { const k = weekKey(s.started_at); if (k in xp) { xp[k] += s.xp; profit[k] += s.net_profit; } }
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
function streakCard(s) {
  const won = (s.rewards || []).reduce((a, r) => a + r.days, 0);
  return `<div class="card streak">
    <div class="row" style="align-items:flex-end; flex-wrap:wrap">
      <div><div class="muted">🔥 Sequência de dias</div><div class="count">${s.current} <span class="muted" style="font: 600 15px system-ui">dia${s.current === 1 ? "" : "s"} seguidos</span></div></div>
      <div style="text-align:right"><div class="muted" style="font-size:13px">Próxima recompensa</div>
        <b class="gold">+${s.reward_days} dias em ${s.next_reward_in} dia${s.next_reward_in === 1 ? "" : "s"}</b></div></div>
    <div class="days" aria-label="Últimos 30 dias">${streakDays(s)}</div>
    <div class="gbar"><div style="width:${(s.progress / s.target) * 100}%"></div></div>
    <p style="margin:10px 0 0; font-size:14px"><b>Como ganhar:</b> envie pelo menos <b>uma</b> party hunt (Lootsplit) ou sessão (Stacker) por dia.
      A cada <b>${s.target} dias seguidos</b>, seu código de acesso ganha <b class="gold">+${s.reward_days} dias</b> de validade, sozinho.</p>
    <div class="hint">${s.active_today ? "Hoje já conta ✔" : "Hoje ainda não conta: envie algo até a meia-noite (horário de Brasília) para manter a sequência."}
      ${s.expires_at ? ` Seu código vale até ${new Date(s.expires_at).toLocaleDateString("pt-BR")}.` : ""}${won ? ` Você já ganhou ${won} dias assim.` : ""}</div></div>`;
}
function streakTeaser(s) {
  return `<div class="card streak teaser" data-page-link="ach" role="button" tabindex="0" aria-label="Ver conquistas e sequência">
    <div class="count">${s.current}</div>
    <div style="min-width:0; flex:1"><b>🔥 ${s.current} de ${s.target} dias seguidos</b>
      <div class="muted" style="font-size:13px">Envie uma hunt ou sessão por dia: com ${s.target} dias seguidos seu código ganha
        <b class="gold">+${s.reward_days} dias</b>. ${s.active_today ? "Hoje já conta ✔" : "Falta enviar hoje."}</div>
      <div class="gbar" style="margin-top:6px"><div style="width:${(s.progress / s.target) * 100}%"></div></div></div></div>`;
}
function achProgress(a) {
  const f = a.id === "marathon" ? dur : ["loot_kk", "xp_kk", "slayer"].includes(a.id) ? kk : fmt;
  return `${f(a.value)} / ${f(a.target)}`;
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
  return [s && "Sessão de " + s, d && "em " + dayLabel(d)].filter(Boolean).join(" ") || "Texto do analyser";
}
async function offerPaste(kind, t) {
  S.pasteText = t;
  const sheet = $("#sheet");
  if (kind === "party") {
    sheet.innerHTML = `<b>📋 Party Hunt Analyser detectado</b>
      <div class="muted" style="font-size:14px; margin-top:2px">${esc(pasteSummary(t))}. Enviar para o Lootsplit em nome de ${esc(S.nick)}?</div>
      <div class="actions"><button class="btn" data-paste-go="party">Enviar agora</button><button class="btn2" data-paste-cancel>Cancelar</button></div>`;
  } else {
    await ensurePlaces();
    const last = +(await kv.get("last_place")) || 0, place = (S.places || []).find((p) => p.id === last);
    sheet.innerHTML = `<b>📋 Hunt Analyser (sessão solo) detectado</b>
      <div class="muted" style="font-size:14px; margin-top:2px">${esc(pasteSummary(t))}.${place ? ` Hunt: <b style="color:var(--text)">${esc(place.name)}</b> (a última que você usou).` : " Escolha em qual hunt foi."}</div>
      <div class="actions">${place ? `<button class="btn" data-paste-go="solo">Enviar agora</button><button class="btn2" data-paste-go="solo-pick">Outra hunt</button>`
                                   : `<button class="btn" data-paste-go="solo-pick">Escolher a hunt</button>`}
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
    if (g.dataset.pasteGo === "party") { go("loot"); $("#lootText").value = t; $("#lootBtn").click(); return; }
    if (g.dataset.pasteGo === "boss") { go("boss"); $("#bossText").value = t; $("#bossText").focus(); return; }
    go("stack");
    await initStackPicker();
    $("#stackText").value = t;
    if (g.dataset.pasteGo === "solo") $("#stackBtn").click();
    else { const inp = $("#stackPlace .pk-in"); inp.value = ""; inp.focus(); }
    return;
  }
  const p = e.target.closest("[data-paste-into]");
  if (p) {
    const box = document.getElementById(p.dataset.pasteInto);
    const err = p.dataset.pasteErr ? document.getElementById(p.dataset.pasteErr)
              : p.dataset.pasteInto === "lootText" ? $("#lootErr") : $("#stackErr");
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
      ${isIOS() ? "<li>No iPhone e no iPad quem cria o ícone é o Safari: vamos mostrar os 2 toques necessários.</li>"
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

boot();
