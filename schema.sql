-- Run this once in your Supabase SQL editor:
-- https://supabase.com/dashboard/project/depyytfrakwsmjzkzecn/sql

-- ── 1. All Slack messages ─────────────────────────────────────────────────────

create table if not exists public.slack_messages (
  id              bigserial     primary key,

  -- Channel
  channel_id      text          not null,
  channel_name    text,

  -- Message identity
  message_ts      text          not null,   -- Slack timestamp (unique message ID)
  thread_ts       text,                     -- NULL = top-level; otherwise = parent message_ts

  -- Flags
  is_thread_reply boolean       not null default false,
  has_response    boolean       not null default false,

  -- Sender
  user_id         text,
  user_name       text,

  -- Content
  text            text,

  -- Timestamps
  created_at      timestamptz   not null,
  ingested_at     timestamptz   not null default now(),

  constraint slack_messages_unique unique (channel_id, message_ts)
);

create index if not exists slack_messages_thread_idx
  on public.slack_messages (channel_id, thread_ts);

create index if not exists slack_messages_unanswered_idx
  on public.slack_messages (has_response, created_at)
  where is_thread_reply = false;

create index if not exists slack_messages_channel_time_idx
  on public.slack_messages (channel_id, created_at desc);


-- ── 2. Unanswered alert events (analytics) ────────────────────────────────────
-- One row per alert fired. Lets you query: how often does this happen?
-- Which channels are worst? Which times of day? etc.

create table if not exists public.slack_unanswered_events (
  id              bigserial     primary key,

  channel_id      text          not null,
  channel_name    text,
  message_ts      text          not null,   -- the unanswered message
  user_id         text,
  user_name       text,
  message_text    text,

  timeout_minutes int           not null,   -- what timeout was configured when alert fired
  alerted_at      timestamptz   not null default now(),

  -- Did someone eventually respond after the alert?
  resolved_at     timestamptz,              -- NULL until marked resolved
  resolved        boolean       not null default false
);

create index if not exists slack_unanswered_channel_idx
  on public.slack_unanswered_events (channel_id, alerted_at desc);

create index if not exists slack_unanswered_unresolved_idx
  on public.slack_unanswered_events (resolved, alerted_at desc)
  where resolved = false;
