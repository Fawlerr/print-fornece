<?php
declare(strict_types=1);
require_once __DIR__ . '/../includes/auth.php';require_login();$user=current_user();
if(!is_post()){http_response_code(405);exit('Método inválido.');}validate_csrf($_POST['csrf_token']??null);if(!empty($_POST['all'])){db()->prepare('UPDATE notificacoes SET lida_em=NOW() WHERE usuario_id=? AND lida_em IS NULL')->execute([$user['id']]);redirect('notificacoes/index.php');}$id=(int)($_POST['id']??0);$s=db()->prepare('SELECT link FROM notificacoes WHERE id=? AND usuario_id=?');$s->execute([$id,$user['id']]);$n=$s->fetch();if(!$n){http_response_code(404);exit('Notificação não encontrada.');}db()->prepare('UPDATE notificacoes SET lida_em=COALESCE(lida_em,NOW()) WHERE id=? AND usuario_id=?')->execute([$id,$user['id']]);redirect($n['link']?:'notificacoes/index.php');
