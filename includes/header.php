<?php
declare(strict_types=1);

require_once __DIR__ . '/auth.php';
require_login();
require_once __DIR__ . '/notifications.php';

$page_title = $page_title ?? APP_NAME;
$headerUser = current_user();
$unread = unread_notifications_count((int) $headerUser['id']);
$recentHeaderNotifications = recent_notifications((int) $headerUser['id'], 5);
?>
<!doctype html>
<html lang="pt-BR" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0b0d0c">
  <meta name="color-scheme" content="light dark">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <meta name="apple-mobile-web-app-title" content="Print Fornece">
  <title><?= e($page_title) ?> | <?= e(APP_NAME) ?></title>
  <link rel="manifest" href="<?= e(url('manifest.webmanifest')) ?>">
  <link rel="icon" href="<?= e(asset_url('icons/icon.svg')) ?>" type="image/svg+xml">
  <link rel="apple-touch-icon" href="<?= e(asset_url('icons/icon-192.png')) ?>">
  <script>
    (function () {
      try {
        var preference = localStorage.getItem('print-fornece-theme');
        if (preference !== 'light' && preference !== 'dark' && preference !== 'system') preference = 'system';
        var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.dataset.theme = preference === 'system' ? (dark ? 'dark' : 'light') : preference;
        document.documentElement.dataset.themePreference = preference;
      } catch (_) {}
    }());
  </script>
  <link rel="stylesheet" href="<?= e(asset_url('assets/css/style.css')) ?>">
  <link rel="stylesheet" href="<?= e(asset_url('assets/css/overrides.css')) ?>">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css" referrerpolicy="no-referrer">
</head>
<body>
<div class="app-shell">
  <?php require __DIR__ . '/sidebar.php'; ?>
  <main class="main-content">
    <header class="topbar">
      <button class="icon-button menu-toggle" data-menu-open aria-label="Abrir menu"><i class="fa-solid fa-bars" aria-hidden="true"></i></button>
      <div class="topbar-title"><h1><?= e($page_title) ?></h1><p><?= e($headerUser['nome']) ?> · <?= e(ucfirst($headerUser['perfil'])) ?></p></div>
      <div class="topbar-actions">
        <label class="theme-control"><span class="sr-only">Tema do sistema</span><i class="fa-solid fa-circle-half-stroke" aria-hidden="true"></i><select data-theme-select aria-label="Selecionar tema"><option value="system">Tema do sistema</option><option value="light">Claro</option><option value="dark">Escuro</option></select></label>
        <button class="icon-button install-button" type="button" data-install-app hidden><i class="fa-solid fa-download" aria-hidden="true"></i><span>Instalar app</span></button>
        <button class="icon-button install-button" type="button" data-install-ios hidden><i class="fa-solid fa-mobile-screen-button" aria-hidden="true"></i><span>Instalar no iPhone/iPad</span></button>
        <div class="notification-area">
          <a class="notification-bell" href="<?= e(url('notificacoes/index.php')) ?>" aria-label="Notificações"><i class="fa-regular fa-bell" aria-hidden="true"></i><span class="notification-count <?= $unread ? '' : 'is-empty' ?>" data-unread-count><?= $unread ?></span></a>
          <div class="notification-dropdown">
            <strong>Recentes</strong>
            <?php foreach ($recentHeaderNotifications as $notification): ?><a href="<?= e(url($notification['link'] ?: 'notificacoes/index.php')) ?>" class="<?= !$notification['lida_em'] ? 'unread' : '' ?>"><span><?= e($notification['titulo']) ?></span><small><?= e($notification['mensagem']) ?></small></a><?php endforeach; ?>
            <?php if (!$recentHeaderNotifications): ?><p>Nenhuma notificação.</p><?php endif; ?>
            <a class="notification-see-all" href="<?= e(url('notificacoes/index.php')) ?>">Ver todas</a>
          </div>
        </div>
      </div>
    </header>
    <section class="page-body">
      <?php if ($error = flash('error')): ?><div class="toast toast-error" role="alert"><?= e($error) ?></div><?php endif; ?>
      <?php if ($success = flash('success')): ?><div class="toast toast-success" role="status"><?= e($success) ?></div><?php endif; ?>
