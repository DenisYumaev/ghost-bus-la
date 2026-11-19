-- The inner join keeps classified trips only, which is the denominator.
-- AVG over a 0/1 CASE is the share. HAVING filters groups after aggregation;
-- WHERE can't see COUNT(*). In Postgres, integer / integer truncates:
-- SUM(missed) / COUNT(*) gives 0, so write 1.0 * SUM(...) / COUNT(*).
-- AVG over an integer CASE is safe there (it returns numeric).
SELECT t.line_id,
       t.service_date,
       COUNT(*) AS classified,
       ROUND(AVG(CASE WHEN o.outcome = 'missed' THEN 1.0 ELSE 0.0 END), 3) AS missed_share
FROM trips AS t
JOIN trip_outcomes AS o ON o.trip_id = t.trip_id
GROUP BY t.line_id, t.service_date
HAVING COUNT(*) >= 40;
