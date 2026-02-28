-- 007: Drop full-text search column (incompatible with encrypted content)
-- The content_tsv GENERATED column references plaintext content, which
-- will now be stored encrypted. FTS is replaced by app-level search.

DROP INDEX IF EXISTS chat.idx_chat_history_fts;
ALTER TABLE chat.chat_history DROP COLUMN IF EXISTS content_tsv;
