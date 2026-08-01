<?php
declare(strict_types=1);
require_once __DIR__ . '/includes/auth.php';
if ($user=current_user()) audit('logout','usuario',(int)$user['id']);
$_SESSION=[];
if (ini_get('session.use_cookies')) { $params=session_get_cookie_params(); setcookie(session_name(),'', ['expires'=>time()-42000,'path'=>$params['path'],'domain'=>$params['domain'],'secure'=>$params['secure'],'httponly'=>$params['httponly'],'samesite'=>'Lax']); }
session_destroy();
header('Location: ' . url('login.php')); exit;
