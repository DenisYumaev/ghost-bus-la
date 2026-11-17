-- Warning under var('match_rate_alert') per feed per day (pipeline spec, section 7): a sudden
-- drop usually means a new schedule version wasn't loaded.
{{ config(severity='warn') }}
{{ match_rate_below(var('match_rate_alert')) }}
