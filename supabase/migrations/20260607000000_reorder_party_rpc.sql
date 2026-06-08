create or replace function reorder_party(p_campaign_id uuid, p_order uuid[])
returns void language plpgsql security definer as $$
begin
  for i in 1..array_length(p_order, 1) loop
    update campaign_members
    set sort_order = i - 1
    where campaign_id = p_campaign_id and player_id = p_order[i];
  end loop;
end;
$$;
