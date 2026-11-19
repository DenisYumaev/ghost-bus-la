{#- The date index drawn by draw k of replicate r in one window x day-type stratum of n dates
    (ADR-027). The outer hash matters: DuckDB's multi-argument hash XORs its last argument in
    without a final mix, so hash(seed, ..., k) % n repeats one pattern across replicates when n
    is a power of two (measured: every replicate drew exactly 11 distinct dates of 16). Hashing
    the hash scrambles it. tests/bootstrap_draw_is_random.sql checks this for many n. -#}
{% macro bootstrap_draw(time_window, stratum, replicate, draw, n) -%}
    (hash(hash({{ var('bootstrap_seed') }}, {{ time_window }}, {{ stratum }}, {{ replicate }}, {{ draw }})) % {{ n }})
{%- endmacro %}
