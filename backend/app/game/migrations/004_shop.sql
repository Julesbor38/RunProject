-- Shop purchases (items paid in points or gems) and gem purchases (real money, through a payment provider).
CREATE TABLE purchases (
  id INTEGER PRIMARY KEY,
  user TEXT NOT NULL,
  item TEXT NOT NULL,                  -- a shop item id, or a gem pack id
  currency TEXT NOT NULL,              -- points, gems, or eur (a gem pack)
  price REAL NOT NULL,
  request_id TEXT NOT NULL,
  provider TEXT,                       -- gem packs: mock, appstore, stripe…
  receipt TEXT,                        -- gem packs: the provider's proof of payment
  pet_id INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (user, request_id)
);
CREATE INDEX purchases_user ON purchases (user, id);
-- A shop familier is sold once per account.
CREATE UNIQUE INDEX pets_one_shop_species ON pets (user, species) WHERE origin = 'shop';
