-- NanoClaw structured long-term memory (MySQL 8 / InnoDB / utf8mb4).
-- Select the database configured by NANOCLAW_MEMORY_MYSQL_DATABASE before running.

CREATE TABLE IF NOT EXISTS customer_memory_consent (
  consent_record_id VARCHAR(64) PRIMARY KEY,
  tenant_id VARCHAR(128) NOT NULL,
  account_id VARCHAR(128) NOT NULL,
  purpose VARCHAR(128) NOT NULL,
  categories_json JSON NOT NULL,
  status VARCHAR(32) NOT NULL,
  granted_at VARCHAR(40) NOT NULL,
  expires_at VARCHAR(40) NULL,
  withdrawn_at VARCHAR(40) NULL,
  KEY ix_customer_consent_scope (tenant_id, account_id, purpose, status, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS customer_memory_item (
  memory_id VARCHAR(64) PRIMARY KEY,
  tenant_id VARCHAR(128) NOT NULL,
  account_id VARCHAR(128) NOT NULL,
  conversation_id VARCHAR(191) NULL,
  memory_type VARCHAR(32) NOT NULL,
  purpose VARCHAR(128) NOT NULL,
  content TEXT NOT NULL,
  summary TEXT NOT NULL,
  source_refs_json JSON NOT NULL,
  status VARCHAR(32) NOT NULL,
  confidence DOUBLE NOT NULL,
  importance DOUBLE NOT NULL,
  sensitivity VARCHAR(32) NOT NULL,
  consent_record_id VARCHAR(64) NULL,
  version INT NOT NULL,
  supersedes VARCHAR(64) NULL,
  content_hash CHAR(64) NOT NULL,
  embedding_model VARCHAR(191) NULL,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  valid_from VARCHAR(40) NOT NULL,
  expires_at VARCHAR(40) NULL,
  invalid_reason VARCHAR(255) NULL,
  live_content_hash CHAR(64) GENERATED ALWAYS AS
    (CASE WHEN status IN ('pending_consent','active') THEN content_hash ELSE NULL END) STORED,
  UNIQUE KEY uq_customer_memory_live_hash
    (tenant_id, account_id, purpose, live_content_hash),
  KEY ix_customer_memory_scope
    (tenant_id, account_id, purpose, status, expires_at),
  CONSTRAINT fk_customer_memory_consent FOREIGN KEY (consent_record_id)
    REFERENCES customer_memory_consent(consent_record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS memory_deletion_job (
  job_id VARCHAR(64) PRIMARY KEY,
  tenant_id VARCHAR(128) NOT NULL,
  account_id VARCHAR(128) NULL,
  conversation_id VARCHAR(191) NULL,
  request_id VARCHAR(191) NOT NULL UNIQUE,
  status VARCHAR(32) NOT NULL,
  steps_json JSON NOT NULL,
  attempt_count INT NOT NULL DEFAULT 0,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  completed_at VARCHAR(40) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS memory_index_outbox (
  event_id VARCHAR(64) PRIMARY KEY,
  store_kind VARCHAR(32) NOT NULL,
  aggregate_id VARCHAR(64) NOT NULL,
  event_type VARCHAR(32) NOT NULL,
  payload_json JSON NOT NULL,
  status VARCHAR(32) NOT NULL,
  attempt_count INT NOT NULL DEFAULT 0,
  available_at VARCHAR(40) NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  KEY ix_memory_index_outbox_due (status, available_at, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS workspace_memory_item (
  memory_id VARCHAR(64) PRIMARY KEY,
  tenant_id VARCHAR(128) NOT NULL,
  subject_id VARCHAR(128) NULL,
  project_id VARCHAR(128) NULL,
  memory_type VARCHAR(32) NOT NULL,
  purpose VARCHAR(128) NOT NULL,
  content TEXT NOT NULL,
  summary TEXT NOT NULL,
  source_refs_json JSON NOT NULL,
  status VARCHAR(32) NOT NULL,
  confidence DOUBLE NOT NULL,
  importance DOUBLE NOT NULL,
  sensitivity VARCHAR(32) NOT NULL,
  version INT NOT NULL,
  supersedes VARCHAR(64) NULL,
  content_hash CHAR(64) NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  valid_from VARCHAR(40) NOT NULL,
  expires_at VARCHAR(40) NULL,
  live_content_hash CHAR(64) GENERATED ALWAYS AS
    (CASE WHEN status IN ('pending_confirmation','active') THEN content_hash ELSE NULL END) STORED,
  UNIQUE KEY uq_workspace_memory_live_hash
    (tenant_id, subject_id, project_id, purpose, live_content_hash),
  KEY ix_workspace_memory_scope
    (tenant_id, subject_id, project_id, purpose, status, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS workspace_memory_index_outbox (
  event_id VARCHAR(64) PRIMARY KEY,
  aggregate_id VARCHAR(64) NOT NULL,
  event_type VARCHAR(32) NOT NULL,
  payload_json JSON NOT NULL,
  status VARCHAR(32) NOT NULL,
  attempt_count INT NOT NULL DEFAULT 0,
  available_at VARCHAR(40) NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  KEY ix_workspace_memory_index_due (status, available_at, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS workspace_memory_review_suggestion (
  suggestion_id VARCHAR(64) PRIMARY KEY,
  tenant_id VARCHAR(128) NOT NULL,
  subject_id VARCHAR(128) NOT NULL,
  project_id VARCHAR(128) NOT NULL,
  action VARCHAR(32) NOT NULL,
  memory_ids_json JSON NOT NULL,
  rationale TEXT NOT NULL,
  status VARCHAR(32) NOT NULL,
  content_hash CHAR(64) NOT NULL,
  version INT NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
