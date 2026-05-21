# THE3 - Manuel Test Checklist

`board_test.py` serial + timing'i otomatik kontrol eder. Asagidakiler
fiziksel mudahale (pot, RB6, goz) ister; simulator UI ile yapilir:

    python evCabinetSimulator.py --port /dev/ttyUSB0

## ADC & Thermal (board_test.py kapsamiyor - pot gerek)
- [ ] Pot dusuk (<700)  -> STS `m=N`
- [ ] Pot orta-ust (700-899) -> STS `m=D`
- [ ] Pot tepe (>=900) -> STS `m=H`
- [ ] Sinir: pot 699 -> N, 700 -> D
- [ ] `$LIM24#` + pot N -> `ee=24` ; pot D -> `ee=08` ; pot H -> `ee=00`
- [ ] Pot H'den N'e geri -> `ee=24` (yeniden LIM istemeden)
- [ ] STS `xxxx` pot ile ~500 ms icinde guncelleniyor

## Display & RB6 (goz + buton)
- [ ] GO oncesi 7-seg tamamen kapali
- [ ] Page 0: 4 haneli ADRES, leading zero (orn. 0480)
- [ ] Page 0 ADRES pot cevirince degisiyor
- [ ] RB6 birak -> Page 1 (ee + bos hane + c mask)
- [ ] RB6 basili tut -> sayfa DEGISMEZ
- [ ] RB6 tekrar birak -> Page 0
- [ ] END sonrasi 7-seg soner
- [ ] Flicker / ghosting yok

## Timing (kesin olcum)
- [ ] `python evCabinetSimulator.py --log-only sample_scenario.json --port /dev/ttyUSB0`
- [ ] Cikti: `avg_interval_ms` ~ 100
- [ ] Cikti: `worst_miss_ms` < 5
