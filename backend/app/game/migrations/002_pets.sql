-- Familiers. Type and stats come from the species (config) and the stage, level and branch stored here.
CREATE TABLE pets (
  id INTEGER PRIMARY KEY,
  user TEXT NOT NULL,
  species TEXT NOT NULL,
  name TEXT NOT NULL,
  stage INTEGER NOT NULL DEFAULT 0,
  level INTEGER NOT NULL DEFAULT 1,
  branch TEXT,                         -- the final form's branch, once evolved
  active INTEGER NOT NULL DEFAULT 0,
  origin TEXT NOT NULL,                -- starter, shop, pack…
  acquired_at TEXT NOT NULL,
  profile_since TEXT,                  -- running profile counted from this date (NULL: all the account's history)
  evolved_at TEXT
);
CREATE INDEX pets_user ON pets (user);
CREATE UNIQUE INDEX pets_one_starter ON pets (user) WHERE origin = 'starter';
CREATE UNIQUE INDEX pets_one_active ON pets (user) WHERE active = 1;
