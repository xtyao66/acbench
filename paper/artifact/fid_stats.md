SCORING: fixed-gold rescoring from recorded measured_speedup + correctness; stored score columns ignored; recorded speedups are rounded to 3 decimals
FIXED GOLD: manifests/perf_real_validated.json
=== Raw unmatched OFF -> ON diagnostic (not manuscript F1; Wilson 95% CI) ===
  devstral          OFF  31% [26, 36] n=392 | ON  45% [40, 50] n=392 | lift +14pp
  gpt-oss-120b      OFF  50% [45, 55] n=392 | ON  89% [86, 92] n=388 | lift +39pp
  gpt-oss-20b       OFF  35% [31, 40] n=392 | ON  58% [53, 63] n=392 | lift +23pp
  llama-4-maverick  OFF  62% [57, 67] n=392 | ON  94% [91, 96] n=392 | lift +32pp
  qwen3-235b        OFF  26% [21, 30] n=392 | ON  81% [77, 85] n=392 | lift +56pp
  qwen3.5           OFF  61% [57, 66] n=392 | ON  99% [97,100] n=392 | lift +38pp
  v4-flash          OFF  65% [60, 69] n=392 | ON  98% [96, 99] n=392 | lift +33pp
  SIGN TEST across models: 7/7 positive  ->  exact one-sided p = 0.0078 (two-sided 0.0156)

=== Fixed-gold pooled unpaired means (descriptive) ===
  none             mean=0.250 n=168
  fresh prof_cpu   mean=0.238 n=166
  baseline profile mean=0.259 n=164

=== F3 fixed-gold arm-by-arm paired contrasts (B=100000) ===
  INFERENCE SCOPE: scenario-cluster uncertainty conditional on the measured model panel and decoding seed(s) ['0']; generation-seed variance is not estimated.
  MULTIPLICITY: 7 reported contrasts; raw 95% CIs are unadjusted. Bonferroni 99.29% individual intervals provide 95% familywise coverage across this family.
  directional vs none
     n=126 pairs (14 scenario clusters), non-tied=65 | mean +0.040 | unadjusted scenario-cluster 95% CI [-0.018, +0.098] | SD 0.324 | cluster-MDE(80%) ~0.083 | sign 36/65
     Bonferroni familywise interval (99.29% individual): [-0.039, +0.119]
  numbers vs none
     n=125 pairs (14 scenario clusters), non-tied=67 | mean +0.023 | unadjusted scenario-cluster 95% CI [-0.043, +0.091] | SD 0.362 | cluster-MDE(80%) ~0.096 | sign 36/67
     Bonferroni familywise interval (99.29% individual): [-0.068, +0.117]
  benchstat vs none
     n=125 pairs (14 scenario clusters), non-tied=63 | mean +0.060 | unadjusted scenario-cluster 95% CI [-0.001, +0.128] | SD 0.310 | cluster-MDE(80%) ~0.093 | sign 35/63
     Bonferroni familywise interval (99.29% individual): [-0.020, +0.155]
  prof_cpu vs none
     n=166 pairs (14 scenario clusters), non-tied=81 | mean -0.008 | unadjusted scenario-cluster 95% CI [-0.068, +0.059] | SD 0.373 | cluster-MDE(80%) ~0.091 | sign 41/81
     Bonferroni familywise interval (99.29% individual): [-0.087, +0.087]
  prof_line vs none
     n=164 pairs (14 scenario clusters), non-tied=83 | mean +0.024 | unadjusted scenario-cluster 95% CI [-0.041, +0.084] | SD 0.381 | cluster-MDE(80%) ~0.090 | sign 39/83
     Bonferroni familywise interval (99.29% individual): [-0.066, +0.106]
  base_prof vs none
     n=164 pairs (14 scenario clusters), non-tied=81 | mean +0.014 | unadjusted scenario-cluster 95% CI [-0.047, +0.071] | SD 0.387 | cluster-MDE(80%) ~0.085 | sign 38/81
     Bonferroni familywise interval (99.29% individual): [-0.071, +0.092]
  base_prof vs prof_cpu
     n=164 pairs (14 scenario clusters), non-tied=74 | mean +0.018 | unadjusted scenario-cluster 95% CI [-0.038, +0.073] | SD 0.348 | cluster-MDE(80%) ~0.079 | sign 35/74
     Bonferroni familywise interval (99.29% individual): [-0.057, +0.094]

