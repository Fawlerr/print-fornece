<?php
declare(strict_types=1);

require_once __DIR__ . '/includes/auth.php';
if (current_user()) redirect('index.php');

$error = null;
if (is_post()) {
    validate_csrf($_POST['csrf_token'] ?? null);
    $attempts = $_SESSION['login_attempts'] ?? ['count' => 0, 'last' => 0];
    if ($attempts['count'] >= 5 && time() - $attempts['last'] < 900) {
        $error = 'Muitas tentativas. Aguarde alguns minutos e tente novamente.';
    } else {
        $email = filter_var(trim((string) ($_POST['email'] ?? '')), FILTER_VALIDATE_EMAIL);
        $password = (string) ($_POST['senha'] ?? '');
        $stmt = db()->prepare('SELECT id, senha, ativo, forcar_troca_senha FROM usuarios WHERE email = ? LIMIT 1');
        $stmt->execute([$email ?: '']);
        $user = $stmt->fetch();
        if ($user && $user['ativo'] && password_verify($password, $user['senha'])) {
            session_regenerate_id(true);
            $_SESSION['user_id'] = (int) $user['id'];
            $_SESSION['login_attempts'] = ['count' => 0, 'last' => 0];
            db()->prepare('UPDATE usuarios SET ultimo_acesso=NOW() WHERE id=?')->execute([$user['id']]);
            audit('login', 'usuario', (int) $user['id']);
            redirect(!empty($user['forcar_troca_senha']) ? 'perfil/index.php' : 'index.php');
        }
        $_SESSION['login_attempts'] = ['count' => $attempts['count'] + 1, 'last' => time()];
        $error = 'E-mail ou senha inválidos.';
    }
}
?>
<!doctype html>
<html lang="pt-BR" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0b0d0c">
  <meta name="color-scheme" content="light dark">
  <link rel="manifest" href="<?= e(url('manifest.webmanifest')) ?>">
  <link rel="icon" href="<?= e(asset_url('icons/icon.svg')) ?>" type="image/svg+xml">
  <title>Entrar | <?= e(APP_NAME) ?></title>
  <script>
    (function () {
      try {
        var preference = localStorage.getItem('print-fornece-theme');
        if (preference !== 'light' && preference !== 'dark' && preference !== 'system') preference = 'system';
        var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.dataset.theme = preference === 'system' ? (dark ? 'dark' : 'light') : preference;
      } catch (_) {}
    }());
  </script>
  <link rel="stylesheet" href="<?= e(asset_url('assets/css/style.css')) ?>">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css" referrerpolicy="no-referrer">
</head>
<body class="login-page">
  <main class="login-card">
    <div class="login-brand"><i class="fa-solid fa-print" aria-hidden="true"></i><span>PRINT <b>FORNECE</b></span></div>
    <h1>Bem-vindo de volta</h1>
    <p>Entre para gerenciar pedidos e produção.</p>
    <?php if ($error): ?><div class="form-error" role="alert"><?= e($error) ?></div><?php endif; ?>
    <?php if ($message = flash('error')): ?><div class="form-error" role="alert"><?= e($message) ?></div><?php endif; ?>
    <form method="post" novalidate>
      <?= csrf_input() ?>
      <label>E-mail<input type="email" name="email" autocomplete="email" required autofocus></label>
      <label>Senha<input type="password" name="senha" autocomplete="current-password" required></label>
      <button class="btn btn-primary btn-block" type="submit">Entrar <i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button>
    </form>
  </main>
</body>
</html>
