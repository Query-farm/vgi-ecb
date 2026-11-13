SELECT period, value, value_text, unit
FROM ecb.main.observations('EXR', 'D.USD.EUR.SP00.A',
  start_period := '2024-01-02', end_period := '2024-01-05')
ORDER BY period;
