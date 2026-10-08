-- Battles against bots: the state after each turn, the initial state and the player's moves (to replay it).
CREATE TABLE battles (
  id INTEGER PRIMARY KEY,
  user TEXT NOT NULL,
  pet_id INTEGER NOT NULL,
  level INTEGER NOT NULL,
  seed TEXT NOT NULL,
  initial TEXT NOT NULL,
  state TEXT NOT NULL,
  actions TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,                -- running, won, lost, fled
  reward INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE INDEX battles_user ON battles (user, id);
-- The highest level won by each account (the next one is open).
CREATE TABLE battle_progress (
  user TEXT PRIMARY KEY,
  cleared INTEGER NOT NULL DEFAULT 0
);
