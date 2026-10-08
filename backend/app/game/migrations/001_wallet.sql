-- Wallet: balances kept up to date in the same transaction as the ledger row that changes them.
CREATE TABLE wallets (
  user TEXT PRIMARY KEY,
  points INTEGER NOT NULL DEFAULT 0 CHECK (points >= 0),
  gems INTEGER NOT NULL DEFAULT 0 CHECK (gems >= 0)
);
-- Ledger: every gain and spending, once per key (a re-import, a retried request never counts twice).
-- history = 1: earned before the account's points began, only counts in the capped welcome bonus.
CREATE TABLE transactions (
  id INTEGER PRIMARY KEY,
  user TEXT NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('points', 'gems')),
  amount INTEGER NOT NULL,
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  date TEXT,
  detail TEXT NOT NULL DEFAULT '{}',
  history INTEGER NOT NULL DEFAULT 0,
  balance_after INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (user, currency, key)
);
CREATE INDEX transactions_user ON transactions (user, currency, id);
-- When the account's points began, and the last gain already announced.
CREATE TABLE accounts (
  user TEXT PRIMARY KEY,
  points_start TEXT NOT NULL,
  seen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
