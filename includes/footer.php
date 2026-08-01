    </section>
  </main>
</div>
<script>window.APP={baseUrl:<?= json_encode(rtrim(APP_URL, '/')) ?>,basePath:<?= json_encode(app_base_path()) ?>,serviceWorkerUrl:<?= json_encode(url('service-worker.php')) ?>,serviceWorkerScope:<?= json_encode((app_base_path() ?: '') . '/') ?>,csrf:<?= json_encode(csrf_token()) ?>};</script>
<script src="<?= e(asset_url('assets/js/app.js')) ?>" defer></script>
</body>
</html>
