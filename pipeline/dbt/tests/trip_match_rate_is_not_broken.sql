-- Error under var('match_rate_error') (0.80) per feed per day (pipeline spec, section 10):
-- outcomes built on that few matches would misclassify most trips as unobserved.
{{ match_rate_below(var('match_rate_error')) }}
