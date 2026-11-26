-- AIS class of each position: 'A' (ships, messages 1/2/3) or 'B' (small craft,
-- messages 18/19), added in phase 13. Existing rows were all Class A, so the
-- constant default is correct for them; TimescaleDB allows adding a column with
-- a constant default to a compressed hypertable.
ALTER TABLE positions ADD COLUMN ais_class char(1) NOT NULL DEFAULT 'A';
