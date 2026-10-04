-- Run this once in Supabase: Dashboard -> SQL Editor -> New query -> paste -> Run.
--
-- This creates the `profiles` table (the app-data counterpart to Supabase's
-- built-in `auth.users`) and turns on Row Level Security for it.
--
-- IMPORTANT CAVEAT — read this before assuming RLS alone protects you:
-- your FastAPI backend connects to Postgres with the connection string
-- from Project Settings -> Database (typically the `postgres` role, or a
-- role you create), which by default BYPASSES RLS as the table owner /
-- a sufficiently privileged role. RLS as written here protects data
-- reached through Supabase's own PostgREST/client-side API (the anon or
-- authenticated keys), NOT queries your backend makes directly over
-- SQLAlchemy. Your backend's actual authorization boundary is the
-- `WHERE user_id = current_user.id` filters already in every router
-- (routers/videos.py, routers/notes.py) — those are what's actually
-- enforced today. The policies below are still worth having:
--   1. Defense in depth if your DB credentials or a raw connection string
--      ever leak — an attacker with just the anon key still can't read
--      other users' rows.
--   2. Required if you ever add a client that talks to Supabase directly
--      (e.g. Claude in Excel/Sheets prototyping, or a future mobile app
--      using the Supabase SDK instead of going through this backend).
-- If you want your FastAPI connection itself to be RLS-constrained, create
-- a dedicated least-privilege Postgres role for it (not the default
-- `postgres` role) and grant it only what it needs — ask if you want that
-- role + grants written out too.

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  display_name text not null default '',
  plan text not null default 'free',
  llm_credits integer not null default 0,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "profiles: read own row"
  on public.profiles for select
  using (auth.uid() = id);

create policy "profiles: update own row"
  on public.profiles for update
  using (auth.uid() = id);

-- No insert/delete policy: rows are created by the backend on first login
-- (using the postgres/service connection, which bypasses RLS as noted
-- above) and deleted automatically via the FK's ON DELETE CASCADE when
-- the auth.users row is deleted.

-- ---------------------------------------------------------------------
-- The same pattern applies to every other app table (videos, sessions,
-- transcript_segments, visual_events, note_sections, note_assets,
-- exports, consent_log, llm_jobs) if you want RLS on them too — enable
-- RLS, then a policy like:
--
--   create policy "videos: owner only"
--     on public.videos for select using (auth.uid() = user_id);
--
-- for tables with a direct user_id column, or a join through videos/
-- sessions for tables that only have session_id/video_id. Ask and I'll
-- generate the full set for all nine tables rather than you writing
-- them by hand.
-- ---------------------------------------------------------------------
