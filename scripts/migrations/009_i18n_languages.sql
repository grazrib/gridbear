-- Migration: 009_i18n_languages
-- Odoo-style language management table

CREATE SCHEMA IF NOT EXISTS i18n;

CREATE TABLE i18n.languages (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    active      BOOLEAN DEFAULT FALSE,
    direction   TEXT DEFAULT 'ltr',
    date_format TEXT DEFAULT '%Y-%m-%d',
    is_default  BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Seed default languages
INSERT INTO i18n.languages (code, name, active, is_default) VALUES
    ('en', 'English', TRUE, TRUE),
    ('it', 'Italiano', TRUE, FALSE);
