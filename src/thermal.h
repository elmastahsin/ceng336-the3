/*
 * thermal.h  —  Member B public interface
 *               ADC, thermal classifier, effective current limit.
 *
 * Variable names in this header are agreed with Member C's display code:
 *   adc_last       — the name Member C uses for the ADC display value
 *   connected_mask — defined/written by Member A, read by Member C
 *   limit_effective() — function Member C calls for Page 1 ee digits
 *
 * Include in: main.c (Member A), display.c (Member C).
 *
 * INTEGRATION CHECKLIST FOR MEMBER A
 * ===================================
 * 1. #include "thermal.h"
 * 2. Call adc_init() in main() BEFORE enabling GIE/PEIE.
 * 3. On $GO# acceptance:
 *        thermal_reset();          // zeros requested_limit, mode=N, cap=24
 *        adc_start_conversion();   // cold-start (S.15 / S.56)
 * 4. On $LIMxx# acceptance (xx is the validated amps value 0/8/16/24):
 *        requested_limit = xx;
 * 5. Inside the 100 ms tick handler, at Algorithm-1 step 6,
 *    ONLY while phase == ACTIVE:
 *        thermal_update();         // consume latest ADC result if ready
 *        adc_tick();               // advance 500 ms cadence counter
 * 6. In the STS frame builder:
 *        thermal_mode              <- m    field ('N'/'D'/'H')
 *        adc_last                  <- xxxx field (uint16_t, 0-1023)
 *        connected_mask            <- c    field (uint8_t,  0-7)
 *        limit_effective()         <- ee   field (uint8_t,  0/8/16/24)
 *    Read adc_last under a brief ADIE mask for atomicity (see below).
 * 7. Paste the ADC ISR BRANCH (bottom of this file) into isr().
 * 8. Define and maintain connected_mask (write it when ports change).
 *
 * INTEGRATION CHECKLIST FOR MEMBER C
 * ===================================
 * 1. #include "thermal.h"
 * 2. Page 0 ADC value : adc_last          (read under ADIE mask, see note)
 * 3. Page 1 ee value  : limit_effective() (returns 0, 8, 16, or 24)
 * 4. Page 1 port mask : connected_mask    (0-7, written by Member A)
 *
 * ATOMICITY NOTE FOR adc_last
 * ===========================
 * adc_last is uint16_t on an 8-bit CPU. Reading it outside the ISR
 * requires a brief ADIE mask to prevent a torn read:
 *
 *     PIE1bits.ADIE = 0;
 *     uint16_t snap = adc_last;
 *     PIE1bits.ADIE = 1;
 *
 * The mask window is two instructions (~200 ns). Use this pattern
 * wherever adc_last is read in main-context code.
 */

#ifndef THERMAL_H
#define THERMAL_H

#include <stdint.h>

/* -----------------------------------------------------------------------
 * Shared volatile state
 * --------------------------------------------------------------------- */

/*
 * adc_last — latest completed 10-bit raw ADRES value (0-1023).
 *
 * Written by the ADC ISR immediately when a conversion finishes.
 * This is the value Member C displays on Page 0 and Member A puts
 * in the xxxx field of every STS frame.
 *
 * READ RULE: never read this directly in main-context code without
 * masking ADIE first (see ATOMICITY NOTE above).
 */
extern volatile uint16_t adc_last;

/*
 * adc_ready — set 1 by the ADC ISR each time adc_last is updated.
 * Cleared by thermal_update() after the value has been classified.
 * Do not write this outside thermal.c.
 */
extern volatile uint8_t adc_ready;

/*
 * thermal_mode — STS wire character for the current thermal band.
 *   'N'  NORMAL   (cap 24 A)
 *   'D'  DERATED  (cap  8 A)
 *   'H'  OVERHEAT (cap  0 A)
 * Initialised 'N' (provisional, S.55). Updated by thermal_update().
 * Read by Member A's STS builder (m field).
 */
extern volatile char thermal_mode;

