CREATE SCHEMA IF NOT EXISTS {s};

DO $ddl$
BEGIN
    CREATE TYPE {s}.strategy AS ENUM ('content', 'collaborative', 'hybrid');
EXCEPTION WHEN duplicate_object THEN
    NULL;
END;
$ddl$;

CREATE TABLE IF NOT EXISTS {s}.engines (
    engine_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE CHECK (char_length(trim(code)) >= 3),
    strategy {s}.strategy NOT NULL,
    features text[] NOT NULL CHECK (cardinality(features) > 0),
    enabled boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS {s}.benchmarks (
    benchmark_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    engine_id bigint NOT NULL REFERENCES {s}.engines(engine_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    corpus text NOT NULL CHECK (char_length(trim(corpus)) >= 3),
    checked_on date NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    hit_rate numeric(5,4) NOT NULL CHECK (hit_rate BETWEEN 0 AND 1),
    users_tested integer NOT NULL CHECK (users_tested > 0),
    remark text,
    UNIQUE (engine_id, corpus, checked_on)
);

CREATE TABLE IF NOT EXISTS {s}.releases (
    release_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    engine_id bigint NOT NULL REFERENCES {s}.engines(engine_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    version text NOT NULL CHECK (char_length(version) > 0),
    released_on date NOT NULL,
    UNIQUE (engine_id, version)
);
