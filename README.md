# CENG 336 THE3 — Three-Port EV Charging Cabinet

**Group Working Guide & Task Plan**

Son teslim: **23 Mayıs 2026, 23:55** (ODTUClass)
Hedef: Tüm rubric maddelerini geçen, board üzerinde sample scenario'yu sorunsuz çalıştıran firmware.

---

## 1. Repo Yapısı

```
the3/
├── README.md                 # bu dosya
├── names.txt                 # 3 üye: ID, ad, soyad, grup no
├── src/
│   ├── cabinet.h             # ortak state ve API contract
│   ├── the3.c                # main + ISR (template'den evrilir)
│   ├── pragmas.h             # verildi, dokunma
│   └── ...                   # gerekirse modül başına .c/.h
├── StudentPack/              # hand-out (referans, submit edilmez)
│   ├── evCabinetSimulator.py
│   ├── sample_scenario.json
│   └── evcabsim/
└── the3.X/                   # MPLAB X projesi
```

**Submit edilen:** `the3.zip` içinde `src/`, `the3.X/`, `names.txt`. StudentPack zaten TA'da var.

---

## 2. Roller

Bağımlılıkları minimize etmek için 3 paralel modül + 1 entegrasyon sahibi. Rolleri **deneyim seviyesine göre** atayın; PIC/C/interrupt'ta en güvenilir kişi A olur.

### Üye A — Parser + State Machine + Tick + Integration Owner
**Toplam rubric ağırlığı: ~45 puan** (Serial Protocol 30 + Timing 15)

