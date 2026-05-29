-- Consolidated initial schema for Bedtime D&D
-- This represents the final state of all tables, RLS policies, triggers, storage, and realtime.
-- Fully idempotent — safe to run against an existing database.

-- ============================================================================
-- TABLES
-- ============================================================================

-- Profiles (1:1 with auth.users)
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null,
  created_at timestamptz default now()
);

-- Players (character sheets)
create table if not exists players (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id) on delete cascade,
  name text not null,
  class text not null,
  might int not null default 3,
  agility int not null default 3,
  wits int not null default 3,
  max_hp int not null default 10,
  avatar_url text,
  description text,
  visual_description text,
  level int default 1,
  unspent_points int default 0,
  xp int default 0,
  created_at timestamptz default now()
);

-- Campaigns
create table if not exists campaigns (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id) on delete cascade,
  name text not null,
  summary text,
  difficulty text default 'normal',
  style text,
  rating text default 'campfire',
  current_turn_profile_id uuid references profiles(id),
  last_played_at timestamptz default now(),
  created_at timestamptz default now()
);

-- Campaign Members (live state per character per campaign)
create table if not exists campaign_members (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  player_id uuid not null references players(id) on delete cascade,
  current_hp int not null,
  inventory jsonb default '[]'::jsonb,
  sort_order int default 0
);

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'campaign_members_campaign_id_player_id_key') then
    alter table campaign_members add constraint campaign_members_campaign_id_player_id_key unique (campaign_id, player_id);
  end if;
end $$;

-- Game Logs (narrative history)
create table if not exists game_logs (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  role text not null check (role in ('user', 'model')),
  content text not null,
  turn_number int,
  image_url text,
  created_at timestamptz default now()
);

-- Game Events (audit trail)
create table if not exists game_events (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  player_id uuid references players(id) on delete set null,
  event_type text not null,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz default now()
);

-- Game Summaries (long-term memory)
create table if not exists game_summaries (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  from_turn int not null,
  to_turn int not null,
  summary text not null,
  created_at timestamptz default now()
);

-- Campaign Shares (multi-household access)
create table if not exists campaign_shares (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  profile_id uuid not null references profiles(id) on delete cascade,
  created_at timestamptz default now(),
  unique (campaign_id, profile_id)
);

-- Friendships
create table if not exists friendships (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id) on delete cascade,
  friend_id uuid not null references profiles(id) on delete cascade,
  created_at timestamptz default now(),
  unique (profile_id, friend_id)
);

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================

alter table profiles enable row level security;
alter table players enable row level security;
alter table campaigns enable row level security;
alter table campaign_members enable row level security;
alter table game_logs enable row level security;
alter table game_events enable row level security;
alter table game_summaries enable row level security;
alter table campaign_shares enable row level security;
alter table friendships enable row level security;

-- Helper function: check if user has shared access to a campaign (bypasses RLS)
create or replace function is_campaign_member(cid uuid)
returns boolean as $$
  select exists (
    select 1 from campaign_shares where campaign_id = cid and profile_id = auth.uid()
  );
$$ language sql security definer stable set search_path = public;

-- Profiles
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'profiles' and policyname = 'Users can read own profile') then
    create policy "Users can read own profile" on profiles for select using (auth.uid() = id);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'profiles' and policyname = 'Users can update own profile') then
    create policy "Users can update own profile" on profiles for update using (auth.uid() = id);
  end if;
end $$;

-- Players
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'players' and policyname = 'Owners manage their players') then
    create policy "Owners manage their players" on players for all using (auth.uid() = profile_id);
  end if;
end $$;

-- Campaigns (owner or shared member)
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'campaigns' and policyname = 'Owners and shared users access campaigns') then
    create policy "Owners and shared users access campaigns" on campaigns for all
      using (profile_id = auth.uid() or is_campaign_member(id));
  end if;
end $$;

