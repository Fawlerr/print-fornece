    </section>
  </main>
</div>
<script>window.APP={baseUrl:<?= json_encode(rtrim(APP_URL, '/')) ?>,csrf:<?= json_encode(csrf_token()) ?>};</script>
<script src="<?= e(asset_url('assets/js/app.js')) ?>" defer></script>
</body>
</html>
