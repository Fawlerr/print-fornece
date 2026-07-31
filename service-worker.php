<?php
declare(strict_types=1);

require_once __DIR__ . '/config/config.php';

$baseUrl = rtrim(APP_URL, '/');
$scope = ($baseUrl ?: '') . '/';
$assets = ['assets/css/style.css', 'assets/css/overrides.css', 'assets/js/app.js', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png'];
$versionParts = [];
$urls = [];
foreach ($assets as $asset) {
    $path = __DIR__ . '/' . $asset;
    $version = is_file($path) ? (string) filemtime($path) : '0';
    $versionParts[] = $asset . ':' . $version;
    $urls[] = $baseUrl . '/' . $asset . '?v=' . rawurlencode($version);
}
$cacheName = 'print-fornece-static-' . substr(hash('sha256', implode('|', $versionParts)), 0, 16);

header('Content-Type: application/javascript; charset=utf-8');
header('Cache-Control: no-cache, no-store, must-revalidate');
header('Service-Worker-Allowed: ' . $scope);
?>
const CACHE_NAME = <?= json_encode($cacheName) ?>;
const STATIC_URLS = <?= json_encode($urls, JSON_UNESCAPED_SLASHES) ?>;

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_URLS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key.startsWith('print-fornece-static-') && key !== CACHE_NAME).map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});

function isStaticAsset(request) {
  if (request.method !== 'GET') return false;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  return url.pathname.includes('/assets/') || url.pathname.includes('/icons/') || url.pathname.endsWith('/manifest.webmanifest');
}

self.addEventListener('fetch', (event) => {
  if (!isStaticAsset(event.request)) return;
  event.respondWith(fetch(event.request).then((response) => {
    if (response.ok) {
      const copy = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
    }
    return response;
  }).catch(() => caches.match(event.request)));
});
