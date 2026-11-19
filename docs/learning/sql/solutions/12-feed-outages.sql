-- Gaps and islands. Number every row, and separately number the failed rows.
-- Inside one unbroken run of failures both counters rise by one per row, so
-- their difference is constant: that difference labels the island.
WITH numbered AS (
    SELECT feed, fetched_at, ok,
           ROW_NUMBER() OVER (PARTITION BY feed ORDER BY fetched_at)
         - ROW_NUMBER() OVER (PARTITION BY feed, ok ORDER BY fetched_at) AS island
    FROM fetch_log
)
SELECT feed,
       MIN(fetched_at) AS outage_start,
       MAX(fetched_at) AS outage_end,
       COUNT(*) AS minutes
FROM numbered
WHERE NOT ok
GROUP BY feed, island;
