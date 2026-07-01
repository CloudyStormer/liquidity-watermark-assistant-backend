PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  openid TEXT PRIMARY KEY,
  nickname TEXT,
  avatar_url TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_jobs (
  id TEXT PRIMARY KEY,
  openid TEXT NOT NULL,
  media_type TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  source_path TEXT NOT NULL,
  result_path TEXT,
  result_media_type TEXT,
  result_md5 TEXT,
  method TEXT NOT NULL,
  status TEXT NOT NULL,
  regions_json TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (openid) REFERENCES users(openid)
);

CREATE INDEX IF NOT EXISTS idx_media_jobs_openid_created
ON media_jobs(openid, created_at DESC);

CREATE TABLE IF NOT EXISTS daily_quotas (
  openid TEXT NOT NULL,
  quota_date TEXT NOT NULL,
  used INTEGER NOT NULL DEFAULT 0,
  bonus INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (openid, quota_date),
  FOREIGN KEY (openid) REFERENCES users(openid)
);

CREATE INDEX IF NOT EXISTS idx_daily_quotas_openid_date
ON daily_quotas(openid, quota_date DESC);

CREATE TABLE IF NOT EXISTS ratings (
  id TEXT PRIMARY KEY,
  openid TEXT NOT NULL,
  score INTEGER NOT NULL,
  comment TEXT,
  job_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (openid) REFERENCES users(openid)
);

CREATE INDEX IF NOT EXISTS idx_ratings_openid_created
ON ratings(openid, created_at DESC);

CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  openid TEXT NOT NULL,
  type TEXT NOT NULL,
  content TEXT NOT NULL,
  contact TEXT,
  job_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (openid) REFERENCES users(openid)
);

CREATE INDEX IF NOT EXISTS idx_feedback_openid_created
ON feedback(openid, created_at DESC);

CREATE TABLE IF NOT EXISTS operation_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  openid TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  detail_json TEXT NOT NULL,
  ip TEXT,
  user_agent TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operation_logs_openid_created
ON operation_logs(openid, created_at DESC);
