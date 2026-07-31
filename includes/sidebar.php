<?php
$user = current_user(); $path = request_path();
$logo = null; foreach (['logo.svg','logo.png','logo.webp'] as $name) { if (is_file(APP_ROOT . '/images/' . $name)) { $logo = 'images/' . $name; break; } }
$adminItems = [['admin/dashboard.php','Visão geral','fa-chart-line'],['pedidos/novo.php','Novo pedido','fa-plus-circle'],['producao/index.php','Produção','fa-table-columns'],['admin/despesas.php','Despesas','fa-wallet'],['admin/relatorios.php','Relatórios','fa-file-chart-column'],['admin/usuarios.php','Usuários','fa-users']];
$commonItems = [['notificacoes/index.php','Notificações','fa-bell'],['perfil/index.php','Meu perfil','fa-user-gear'],['logout.php','Sair','fa-right-from-bracket']];
$navItems = array_merge(is_admin() ? $adminItems : [['pedidos/novo.php','Novo pedido','fa-plus-circle'],['producao/index.php','Produção','fa-table-columns']], $commonItems);
?>
<aside class="sidebar" id="sidebar" aria-label="Navegação principal">
  <div class="brand"><?php if ($logo): ?><img src="<?= e(url($logo)) ?>" alt="Logo <?= e(APP_NAME) ?>"><?php else: ?><span>PRINT <b>FORNECE</b></span><?php endif; ?><button class="icon-button mobile-only" data-menu-close aria-label="Fechar menu"><i class="fa-solid fa-xmark"></i></button></div>
  <nav><?php foreach ($navItems as [$href,$label,$icon]): $active=str_contains($path, '/'.$href); ?><a href="<?= e(url($href)) ?>" class="<?= $active?'active':'' ?>"><i class="fa-solid <?= e($icon) ?>"></i><span><?= e($label) ?></span></a><?php endforeach; ?></nav>
  <div class="sidebar-user"><strong><?= e($user['nome']) ?></strong><small><?= e(ucfirst($user['perfil'])) ?></small></div>
</aside><div class="menu-overlay" data-menu-close></div>
