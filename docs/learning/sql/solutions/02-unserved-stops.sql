-- NOT EXISTS ignores the NULL stop_id. NOT IN would compare every stop with
-- NULL, get UNKNOWN, and return no rows at all.
SELECT s.stop_id, s.stop_name
FROM stops AS s
WHERE NOT EXISTS (
    SELECT 1 FROM line_stops AS ls WHERE ls.stop_id = s.stop_id
);