Sorumlulukları:
- EUSART register init (`eusart_init`): 115200 8N1 on RC6/RC7, RX1IE aktif.
- 100 ms cabinet tick (Timer0 önerilir; Timer1 display'e ayrılmış).
- Frame parser: `$...#` framing, malformed/idempotent silent discard.
- State machine: `WAITING → ACTIVE → END`. Lifecycle vs in-run komut ayrımı.
- ACK queue (max 1 pending), STS builder (`sprintf` ile `$STS%c%04u%u%02u#`).
- Algorithm 1'in birebir uygulanması (within-tick order).
- EUSART OERR/FERR recovery (S.65).
- Cross-module integration: `cabinet.h` API'sini sahiplenir.

Done kriterleri (board üzerinde, simulator karşısında):
- `$GO#` → `$ACK00#`, sonra periyodik STS.
- `$LIM24#` → `$ACK03#`, sonraki STS'lerde ee güncellenmiş.
- Malformed (`$CON5#`, `$LIM99#`, `$XXX#`) sessizce drop.
- `$END#` sonrası TX kesilir.
- `--log-only` modda `avg_interval_ms ≈ 100`, `worst_miss_ms < 5`.

### Üye B — ADC + Thermal + Effective Limit
**Toplam rubric ağırlığı: ~40 puan** (ADC & Thermal 25 + Current Limit 15)

Sorumlulukları:
- `adc_init`: AN12 (RH4), 10-bit right-adjusted, Fosc/64 clock, ADIE aktif.
- `adc_start_conversion`: tetik fonksiyonu.
- ADC ISR branch (polling YASAK — S.63, 5 puan).
- 500 ms cadence: A'nın tick handler'ında 5 sayaç olarak.
- Cold-start ADC trigger (S.15, S.56) — A'nın `$GO#` handler'ından çağrılır.
- Thermal classifier: `<700 → N (cap 24)`, `700–899 → D (cap 08)`, `≥900 → H (cap 00)`.
- `requested_limit` state (init 0, sadece accepted `$LIMxx#`).
- `limit_effective() = min(requested_limit, thermal_cap)` — STS builder bunu çağırır.

Done kriterleri:
- Pot mid (~500) + `$LIM24#` → ee=24.
- Pot D bandına (~750) → 1 tick içinde m=D, ee=08.
- Pot H bandına (~950) → m=H, ee=00.
- Pot N'e geri → ee=24 (yeniden `$LIM24#` istemiyor).
- `$LIM00#` → her bandda ee=00.

### Üye C — Display + RB6 + QA Lead
**Toplam rubric ağırlığı: ~15 puan** (Display & RB6)
**Ek sorumluluk: takımın QA'ı.**

Sorumlulukları:
- `display_init`: TRISJ = 0x80, TRISH &= ~0x0F, latch'leri sıfırla.
- Timer1 ISR ile 4-digit multiplex (~250 Hz refresh, flicker yok).
- Anti-ghost scan order: PORTH digit-select temizle → LATJ segment yaz → PORTH digit-select set.
- Segment table (0-9 + blank), PORTJ[0:6] = a..g.
- Page 0: ADRES 4-digit decimal (leading zero — `0480`).
- Page 1: ee (2 digit) + blank + connected_mask.
- `rb6_ioc_init`: TRISB6=1, RBIE=1, IOCB6 enable.
- RB6 release edge detection (rising 0→1).
- 20 ms SW debouncing (tick sayacı ile).
- WAITING + END → display blank (digit-select hiçbir bit set etmez).

Done kriterleri:
- `$GO#` öncesi ekran tamamen kapalı.
- Page 0'da ADRES anlık değişiyor, pot çevirince hemen görünür.
- RB6 release → page 1. Basılı tutmak sayfa değiştirmez.
- Tekrar release → page 0.
- `$END#` → ekran tekrar sönüyor.
- Hiç flicker yok, ghosting yok.

QA görevi (her gün 22:00'da):
- `python evCabinetSimulator.py sample_scenario.json` çalıştır.
- Wire trace'i spec'e karşı manuel doğrula.
- Rubric checklist'inden geçilebilenleri işaretle.
- Açık bug listesi tut, GitHub Issues'a yaz.

---

## 3. Ortak API Contract (`cabinet.h`)

Bu dosyayı A bu gece açıp commit eder. **Değişiklikler PR + 3 onay ile.**

```c
// cabinet.h
#ifndef CABINET_H
#define CABINET_H
#include <stdint.h>

typedef enum { ST_WAITING, ST_ACTIVE, ST_END } CabState;
extern volatile CabState cab_state;

// ADC module (Üye B)
extern volatile uint16_t adc_last;
extern volatile char     thermal_band;    // 'N','D','H'
extern volatile uint8_t  thermal_cap;     // 0, 8, 24
extern volatile uint8_t  requested_limit; // 0, 8, 16, 24
extern volatile uint8_t  adc_done_flag;

// State (Üye A sahibi)
extern volatile uint8_t  connected_mask;  // bit0..bit2
extern volatile uint8_t  tick_flag;

// Display (Üye C)
extern volatile uint8_t  display_page;    // 0 or 1
extern volatile uint8_t  display_active;

// Inits
void eusart_init(void);
void cabinet_tick_init(void);
void adc_init(void);
void adc_start_conversion(void);
void rb6_ioc_init(void);
void display_init(void);

// Logic
void thermal_process(void);    // tick'te çağrılır
uint8_t limit_effective(void); // min(requested, cap)
void display_update_buffer(void);
void display_blank(void);

#endif
```

---

## 4. Pack'in Sağladıkları ve Tuzaklar

### Hediyeler (`the3_template.c`)
- Ring buffer (`rx_ring`, `tx_ring`) + push/pop fonksiyonları **hazır**.
- `uart_read_byte`, `uart_write_byte` API'leri **çalışıyor**.
- ISR'da RX/TX byte enqueue/dequeue **zaten yazılmış**.
- Tüm peripheral init'lerin imzaları stub olarak yerleştirilmiş.

### Tuzaklar (bunları bilmek 5–10 puan kurtarır)
1. **Tek seviyeli ISR.** Template `__interrupt() isr(void)` kullanıyor — high/low priority **bölmeyin**. Display mux çok sık fire eder; bölerseniz RX byte kaybedersiniz.
2. **Simülatör frame interval'lerini ölçüyor** (`stats.py`). 100 ms tick'inizdeki jitter görünür ve değerlendirilebilir. Tick timer'ını display mux ile karıştırmayın.
3. **STS decoder katı.** Body **tam 8 byte** olmalı. `sprintf` format string'i: `"$STS%c%04u%u%02u#"` — `xxxx` ve `ee` leading zero'lu.
4. **VALID_LIM_AMPS = (0, 8, 16, 24).** STS'deki ee bu set'in dışına çıkarsa decode error → puan kaybı. `min()` doğru kuruluyorsa zaten güvendesiniz.
5. **`probe_widgets.py` var.** TA muhtemelen manuel probe testleri de yapacak — sadece scenario.json'a güvenmeyin.

---

## 5. Donanım Hesapları (Hızlı Referans)

### EUSART (115200 baud @ 40 MHz)
- `BRG16 = 1`, `BRGH = 1`
- `SPBRG = (40e6 / (4 × 115200)) - 1 ≈ 85`
- `SYNC = 0`, `SPEN = 1`, `CREN = 1`, `TXEN = 1`
- `TRISC6 = 1`, `TRISC7 = 1` (datasheet'in dediği gibi; EUSART pin'leri yine de input olarak set edilir)

### Timer0 — 100 ms tick
- 16-bit mode, Fosc/4 = 10 MHz instruction clock
- Prescaler 1:64 → 156.25 kHz tick
- 15625 count = 100 ms
- Preload = `65536 - 15625 = 49911 = 0xC2F7`

### Timer1 — Display mux (~2 ms / digit, 250 Hz refresh)
- Prescaler 1:8 → 1.25 MHz tick
- 2500 count = 2 ms
- Preload = `65536 - 2500 = 63036`

### ADC — AN12, 10-bit, right-adjusted
- `ADCON0`: CHS3:0 = 1100 (AN12), ADON = 1
- `ADCON1`: PCFG ile AN0–AN12 analog
- `ADCON2`: ADFM = 1, ACQT = uygun, ADCS = Fosc/64 (40 MHz için)
- `TRISH4 = 1`
- `ADIE = 1`, polling YASAK

### Digit Mapping (Spec'e dikkat)
| `cur_digit` | Soldaki konum | LATH biti |
|---|---|---|
| 3 | x3 (leftmost) | LATH0 |
| 2 | x2 | LATH1 |
| 1 | x1 | LATH2 |
| 0 | x0 (rightmost) | LATH3 |

Yani spec der ki: `PORTH0 → digit3`, `PORTH3 → digit0`. Ters mantık, **bug magneti**. Tablo yap.

---

## 6. Zaman Planı Template


### Bu gece (19 Mayıs, 1.5 saat) — Setup Sprint
**Hep birlikte Discord/Zoom:**
- [ ] GitHub repo açılır, StudentPack commit edilir.
- [ ] `cabinet.h` (bu README'deki içerikle) yazılır, A commit eder.
- [ ] Rolleri ata (A/B/C).
- [ ] MPLAB X projesi kurulur, `the3_template.c` + `pragmas.h` derleniyor mu doğrula.
- [ ] Boş proje board'a yüklenip LED toggle ettirilir (toolchain sanity check).

### Gün 1 (20 Mayıs) — Modül Bring-up
- A: `eusart_init` + UART echo loopback (gelen byte'ı geri yolla).
- B: `adc_init` + `adc_start_conversion`. Pot çevir, MSB değerini LED ile gör.
- C: `display_init` + Timer1 mux. Sabit "1234" göster, RB6 → "5678".
- **22:00 stand-up + merge.** Hepsi `main`'de derlenmeli.

### Gün 2 (21 Mayıs) — Protocol & State
- A: Parser tam, state machine, tick generator, STS builder, ACK queue.
- B: Thermal classifier + ee. A'nın STS builder'ına feed.
- C: Page 0/Page 1 buffer fill + WAITING/END blank.
- **22:00:** Sample scenario'yu baştan sona çalıştır. İlk bug listesi.

### Gün 3 (22 Mayıs) — Integration & Bug Hunt
Sample scenario %100 geçmeli. Edge case testleri:
- Idempotent komutlar (`$CON0#` zaten connected port'a).
- Malformed: `$CON5#`, `$LIM99#`, `$XXX#`, eksik byte (`$LIM2#`).
- Threshold tam sınırda: ADC = 699, 700, 899, 900.
- `$END#` sonrası komut → cabinet sessiz.
- Pot D ⇄ N geçişi → ee anlık değişmeli.
- C, rubric checklist'i madde madde geçer.

### Gün 4 (23 Mayıs) — Polish & Submit
- 09:00–18:00: Son bug'lar.
- 18:00–20:00: Code cleanup, comment'ler (S.69), `names.txt`.
- **20:00: HARD FREEZE.** Yeni feature yok.
- 22:00: Final test, `the3.zip` hazırla.
- 22:30: ODTUClass submit. **Son 1 saate bırakma.**

---

## 7. Rubric Checklist (Teslim öncesi)

### Serial Protocol (30 pts)
- [ ] `$...#` frame algılama, dışındaki byte'lar ignore (4).
- [ ] Malformed/wrong-length/invalid payload silently discard (3).
- [ ] `$GO#` sadece WAITING'de, `$END#` sadece ACTIVE'de accept (6).
- [ ] `$CONp#`/`$DISp#` doğru port bit'i set/clear (6).
- [ ] `$LIMxx#` sadece 00/08/16/24 için kabul (4).
- [ ] Tick başına 1 frame TX (ACK öncelikli, yoksa STS) (7).

### ADC & Thermal (25 pts)
- [ ] ADC AN12, doğru clock, 10-bit right-adjusted (5).
- [ ] 500 ms'de bir conversion (5).
- [ ] ADC interrupt (polling YASAK) (5).
- [ ] Threshold: <700 / 700–899 / ≥900 (5).
- [ ] `xxxx` ve `m` doğru raporlanıyor (5).

### Current Limit (15 pts)
- [ ] Init `requested_limit = 00` (5).
- [ ] Cap doğru: 24/08/00 (4).
- [ ] `ee = min(...)` her tick (4).
- [ ] ee cabinet-wide, split yok (2).

### Timing (15 pts)
- [ ] 100 ms tick stabil (5).
- [ ] In-run komutlar next tick'te apply (4).
- [ ] Tick başına 1 frame TX (3).
- [ ] `$END#` sonrası TX yok, display blank (3).

### Display & RB6 (15 pts)
- [ ] Timer1 mux, 4 digit, flicker yok (5).
- [ ] WAITING + END blank (2).
- [ ] Page 0: 4-digit ADRES, leading zeros (3).
- [ ] Page 1: ee + blank + c mask (3).
- [ ] RB6 sadece release edge'de toggle (2).

### Submission Sanity
- [ ] `names.txt` (3 üye: ID, ad, soyad, grup no).
- [ ] Tüm .c/.h dosyaları, MPLAB X proje dosyaları.
- [ ] `the3.zip` adı tam doğru (büyük/küçük harf).
- [ ] Temiz makinede zip extract → derle → board'da çalış.

---



## 9. Submission Komutu

```bash
# repo kökünde
zip -r the3.zip src/ the3.X/ names.txt -x "*.git*" "*StudentPack*"
```

`names.txt` formatı:
```
Group: <numara>
4276844 Tahsin Elmas
12346 Veli Demir
12347 Ayşe Kaya
```

---