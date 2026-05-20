# Person C Display/RB6 - Kısa Entegrasyon Notu

Bu not sadece `display.c` / `display.h` dosyamın diğer kişilere nasıl bağlanacağını söyler.

---

## A Kişisine

### Kullanacağı dosyalar

- `display.c`
- `display.h`

Ana dosyaya eklenecek:

```c
#include "display.h"
```

---

### Tanımlaması gereken global değişkenler

```c
volatile uint8_t display_page = 0;
volatile uint8_t rb6_release_flag = 0;
```

- `display_page`: 0 ise ADC sayfası, 1 ise `ee _ mask` sayfası.
- `rb6_release_flag`: RB6 bırakılınca 1 yapılır, tick içinde işlenir.

---

### Ortak header’da bulunması gereken enum

```c
typedef enum {
    ST_WAITING,
    ST_ACTIVE,
    ST_END
} CabState;
```

- `display.c` içinde kullanılan state isimleri bunlarla aynı olmalı.
- Finalde bu enum tek yerde durmalı.

---

### Main init içinde çağıracağı fonksiyonlar

```c
display_init();
timer1_display_init();
rb6_ioc_init();
```

- `display_init()`: PORTJ/PORTH display pinlerini ayarlar.
- `timer1_display_init()`: Timer1’i display multiplex için başlatır.
- `rb6_ioc_init()`: RB6 interrupt-on-change ayarını yapar.

---

### Ana ISR içine ekleyeceği handlerlar

```c
if (PIR1bits.TMR1IF) {
    display_timer1_handler();
}

if (INTCONbits.RBIF) {
    rb6_ioc_handler();
}
```

- `display_timer1_handler()`: Timer1 geldikçe 7-segment digitlerini sırayla sürer.
- `rb6_ioc_handler()`: RB6 release edge yakalar ve `rb6_release_flag = 1` yapar.

---

### 100 ms tick içinde çağıracağı fonksiyonlar

```c
display_process_button();
display_update_buffer();
```

- `display_process_button()`: RB6 flag varsa display page değiştirir.
- `display_update_buffer()`: Aktif page’e göre display buffer’ını günceller.

---

### GO / END içinde yapacağı şeyler

`$GO#` kabul edilince:

```c
display_page = 0;
```

- Display başlangıçta Page 0 olmalı.

`$END#` kabul edilince:

```c
display_blank();
```

- END sonrası display hemen kapanmalı.

---

### Dikkat

- Timer1 başka iş için kullanılmamalı.
- Final projede sadece bir tane gerçek `__interrupt()` olmalı.
- Benim dosyadaki handlerlar ana ISR içinden çağrılmalı.

---

## B Kişisine

### Benim kullandığım değişkenler

```c
extern volatile uint16_t adc_last;
```

- Page 0’da gösterilecek ADC değeri.
- B kişisi ADC interrupt sonucunda bunu güncel tutmalı.
- Aralık: `0 - 1023`.

---

```c
extern volatile uint8_t connected_mask;
```

- Page 1’de sağdaki digit olarak gösterilir.
- A/state tarafı port bağlantılarına göre bunu güncel tutmalı.
- Aralık: `0 - 7`.

---

### Benim çağırdığım fonksiyon

```c
extern uint8_t limit_effective(void);
```

- Page 1’de gösterilecek `ee` değerini verir.
- B kişisi bu fonksiyonu sağlamalı.

Beklenen mantık:

```c
ee = min(requested_limit, thermal_cap);
```

Beklenen dönüş değerleri:

```text
0, 8, 16, 24
```

---

### Thermal cap değerleri

B kişisinin thermal hesaplaması şu değerlere uymalı:

```text
NORMAL   -> thermal_cap = 24
DERATED  -> thermal_cap = 8
OVERHEAT -> thermal_cap = 0
```

---

### Dikkat

- `limit_effective()` kısa olmalı.
- İçinde UART, string formatting veya uzun işlem yapılmamalı.
- Display tarafı `limit_effective()` sonucunu direkt 2 digit olarak gösterir.
- Eğer `limit_effective()` yanlış değer döndürürse Page 1 yanlış görünür.

---

## Person C’nin Sağladığı Fonksiyonlar

```c
void display_init(void);
void display_blank(void);
void display_update_buffer(void);
void display_process_button(void);

void timer1_display_init(void);
void rb6_ioc_init(void);

void display_timer1_handler(void);
void rb6_ioc_handler(void);
```

---

## Kullanılan Kaynaklar

```text
PORTJ0-PORTJ6 : 7-segment segments
PORTH0-PORTH3 : digit select
RB6            : display page button
Timer1         : display multiplex timer
```