/*
 * thermal_cap — band cap in amperes: 24, 8, or 0.
 * Private to thermal.c. Do not access outside this module;
 * use limit_effective() instead.
 */
extern volatile uint8_t thermal_cap;

/*
 * requested_limit — cabinet-wide limit from the last accepted $LIMxx#.
 * Initialised 0 (S.53). Written by Member A's parser on $LIMxx# accept.
 * Read by limit_effective().
 */
extern volatile uint8_t requested_limit;

/*
 * connected_mask — 3-bit port connection mask (bit i set = port i connected).
 * Defined and written by Member A when ports connect or disconnect.
 * Read by Member A's STS builder (c field) and Member C's Page 1 display.
 * Range 0-7.
 */
extern volatile uint8_t connected_mask;

/* -----------------------------------------------------------------------
 * Functions provided by thermal.c
 * --------------------------------------------------------------------- */

/*
 * adc_init()
 *   Configure AN12/RH4: 10-bit right-adjusted, Fosc/64 clock, ADIE=1.
 *   Call once in main() before enabling GIE/PEIE.
 */
void adc_init(void);

/*
 * adc_start_conversion()
 *   Set GO/DONE to start one conversion. Result arrives via ADC ISR.
 *   Member A calls this:
 *     (a) once immediately after $GO# for the cold-start (S.15/S.56)
 *     (b) automatically every 500 ms via adc_tick()
 */
void adc_start_conversion(void);

/*
 * adc_tick()
 *   Advance the internal 500 ms cadence counter.
 *   Call exactly once per 100 ms tick, AFTER thermal_update(),
 *   and ONLY while phase == ACTIVE (S.14).
 *   Calls adc_start_conversion() automatically every 5 ticks (=500 ms).
 */
void adc_tick(void);

/*
 * thermal_update()
 *   If adc_ready == 1, atomically read adc_last, classify it into a
 *   thermal band, and update thermal_mode and thermal_cap.
 *   No-op when adc_ready == 0 (band persists, S.17).
 *   Member A calls this at Algorithm-1 tick step 6, ONLY while ACTIVE.
 */
void thermal_update(void);

/*
 * limit_effective()
 *   Returns ee = min(requested_limit, thermal_cap).
 *   Possible return values: 0, 8, 16, 24.
 *   No side effects; no UART, no formatting, no long computation.
 *   Called by Member A's STS builder (ee field).
 *   Called by Member C's display driver (Page 1 ee digits).
 */
uint8_t limit_effective(void);

/*
 * thermal_reset()
 *   Restore all Member-B state to $GO# initial conditions (S.53/S.55/S.57):
 *     requested_limit = 0   (ee starts at 00)
 *     thermal_mode    = 'N' (provisional NORMAL)
 *     thermal_cap     = 24
 *     adc_ready       = 0   (discard any pre-$GO# result)
 *     internal 500 ms counter = 0
 *   Member A calls this from the $GO# handler BEFORE adc_start_conversion().
 */
void thermal_reset(void);

/* -----------------------------------------------------------------------
 * ADC ISR BRANCH
 * Copy-paste verbatim into __interrupt() isr() in main.c,
 * AFTER the EUSART branches, BEFORE the timer and RB6 branches.
 * -----------------------------------------------------------------------
 *
 *     if (PIE1bits.ADIE && PIR1bits.ADIF) {
 *         // Right-adjusted result: ADRESL = bits[7:0], ADRESH[1:0] = bits[9:8].
 *         // Read ADRESL first: PIC18F8722 hardware freezes ADRESH until
 *         // ADRESL is read (DS §22.3).
 *         uint8_t lo  = ADRESL;
 *         uint8_t hi  = ADRESH & 0x03u;
 *         adc_last    = (uint16_t)lo | ((uint16_t)hi << 8u);
 *         adc_ready   = 1u;
 *         PIR1bits.ADIF = 0;
 *     }
 *
 * --------------------------------------------------------------------- */

#endif /* THERMAL_H */
