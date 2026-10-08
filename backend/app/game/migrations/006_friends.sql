-- Friendships: one row per pair (user_a < user_b): a request (pending), a friendship (accepted), or a block.
CREATE TABLE friendships (
  user_a TEXT NOT NULL,
  user_b TEXT NOT NULL,
  status TEXT NOT NULL,                -- pending, accepted, blocked
  requested_by TEXT,
  blocked_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_a, user_b),
  CHECK (user_a < user_b)
);
CREATE INDEX friendships_b ON friendships (user_b);
-- Friendly battles, live: the challenger plays the engine's "player" side, the friend its "enemy" side.
CREATE TABLE pvp (
  id INTEGER PRIMARY KEY,
  challenger TEXT NOT NULL,
  opponent TEXT NOT NULL,
  mode TEXT NOT NULL,                  -- normal (familiers as they are), balanced (same stage and level)
  status TEXT NOT NULL,                -- invited, running, done, declined, cancelled, expired
  seed TEXT NOT NULL,
  initial TEXT,
  state TEXT,
  actions TEXT NOT NULL DEFAULT '[]',  -- per round: {fighter id: [move, target]}
  rounds TEXT NOT NULL DEFAULT '[]',   -- per round: the events to animate
  pending TEXT NOT NULL DEFAULT '{}',  -- the moves already chosen this round, per side
  misses TEXT NOT NULL DEFAULT '{}',   -- rounds missed in a row, per side
  deadline TEXT,
  winner TEXT,                         -- a user name, or NULL: a draw (or not finished)
  end_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX pvp_challenger ON pvp (challenger, id);
CREATE INDEX pvp_opponent ON pvp (opponent, id);
