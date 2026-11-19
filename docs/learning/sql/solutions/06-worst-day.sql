-- Without window functions: compute every line-day share, find each line's
-- maximum, join back, and break ties with MIN(service_date).
-- With them: ROW_NUMBER() OVER (PARTITION BY line_id
--            ORDER BY share DESC, service_date) = 1.
WITH daily AS (
    SELECT t.line_id, t.service_date,
           AVG(CASE WHEN o.outcome = 'missed' THEN 1.0 ELSE 0.0 END) AS share
    FROM trips AS t
    JOIN trip_outcomes AS o ON o.trip_id = t.trip_id
    GROUP BY t.line_id, t.service_date
),
worst AS (
    SELECT line_id, MAX(share) AS share FROM daily GROUP BY line_id
)
SELECT d.line_id, MIN(d.service_date) AS service_date, ROUND(w.share, 3) AS missed_share
FROM daily AS d
JOIN worst AS w ON w.line_id = d.line_id AND w.share = d.share
GROUP BY d.line_id, w.share;
