const CACHE = 'sonar-v1'
const ASSETS = ['/', '/static/manifest.json', '/static/icon-192.png', '/static/icon-512.png']

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)))
})

self.addEventListener('fetch', e => {
  // Solo cachea assets estáticos, no las búsquedas
  if (e.request.url.includes('/search') || 
      e.request.url.includes('/solo') ||
      e.request.url.includes('/explore') ||
      e.request.url.includes('/resolve') ||
      e.request.url.includes('/daily')) {
    return
  }
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  )
})
