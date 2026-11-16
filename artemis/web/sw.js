// Guarda a página para que, sem internet, o celular ainda abra a tela "Sem conexão" do 4rt3mi5.
// 0.17.0: o script do site saiu do HTML (app.js), então ele também fica guardado.
const CACHE = "artemis-v3";
const OFFLINE = ["/", "/app.js", "/i18n.js"];  // 0.19.0: + idiomas (o dicionário escolhido entra ao ser usado)
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(OFFLINE)));
  self.skipWaiting();
});
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim())
));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  // só a página inicial, os scripts e os idiomas (o painel /admin nunca vai para o cache)
  const SCRIPTS = ["/app.js", "/i18n.js", "/i18n-en.json", "/i18n-es.json", "/i18n-ja.json"];
  const key = e.request.mode === "navigate" ? (url.pathname === "/" ? "/" : null) : (SCRIPTS.includes(url.pathname) ? url.pathname : null);
  if (!key) return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(key, copy)); }
        return res;
      })
      .catch(() => caches.match(key))
  );
});
