-- Proposal only. Do not execute without owner/team approval.
--
-- Existing db/104_user_profiles.sql is intentionally unchanged. These nullable
-- encrypted columns let old profile rows remain readable while new onboarding
-- rows can persist the two currently missing fields.
--
-- Values must be sealed with the existing ProfileCipher using the same
-- user_id|field-name AAD and key_version contract as the four existing fields.
-- No plaintext fallback or JSON packing into an existing column is allowed.

ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS role_enc bytea,
    ADD COLUMN IF NOT EXISTS service_enc bytea;

-- Backward compatibility: existing rows remain NULL until the owner-approved
-- application rollout writes these fields. New application validation must
-- require them only for profiles created/updated after the rollout.
