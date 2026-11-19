-- Conditional aggregation: one pass, one CASE per column. A trip with no
-- outcome row survives the LEFT JOIN with o.trip_id NULL, which is how the
-- unclassified column finds it. (DuckDB and Postgres also accept
-- COUNT(*) FILTER (WHERE ...).)
SELECT t.line_id,
       SUM(CASE WHEN o.outcome = 'ran'      THEN 1 ELSE 0 END) AS ran,
       SUM(CASE WHEN o.outcome = 'partial'  THEN 1 ELSE 0 END) AS partial,
       SUM(CASE WHEN o.outcome = 'missed'   THEN 1 ELSE 0 END) AS missed,
       SUM(CASE WHEN o.outcome = 'canceled' THEN 1 ELSE 0 END) AS canceled,
       SUM(CASE WHEN o.trip_id IS NULL      THEN 1 ELSE 0 END) AS unclassified
FROM trips AS t
LEFT JOIN trip_outcomes AS o ON o.trip_id = t.trip_id
GROUP BY t.line_id;
