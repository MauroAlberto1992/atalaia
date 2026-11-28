-- Declared static AIS data per ship (phase 17a): type code (ITU-R M.1371) and
-- maximum static draught in metres. NULL until a static message is received.
ALTER TABLE ships ADD COLUMN ship_type smallint;
ALTER TABLE ships ADD COLUMN draught_m real;
