-- What each effect of a run fixed when the run was created (architecture-skills-llm, revised
-- 2026-11-25 after an independent review): canonical JSON {scope: {key: value}} of short
-- strings, for example the local date of a decision note and a digest of the vault root it is
-- bound to. Never a path, never content. NULL for runs created before this migration.
ALTER TABLE skill_runs ADD COLUMN effect_bindings TEXT;
