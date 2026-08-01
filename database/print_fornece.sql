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

-- O esquema não cria contas, senhas ou dados de demonstração. Após a primeira
-- inicialização, execute scripts/create-admin.php para criar o administrador
-- com uma senha escolhida localmente.


SET FOREIGN_KEY_CHECKS = 1;
