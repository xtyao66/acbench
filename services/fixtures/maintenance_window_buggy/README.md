# maintenance_window_buggy

Local maintenance scheduling fixture for ACBench.

Seeded defect:

- windows that cross midnight are treated like same-day ranges, so after-midnight times
  are evaluated incorrectly
