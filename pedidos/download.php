<?php
declare(strict_types=1);
require_once __DIR__ . '/../includes/auth.php'; require_login(); $id=(int)($_GET['id']??0);
$s=db()->prepare('SELECT a.*,p.id AS pedido_id FROM pedido_arquivos a JOIN pedidos p ON p.id=a.pedido_id WHERE a.id=? AND a.removido_em IS NULL');$s->execute([$id]);$file=$s->fetch();
if(!$file || !can_access_order(order_by_id((int)$file['pedido_id']))) { http_response_code(404); exit('Arquivo não encontrado.'); }
$path=UPLOAD_DIR.'/'.$file['nome_armazenado'];if(!is_file($path)){http_response_code(404);exit('Arquivo indisponível.');}audit('download_anexo','pedido',(int)$file['pedido_id'],null,['arquivo'=>$file['nome_original']]);header('Content-Type: '.$file['mime_type']);header('Content-Length: '.filesize($path));header('Content-Disposition: attachment; filename="'.rawurlencode($file['nome_original']).'"');header('X-Content-Type-Options: nosniff');readfile($path);exit;
