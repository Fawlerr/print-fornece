<?php
declare(strict_types=1);
require_once __DIR__ . '/includes/auth.php';
if (!current_user()) redirect('login.php');
redirect(is_admin() ? 'admin/dashboard.php' : 'producao/index.php');
