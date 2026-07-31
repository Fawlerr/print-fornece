-- Print Fornece | MySQL 8+ / MariaDB 10.4+
-- Importe este arquivo em um banco vazio criado com utf8mb4.
SET NAMES utf8mb4;
SET time_zone = '-03:00';
SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE usuarios (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(120) NOT NULL,
  email VARCHAR(190) NOT NULL,
  senha VARCHAR(255) NOT NULL,
  perfil ENUM('administrador','funcionario') NOT NULL DEFAULT 'funcionario',
  ativo TINYINT(1) NOT NULL DEFAULT 1,
  forcar_troca_senha TINYINT(1) NOT NULL DEFAULT 0,
  ultimo_acesso DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_usuarios_email (email),
  KEY idx_usuarios_perfil_ativo (perfil, ativo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE pedidos (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  numero VARCHAR(30) NOT NULL,
  cliente_nome VARCHAR(150) NOT NULL,
  cliente_whatsapp VARCHAR(25) NOT NULL,
  descricao TEXT NOT NULL,
  valor_total DECIMAL(12,2) NOT NULL,
  status_pagamento ENUM('nao_pago','parcial','pago') NOT NULL DEFAULT 'nao_pago',
  valor_pago DECIMAL(12,2) NOT NULL DEFAULT 0.00,
  forma_pagamento ENUM('pix','cartao','dinheiro','transferencia','outro') NULL,
  previsao_entrega DATETIME NULL,
  prioridade ENUM('normal','urgente') NOT NULL DEFAULT 'normal',
  observacoes_internas TEXT NULL,
  etapa ENUM('novo','preparacao','producao','pronto','finalizado','cancelado') NOT NULL DEFAULT 'novo',
  responsavel_id INT UNSIGNED NULL,
  criado_por_id INT UNSIGNED NOT NULL,
  etapa_atualizada_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finalizado_em DATETIME NULL,
  cancelado_em DATETIME NULL,
  cancelado_por_id INT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pedidos_numero (numero),
  KEY idx_pedidos_etapa (etapa),
  KEY idx_pedidos_pagamento (status_pagamento),
  KEY idx_pedidos_criado (created_at),
  KEY idx_pedidos_responsavel (responsavel_id),
  KEY idx_pedidos_previsao (previsao_entrega),
  CONSTRAINT fk_pedidos_responsavel FOREIGN KEY (responsavel_id) REFERENCES usuarios(id) ON DELETE SET NULL,
  CONSTRAINT fk_pedidos_criado_por FOREIGN KEY (criado_por_id) REFERENCES usuarios(id),
  CONSTRAINT fk_pedidos_cancelado_por FOREIGN KEY (cancelado_por_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE pedido_arquivos (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  pedido_id INT UNSIGNED NOT NULL,
  nome_original VARCHAR(255) NOT NULL,
  nome_armazenado VARCHAR(100) NOT NULL,
  mime_type VARCHAR(100) NOT NULL,
  tamanho INT UNSIGNED NOT NULL,
  criado_por_id INT UNSIGNED NOT NULL,
  removido_em DATETIME NULL,
  removido_por_id INT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_arquivos_pedido_ativo (pedido_id, removido_em),
  UNIQUE KEY uq_arquivos_armazenado (nome_armazenado),
  CONSTRAINT fk_arquivos_pedido FOREIGN KEY (pedido_id) REFERENCES pedidos(id),
  CONSTRAINT fk_arquivos_criador FOREIGN KEY (criado_por_id) REFERENCES usuarios(id),
  CONSTRAINT fk_arquivos_removedor FOREIGN KEY (removido_por_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE pedido_historico (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  pedido_id INT UNSIGNED NOT NULL,
  usuario_id INT UNSIGNED NULL,
  acao VARCHAR(60) NOT NULL,
  descricao TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_historico_pedido_data (pedido_id, created_at),
  CONSTRAINT fk_historico_pedido FOREIGN KEY (pedido_id) REFERENCES pedidos(id),
  CONSTRAINT fk_historico_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE pedido_observacoes (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  pedido_id INT UNSIGNED NOT NULL,
  usuario_id INT UNSIGNED NOT NULL,
  texto TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_observacoes_pedido (pedido_id, created_at),
  CONSTRAINT fk_observacoes_pedido FOREIGN KEY (pedido_id) REFERENCES pedidos(id),
  CONSTRAINT fk_observacoes_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE pedido_etapas_historico (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  pedido_id INT UNSIGNED NOT NULL,
  etapa_anterior ENUM('novo','preparacao','producao','pronto','finalizado','cancelado') NULL,
  etapa_nova ENUM('novo','preparacao','producao','pronto','finalizado','cancelado') NOT NULL,
  usuario_id INT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_etapas_pedido_data (pedido_id, created_at),
  CONSTRAINT fk_etapas_pedido FOREIGN KEY (pedido_id) REFERENCES pedidos(id),
  CONSTRAINT fk_etapas_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE despesas (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  descricao VARCHAR(180) NOT NULL,
  categoria ENUM('material','manutencao','energia','funcionarios','transporte','aluguel','impostos','outros') NOT NULL,
  valor DECIMAL(12,2) NOT NULL,
  data_despesa DATE NOT NULL,
  observacao TEXT NULL,
  status ENUM('ativa','cancelada') NOT NULL DEFAULT 'ativa',
  criado_por_id INT UNSIGNED NOT NULL,
  cancelado_por_id INT UNSIGNED NULL,
  cancelado_em DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_despesas_data_status (data_despesa,status),
  KEY idx_despesas_categoria (categoria),
  CONSTRAINT fk_despesas_criador FOREIGN KEY (criado_por_id) REFERENCES usuarios(id),
  CONSTRAINT fk_despesas_cancelador FOREIGN KEY (cancelado_por_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE notificacoes (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  usuario_id INT UNSIGNED NOT NULL,
  titulo VARCHAR(160) NOT NULL,
  mensagem TEXT NOT NULL,
  link VARCHAR(255) NULL,
  tipo ENUM('pedido','financeiro','sistema') NOT NULL DEFAULT 'pedido',
  lida_em DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_notificacoes_usuario_lida (usuario_id,lida_em,created_at),
  CONSTRAINT fk_notificacoes_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Estrutura para Stone futura. Nenhuma cobrança real é criada pela aplicação atual.
CREATE TABLE cobrancas (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  pedido_id INT UNSIGNED NOT NULL,
  provedor VARCHAR(50) NOT NULL DEFAULT 'stone',
  tipo ENUM('pix','cartao') NOT NULL,
  identificador_externo VARCHAR(190) NULL,
  valor DECIMAL(12,2) NOT NULL,
  status VARCHAR(50) NOT NULL DEFAULT 'pendente',
  pix_copia_cola TEXT NULL,
  checkout_url TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_cobrancas_pedido (pedido_id),
  KEY idx_cobrancas_externo (identificador_externo),
  CONSTRAINT fk_cobrancas_pedido FOREIGN KEY (pedido_id) REFERENCES pedidos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE auditoria (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  usuario_id INT UNSIGNED NULL,
  acao VARCHAR(80) NOT NULL,
  entidade VARCHAR(80) NOT NULL,
  entidade_id INT UNSIGNED NULL,
  dados_anteriores JSON NULL,
  dados_posteriores JSON NULL,
  ip VARCHAR(45) NULL,
  user_agent VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_auditoria_entidade (entidade,entidade_id,created_at),
  KEY idx_auditoria_usuario (usuario_id,created_at),
  CONSTRAINT fk_auditoria_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- DADOS OBRIGATÓRIOS DE PRIMEIRA INSTALAÇÃO
-- Senha inicial dos usuários abaixo: password. O administrador é obrigado a alterá-la ao entrar.
-- Hash bcrypt compatível com password_hash/password_verify do PHP.
INSERT INTO usuarios (id,nome,email,senha,perfil,ativo,forcar_troca_senha) VALUES
(1,'Administrador Print Fornece','admin@printfornece.local','$2y$10$DbIMe4kHkSabMbnZBPXGduTlo9FpI28Yh8fLvqEOpKM2u7KwpagsC','administrador',1,1),
(2,'Ana Produção','ana@printfornece.local','$2y$10$DbIMe4kHkSabMbnZBPXGduTlo9FpI28Yh8fLvqEOpKM2u7KwpagsC','funcionario',1,0),
(3,'Bruno Arte','bruno@printfornece.local','$2y$10$DbIMe4kHkSabMbnZBPXGduTlo9FpI28Yh8fLvqEOpKM2u7KwpagsC','funcionario',1,0);

-- DADOS DE DEMONSTRAÇÃO: remova este bloco antes da publicação se desejar um banco limpo.
INSERT INTO pedidos (id,numero,cliente_nome,cliente_whatsapp,descricao,valor_total,status_pagamento,valor_pago,forma_pagamento,previsao_entrega,prioridade,observacoes_internas,etapa,responsavel_id,criado_por_id,etapa_atualizada_em,created_at) VALUES
(1,'PF-2026-00001','Camila Santos','84999990001','30 camisetas com arte para evento corporativo.',480.00,'pago',480.00,'pix',DATE_ADD(NOW(),INTERVAL 1 DAY),'normal','Conferir tons de verde.','novo',2,1,NOW(),NOW()),
(2,'PF-2026-00002','Mercadinho Potiguar','84999990002','50 metros de filme DTF para uniformes.',1250.00,'parcial',500.00,'transferencia',DATE_ADD(NOW(),INTERVAL 2 DAY),'urgente','Cliente enviará logo atualizado.','preparacao',3,1,DATE_SUB(NOW(),INTERVAL 4 HOUR),DATE_SUB(NOW(),INTERVAL 1 DAY)),
(3,'PF-2026-00003','João Ribeiro','84999990003','12 estampas personalizadas tamanho A3.',240.00,'nao_pago',0.00,NULL,DATE_SUB(NOW(),INTERVAL 1 DAY),'urgente','Pedido atrasado: ligar para confirmar arte.','producao',2,2,DATE_SUB(NOW(),INTERVAL 28 HOUR),DATE_SUB(NOW(),INTERVAL 3 DAY)),
(4,'PF-2026-00004','Studio Maré','84999990004','Kit de estampas para coleção de verão.',890.00,'pago',890.00,'cartao',NOW(),'normal',NULL,'pronto',3,1,DATE_SUB(NOW(),INTERVAL 1 HOUR),DATE_SUB(NOW(),INTERVAL 2 DAY));
INSERT INTO pedido_etapas_historico (pedido_id,etapa_anterior,etapa_nova,usuario_id,created_at) VALUES
(1,NULL,'novo',1,NOW()),(2,NULL,'novo',1,DATE_SUB(NOW(),INTERVAL 1 DAY)),(2,'novo','preparacao',3,DATE_SUB(NOW(),INTERVAL 4 HOUR)),(3,NULL,'novo',2,DATE_SUB(NOW(),INTERVAL 3 DAY)),(3,'novo','preparacao',2,DATE_SUB(NOW(),INTERVAL 2 DAY)),(3,'preparacao','producao',2,DATE_SUB(NOW(),INTERVAL 28 HOUR)),(4,NULL,'novo',1,DATE_SUB(NOW(),INTERVAL 2 DAY)),(4,'novo','preparacao',3,DATE_SUB(NOW(),INTERVAL 1 DAY)),(4,'preparacao','producao',3,DATE_SUB(NOW(),INTERVAL 12 HOUR)),(4,'producao','pronto',3,DATE_SUB(NOW(),INTERVAL 1 HOUR));
INSERT INTO pedido_historico (pedido_id,usuario_id,acao,descricao,created_at) VALUES
(1,1,'criacao','Pedido criado.',NOW()),(2,3,'mudanca_etapa','Arte encaminhada para preparação.',DATE_SUB(NOW(),INTERVAL 4 HOUR)),(3,2,'mudanca_etapa','Início de produção.',DATE_SUB(NOW(),INTERVAL 28 HOUR)),(4,3,'mudanca_etapa','Pedido pronto para entrega.',DATE_SUB(NOW(),INTERVAL 1 HOUR));
INSERT INTO despesas (descricao,categoria,valor,data_despesa,observacao,status,criado_por_id) VALUES
('Filme DTF','material',320.00,CURDATE(),'Compra semanal de filme','ativa',1),('Energia elétrica','energia',185.50,DATE_SUB(CURDATE(),INTERVAL 2 DAY),'Conta proporcional','ativa',1),('Entrega local','transporte',45.00,DATE_SUB(CURDATE(),INTERVAL 1 DAY),'Motoboy','ativa',1);
INSERT INTO notificacoes (usuario_id,titulo,mensagem,link,tipo,lida_em) VALUES
(1,'Novo pedido','PF-2026-00001 criado por Administrador Print Fornece.','producao/detalhes.php?id=1','pedido',NULL),(1,'Pedido atrasado','PF-2026-00003 ultrapassou a previsão de entrega.','producao/detalhes.php?id=3','pedido',NULL),(2,'Pedido atribuído','Você é responsável pelo pedido PF-2026-00003.','producao/detalhes.php?id=3','pedido',NULL),(3,'Pedido pronto','PF-2026-00004 foi marcado como pronto.','producao/detalhes.php?id=4','pedido',NULL);

SET FOREIGN_KEY_CHECKS = 1;