=== F3 common seven-policy panel: n=125 cells, 9 models, 14 scenarios ===
  directional vs none
     n=125 pairs (14 scenario clusters), non-tied=65 | mean +0.040 | unadjusted scenario-cluster 95% CI [-0.018, +0.098] | SD 0.326 | cluster-MDE(80%) ~0.083 | sign 36/65
     Bonferroni familywise interval (99.29% individual): [-0.039, +0.120]
  numbers vs none
     n=125 pairs (14 scenario clusters), non-tied=67 | mean +0.023 | unadjusted scenario-cluster 95% CI [-0.044, +0.090] | SD 0.362 | cluster-MDE(80%) ~0.095 | sign 36/67
     Bonferroni familywise interval (99.29% individual): [-0.068, +0.116]
  benchstat vs none
     n=125 pairs (14 scenario clusters), non-tied=63 | mean +0.060 | unadjusted scenario-cluster 95% CI [-0.001, +0.129] | SD 0.310 | cluster-MDE(80%) ~0.093 | sign 35/63
     Bonferroni familywise interval (99.29% individual): [-0.020, +0.154]
  prof_cpu vs none
     n=125 pairs (14 scenario clusters), non-tied=65 | mean +0.036 | unadjusted scenario-cluster 95% CI [-0.034, +0.113] | SD 0.349 | cluster-MDE(80%) ~0.105 | sign 35/65
     Bonferroni familywise interval (99.29% individual): [-0.059, +0.146]
  prof_line vs none
     n=125 pairs (14 scenario clusters), non-tied=63 | mean +0.041 | unadjusted scenario-cluster 95% CI [-0.019, +0.104] | SD 0.336 | cluster-MDE(80%) ~0.088 | sign 31/63
     Bonferroni familywise interval (99.29% individual): [-0.039, +0.129]
  base_prof vs none
     n=125 pairs (14 scenario clusters), non-tied=60 | mean +0.039 | unadjusted scenario-cluster 95% CI [-0.020, +0.104] | SD 0.313 | cluster-MDE(80%) ~0.090 | sign 29/60
     Bonferroni familywise interval (99.29% individual): [-0.040, +0.130]
  base_prof vs prof_cpu
     n=125 pairs (14 scenario clusters), non-tied=56 | mean +0.003 | unadjusted scenario-cluster 95% CI [-0.041, +0.043] | SD 0.277 | cluster-MDE(80%) ~0.060 | sign 25/56
     Bonferroni familywise interval (99.29% individual): [-0.059, +0.057]

=== Descriptive max-over-five selector-bias diagnostic (NOT positive evidence) ===
  complete six-arm cells: n=125
  observed max(five faithful)-none: +0.188
  random-singleton five-vs-one opportunity baseline: +0.145
  observed minus opportunity baseline: +0.043
  No inferential CI is reported; this outcome-selected statistic is excluded from the contrast family.

=== Profile-exposure accounting in OFF fidelity cells ===
  Exposure event = correct measured candidate in a pre-final slot, so a later prompt can receive the payload.
  prof_cpu           exposure events 152/ 498 (30.5%) | arm-cells with exposure  89/166 (53.6%)
  baseline profile   exposure events 144/ 492 (29.3%) | arm-cells with exposure  87/164 (53.0%)
  faithful arms      exposure events 610/2118 (28.8%) | arm-cells with exposure 376/706 (53.3%)
