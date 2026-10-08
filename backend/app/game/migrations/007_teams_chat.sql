-- Teams of 3 (against bots: a trail of its own; between friends: a 3 against 3 format), and the chat of
-- friendly battles.
ALTER TABLE battles ADD COLUMN team INTEGER NOT NULL DEFAULT 0;
ALTER TABLE battle_progress ADD COLUMN team_cleared INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pvp ADD COLUMN team INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pvp ADD COLUMN challenger_pets TEXT;    -- the familiers chosen (ids, JSON), NULL: the active one
ALTER TABLE pvp ADD COLUMN opponent_pets TEXT;
CREATE TABLE pvp_chat (
  id INTEGER PRIMARY KEY,
  pvp_id INTEGER NOT NULL,
  user TEXT NOT NULL,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX pvp_chat_battle ON pvp_chat (pvp_id, id);
