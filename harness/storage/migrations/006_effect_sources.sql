-- Which source text an effect was really applied from (architecture-skills-llm D8, revised
-- 2026-11-25): lets `architecture-memory` refuse the same source again before it asks the
-- model. One row per applied effect, written in the transaction that records it as applied
-- (or reconciled as applied); never for a rejected, abandoned or uncertain one. Never content and never a path:
--   scope          the effect (`vault.save_decision`);
--   partition_key  where the rule applies, chosen by the effect: for a decision, the digest of
--                  the vault root it is bound to and the project slug (`<digest>/<slug>`);
--   source_sha256  SHA-256 of the source input, BOM dropped and line ends normalised to LF;
--   effect_ref     what the effect applied (a `decision_id`), checked again in the vault.
-- Decisions saved before this migration have no row and are found only by the title check.
CREATE TABLE effect_sources (
    scope          TEXT NOT NULL,
    partition_key  TEXT NOT NULL,
    source_sha256  TEXT NOT NULL CHECK (length(source_sha256) = 64),
    effect_ref     TEXT NOT NULL,
    run_id         TEXT NOT NULL REFERENCES skill_runs (run_id),
    recorded_at    TEXT NOT NULL,
    PRIMARY KEY (scope, partition_key, source_sha256, effect_ref)
);
