-- 108_auth_privacy_hardening.sql
-- Keep auth tables server-side only. The application DB role is intentionally
-- separate from Supabase Data API roles; no client-side table access is needed.

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE signup_requests ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE users FROM PUBLIC;
REVOKE ALL ON TABLE users FROM anon, authenticated;
REVOKE ALL ON TABLE signup_requests FROM PUBLIC;
REVOKE ALL ON TABLE signup_requests FROM anon, authenticated;

REVOKE ALL ON SEQUENCE signup_requests_request_id_seq FROM PUBLIC;
REVOKE ALL ON SEQUENCE signup_requests_request_id_seq FROM anon, authenticated;
