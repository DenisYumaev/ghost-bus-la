-- One row per line x direction: (line, direction_id). Feeds serving.line_direction; the API
-- returns a headsign with every direction_id (API spec, section 1). Metro's trips.txt leaves
-- trip_headsign empty, but stop_times.txt carries stop_headsign ("754 - Vermont / Athens
-- Station"), so the headsign is the most common stop_headsign at the trips' first stops, with
-- the "<line> - " prefix removed (ties: alphabetical). On combined lines the prefix is one part
-- of the line ("14 - Washington / Fairfax Transit Hub" on 14/37) and says which sub-line runs
-- that direction, so it stays. Dashes inside names ("Hollywood - Vine Station") stay too. If no
-- trip has a headsign, the main pattern's last stop name. first_stop_name and last_stop_name are
-- the main pattern's ends.
with first_visits as (
    select line, direction_id, stop_headsign
    from {{ ref('int_line_trip_stops') }}
    qualify row_number() over (partition by trip_id order by stop_sequence) = 1
),

headsigns as (
    select
        line,
        direction_id,
        case
            when starts_with(stop_headsign, line || ' - ')
                then substr(stop_headsign, length(line) + 4)
            else stop_headsign
        end as headsign
    from first_visits
    where nullif(trim(stop_headsign), '') is not null
),

top_headsign as (
    select line, direction_id, headsign
    from headsigns
    group by line, direction_id, headsign
    qualify row_number() over (partition by line, direction_id order by count(*) desc, headsign) = 1
),

main_trip as (
    select line, direction_id, min(trip_id) as trip_id
    from {{ ref('int_line_trip_stops') }}
    where is_main_pattern
    group by line, direction_id
),

main_ends as (
    select
        m.line,
        m.direction_id,
        arg_min(s.stop_id, s.stop_sequence) as first_stop_id,
        arg_max(s.stop_id, s.stop_sequence) as last_stop_id,
        any_value(s.schedule_version) as schedule_version
    from main_trip as m
    inner join {{ ref('int_line_trip_stops') }} as s on m.trip_id = s.trip_id
    group by m.line, m.direction_id
),

sizes as (
    select line, direction_id, count(distinct pattern) as n_patterns, count(distinct trip_id) as n_trips
    from {{ ref('int_line_trip_stops') }}
    group by line, direction_id
)

select
    e.line,
    e.direction_id,
    coalesce(h.headsign, l.stop_name) as headsign,
    f.stop_name as first_stop_name,
    l.stop_name as last_stop_name,
    z.n_patterns,
    z.n_trips
from main_ends as e
inner join sizes as z on e.line = z.line and e.direction_id = z.direction_id
left join top_headsign as h on e.line = h.line and e.direction_id = h.direction_id
left join {{ ref('dim_stops') }} as f
    on e.schedule_version = f.schedule_version and e.first_stop_id = f.stop_id
left join {{ ref('dim_stops') }} as l
    on e.schedule_version = l.schedule_version and e.last_stop_id = l.stop_id