-- Campaign Members
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'campaign_members' and policyname = 'Campaign owners manage members') then
    create policy "Campaign owners manage members" on campaign_members for all
      using (exists (select 1 from campaigns where campaigns.id = campaign_members.campaign_id and campaigns.profile_id = auth.uid()));
  end if;
end $$;

-- Game Logs (owner or shared)
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'game_logs' and policyname = 'Campaign participants manage logs') then
    create policy "Campaign participants manage logs" on game_logs for all
      using (exists (
        select 1 from campaigns
        where campaigns.id = game_logs.campaign_id
          and (campaigns.profile_id = auth.uid() or is_campaign_member(campaigns.id))
      ));
  end if;
end $$;

-- Game Events (owner or shared)
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'game_events' and policyname = 'Campaign participants manage events') then
    create policy "Campaign participants manage events" on game_events for all
      using (exists (
        select 1 from campaigns
        where campaigns.id = game_events.campaign_id
          and (campaigns.profile_id = auth.uid() or is_campaign_member(campaigns.id))
      ));
  end if;
end $$;

-- Game Summaries
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'game_summaries' and policyname = 'Campaign owners manage summaries') then
    create policy "Campaign owners manage summaries" on game_summaries for all
      using (exists (select 1 from campaigns where campaigns.id = game_summaries.campaign_id and campaigns.profile_id = auth.uid()));
  end if;
end $$;

-- Campaign Shares
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'campaign_shares' and policyname = 'Users see own shares') then
    create policy "Users see own shares" on campaign_shares for select
      using (profile_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where tablename = 'campaign_shares' and policyname = 'Anyone can insert shares') then
    create policy "Anyone can insert shares" on campaign_shares for insert
      with check (true);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'campaign_shares' and policyname = 'Owners delete shares') then
    create policy "Owners delete shares" on campaign_shares for delete
      using (profile_id = auth.uid());
  end if;
end $$;

-- Friendships
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'friendships' and policyname = 'Users see own friendships') then
    create policy "Users see own friendships" on friendships for select
      using (profile_id = auth.uid() or friend_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where tablename = 'friendships' and policyname = 'Users manage own friendships') then
    create policy "Users manage own friendships" on friendships for all
      using (profile_id = auth.uid());
  end if;
end $$;

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Auto-create profile on signup
create or replace function handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'display_name', new.email));
  return new;
end;
$$ language plpgsql security definer set search_path = public;

grant usage on schema public to supabase_auth_admin;
grant insert on profiles to supabase_auth_admin;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- Auto-assign turn_number on game_logs insert
create or replace function set_turn_number()
returns trigger as $$
begin
  new.turn_number := coalesce(
    (select max(turn_number) from game_logs where campaign_id = new.campaign_id), 0
  ) + 1;
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_set_turn_number on game_logs;
create trigger trg_set_turn_number
  before insert on game_logs
  for each row execute function set_turn_number();

-- ============================================================================
-- STORAGE
-- ============================================================================

insert into storage.buckets (id, name, public)
values ('avatars', 'avatars', true)
on conflict (id) do nothing;

do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'objects' and policyname = 'Authenticated users can upload avatars') then
    create policy "Authenticated users can upload avatars"
    on storage.objects for insert
    to authenticated
    with check (bucket_id = 'avatars');
  end if;
  if not exists (select 1 from pg_policies where tablename = 'objects' and policyname = 'Anyone can view avatars') then
    create policy "Anyone can view avatars"
    on storage.objects for select
    to public
    using (bucket_id = 'avatars');
  end if;
  if not exists (select 1 from pg_policies where tablename = 'objects' and policyname = 'Users can delete their own avatars') then
    create policy "Users can delete their own avatars"
    on storage.objects for delete
    to authenticated
    using (bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text);
  end if;
end $$;

-- ============================================================================
-- REALTIME
-- ============================================================================

alter publication supabase_realtime add table game_logs;
