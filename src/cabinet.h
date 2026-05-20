/*
 * cabinet.h - CENG336 THE3 ortak API sozlesmesi
 *
 * Bu dosya 3 modulun paylastigi global state ve fonksiyon imzalarini tanimlar.
 * Sahiplik:
 *   Uye A  -> parser, state machine, tick, EUSART, ACK/STS
 *   Uye B  -> ADC, thermal classifier, effective limit
 *   Uye C  -> 7-segment display, RB6 interrupt-on-change
 *
 * Degisiklikler PR + 3 onay ile yapilir.
 */
#ifndef CABINET_H
#define CABINET_H

#include <stdint.h>

/* Cabinet lifecycle durumu (S.4, S.5, S.46-S.51) */
typedef enum { ST_WAITING, ST_ACTIVE, ST_END } CabState;
extern volatile CabState cab_state;          /* sahip: A */

/* ---- ADC modulu (sahip: Uye B) ----
 * A bu degiskenleri sadece OKUR (STS frame'i kurarken).
 * thermal_process() A'nin tick handler'inda cagrilir.
 */
extern volatile uint16_t adc_last;           /* en son tamamlanan ADRES (0-1023) */
extern volatile char     thermal_band;       /* 'N','D','H' */
extern volatile uint8_t  thermal_cap;        /* 0, 8, 24 */
extern volatile uint8_t  requested_limit;    /* 0, 8, 16, 24 - $LIMxx# ile guncellenir */
extern volatile uint8_t  adc_done_flag;      /* ADC ISR set eder, tick tuketir */

/* ---- State (sahip: Uye A) ---- */
extern volatile uint8_t  connected_mask;     /* bit0..bit2 = port0..port2 */
extern volatile uint8_t  tick_flag;          /* Timer0 ISR set eder, main loop tuketir */

/* ---- Display modulu (sahip: Uye C) ---- */
extern volatile uint8_t  display_page;       /* 0 veya 1 */
extern volatile uint8_t  display_active;     /* 1 ise ekran calisir, 0 ise blank */

/* ---- Init fonksiyonlari ---- */
void eusart_init(void);          /* A */
void cabinet_tick_init(void);    /* A */
void adc_init(void);             /* B */
void adc_start_conversion(void); /* B */
void rb6_ioc_init(void);         /* C */
void display_init(void);         /* C */

/* ---- Logic ---- */
void    thermal_process(void);     /* B: tamamlanan ADC sonucunu banda cevirir */
uint8_t limit_effective(void);     /* B: min(requested_limit, thermal_cap) */
void    display_update_buffer(void); /* C: aktif sayfaya gore digit buffer doldurur */
void    display_blank(void);       /* C: ekrani sondurur */

#endif /* CABINET_H */
