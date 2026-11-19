-- The bootstrap's draw function behaves like random sampling with replacement, for many stratum
-- sizes including powers of two (where DuckDB's plain multi-argument hash fails: every replicate
-- drew the same number of distinct dates). For R = 1000 replicates of n draws each:
-- * the mean number of distinct dates per replicate is within 5% of n (1 - (1 - 1/n)^n);
-- * that number varies between replicates (n >= 3);
-- * every date index is drawn R times +- 5 sqrt(R) in total.
with sizes as (
    select unnest([2, 3, 4, 5, 7, 13, 16, 20, 28, 32, 64, 90, 128]) as n
),

draws as (
    select s.n, r.replicate,
           {{ bootstrap_draw("'test'", "'weekday'", 'r.replicate', 'k.draw', 's.n') }} as date_index
    from sizes as s
    cross join range(1, 1001) as r(replicate)
    cross join lateral (select unnest(range(s.n)) as draw) as k
),

per_replicate as (
    select n, replicate, count(distinct date_index) as n_distinct from draws group by n, replicate
),

spread as (
    select n, avg(n_distinct) as mean_distinct, stddev_samp(n_distinct) as sd_distinct
    from per_replicate group by n
),

per_index as (
    select n, date_index, count(*) as times from draws group by n, date_index
)

select 'distinct dates' as problem, n from spread
where abs(mean_distinct - n * (1 - power(1 - 1.0 / n, n))) > 0.05 * n * (1 - power(1 - 1.0 / n, n))
   or (n >= 3 and sd_distinct = 0)
union all
select 'uneven draws', n from per_index
where abs(times - 1000) > 5 * sqrt(1000)
union all
select 'missing index', s.n from sizes as s
where (select count(*) from per_index as p where p.n = s.n) <> s.n
