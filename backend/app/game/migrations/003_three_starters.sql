-- The three starters can all be adopted, each once (one familier of each starter species per account).
DROP INDEX pets_one_starter;
CREATE UNIQUE INDEX pets_one_starter_species ON pets (user, species) WHERE origin = 'starter';
