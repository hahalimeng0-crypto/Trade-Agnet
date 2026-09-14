-- Customer accounts and authentication sessions are production MySQL data.

CREATE TABLE IF NOT EXISTS customer_account (
  account_id CHAR(36) NOT NULL,
  tenant_id VARCHAR(128) NOT NULL,
  status ENUM('active','locked','disabled','deleted') NOT NULL,
  preferred_locale VARCHAR(16) NOT NULL DEFAULT 'en',
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  last_login_at VARCHAR(40) NULL,
  deleted_at VARCHAR(40) NULL,
  version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  PRIMARY KEY (account_id),
  KEY idx_customer_account_tenant (tenant_id,status,account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS customer_auth_identity (
  identity_id CHAR(36) NOT NULL,
  account_id CHAR(36) NOT NULL,
  tenant_id VARCHAR(128) NOT NULL,
  identifier_type VARCHAR(32) NOT NULL,
  identifier_normalized VARCHAR(191) NOT NULL,
  credential_hash VARCHAR(255) NOT NULL,
  failed_attempts INT UNSIGNED NOT NULL DEFAULT 0,
  locked_until VARCHAR(40) NULL,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  PRIMARY KEY (identity_id),
  UNIQUE KEY uq_customer_auth_identifier (tenant_id,identifier_type,identifier_normalized),
  KEY idx_customer_auth_account (tenant_id,account_id),
  CONSTRAINT fk_customer_auth_account FOREIGN KEY (account_id) REFERENCES customer_account(account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS customer_auth_session (
  session_id CHAR(36) NOT NULL,
  account_id CHAR(36) NOT NULL,
  tenant_id VARCHAR(128) NOT NULL,
  token_hash CHAR(64) NOT NULL,
  csrf_hash CHAR(64) NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  last_seen_at VARCHAR(40) NOT NULL,
  idle_expires_at VARCHAR(40) NOT NULL,
  absolute_expires_at VARCHAR(40) NOT NULL,
  revoked_at VARCHAR(40) NULL,
  PRIMARY KEY (session_id),
  UNIQUE KEY uq_customer_auth_token (token_hash),
  KEY idx_customer_auth_session_account (tenant_id,account_id,revoked_at),
  CONSTRAINT fk_customer_session_account FOREIGN KEY (account_id) REFERENCES customer_account(account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
