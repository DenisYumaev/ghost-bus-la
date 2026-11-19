-- The date filter belongs in the ON clause. In WHERE it runs after the join,
-- throws away line 901's NULL row, and the zero disappears.
-- COUNT(t.trip_id) counts non-NULL values, so the padded row counts as 0;
-- COUNT(*) would count it as 1.
SELECT l.line_id, COUNT(t.trip_id) AS trips
FROM lines AS l
LEFT JOIN trips AS t
    ON t.line_id = l.line_id
   AND t.service_date = DATE '2026-11-02'
GROUP BY l.line_id;
