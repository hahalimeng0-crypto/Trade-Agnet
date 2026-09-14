-- Enterprise knowledge metadata authority. Binary/parsed artifacts stay in file storage.

CREATE TABLE IF NOT EXISTS rag_manifest_state (
  singleton_id TINYINT UNSIGNED NOT NULL,
  schema_version VARCHAR(64) NOT NULL,
  revision BIGINT UNSIGNED NOT NULL DEFAULT 0,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (singleton_id),
  CONSTRAINT chk_rag_manifest_singleton CHECK (singleton_id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS rag_document_metadata (
  metadata_id CHAR(64) NOT NULL,
  document_id VARCHAR(191) NOT NULL,
  document_version INT UNSIGNED NOT NULL,
  source_hash CHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  index_status VARCHAR(32) NOT NULL,
  classification VARCHAR(32) NOT NULL,
  business_unit_id VARCHAR(128) NOT NULL,
  sequence_no INT UNSIGNED NOT NULL,
  payload_json JSON NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (metadata_id),
  KEY idx_rag_document_lookup (document_id,document_version),
  KEY idx_rag_document_work (index_status,status,updated_at),
  KEY idx_rag_document_acl (business_unit_id,classification,status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS rag_index_job (
  job_id CHAR(64) NOT NULL,
  metadata_id CHAR(64) NOT NULL,
  document_id VARCHAR(191) NOT NULL,
  document_version INT UNSIGNED NOT NULL,
  operation ENUM('index','delete') NOT NULL,
  status ENUM('pending','running','completed','failed') NOT NULL DEFAULT 'pending',
  attempt_count INT UNSIGNED NOT NULL DEFAULT 0,
  last_error TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (job_id),
  KEY idx_rag_index_job_work (status,updated_at),
  KEY idx_rag_index_job_document (document_id,document_version,operation)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS rag_parent_chunk (
  parent_id VARCHAR(191) NOT NULL,
  document_id VARCHAR(191) NOT NULL,
  document_version INT UNSIGNED NOT NULL,
  content_hash CHAR(64) NOT NULL,
  parent_text MEDIUMTEXT NOT NULL,
  parent_location TEXT NOT NULL,
  metadata_json JSON NOT NULL,
  business_unit_id VARCHAR(128) NOT NULL,
  allowed_roles_json JSON NOT NULL,
  source_status VARCHAR(32) NOT NULL,
  effective_from VARCHAR(40) NULL,
  expires_at VARCHAR(40) NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (parent_id),
  KEY idx_rag_parent_document (document_id,document_version),
  KEY idx_rag_parent_acl (business_unit_id,source_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
