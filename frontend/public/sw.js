/* Service worker do Ponto.
 * - Instalação: guarda o app INTEIRO (página, JS, CSS, fontes, ícones). A lista e a versão são gravadas pelo build
 *   (vite.config.ts); sem isso o app abriria em branco sem internet. Se algum arquivo falhar, a instalação falha e tenta de novo.
 * - Navegação: rede primeiro, com prazo curto; sem rede (ou rede travada) serve a página guardada. O app é uma SPA:
 *   qualquer rota abre a mesma página.
 * - Consultas necessárias para abrir o app e ver o dia (sessão, empresa, marcações, espelho): rede primeiro, cache como reserva.
 *   Não guarda /api/time (o relógio precisa ser fresco) nem nada que grave dados.
 * - Registro de ponto sem rede NÃO passa pelo service worker: a fila fica no app (localStorage) e é enviada por ele (src/offline.ts).
 */
const BUILD = "__BUILD__";
const SHELL = `ponto-shell-${BUILD}`;
const API = "ponto-api-v1";
const PRECACHE = ["/", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png", "/icons/icon.svg"];
const ASSETS = [/* __ASSETS__ */];
const CACHEABLE_API = [
  /^\/api\/auth\/me$/, /^\/api\/auth\/2fa$/, /^\/api\/company$/, /^\/api\/mirror/, /^\/api\/punches(\?|$|\/next$|\/\d+\/receipt$)/,
  /^\/api\/receipts/, /^\/api\/adjustments/, /^\/api\/absences/, /^\/api\/hour-bank/,
];
const NAVIGATE_TIMEOUT_MS = 4000; // rede travada (sinal ruim) conta como sem rede

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll([...PRECACHE, ...ASSETS])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => ![SHELL, API].includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "clear-api") event.waitUntil(caches.delete(API));
  if (event.data === "skip-waiting") self.skipWaiting();
});

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("timeout")), ms);
    promise.then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
  });
}

async function networkFirst(request, cacheName, fallbackKey, timeoutMs) {
  const cache = await caches.open(cacheName);
  try {
    const attempt = fetch(request);
    const res = await (timeoutMs ? withTimeout(attempt, timeoutMs) : attempt);
    if (res.ok) cache.put(fallbackKey ?? request, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(fallbackKey ?? request);
    if (hit) return hit;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res.ok) cache.put(request, res.clone());
  return res;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/")) {
    if (CACHEABLE_API.some((re) => re.test(url.pathname + url.search))) {
      event.respondWith(networkFirst(request, API));
    }
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request, SHELL, "/", NAVIGATE_TIMEOUT_MS));
    return;
  }
  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(cacheFirst(request));
  }
});
