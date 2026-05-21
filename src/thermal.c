/*
 * thermal.c  —  Member B implementation
 *
 * Variable names are aligned with Member C's display code contract:
 *   adc_last  (was adc_result) — the shared ADC display variable
 *
 * Spec rules covered:
 *   S.12  10-bit right-adjusted ADC output
 *   S.13  ADC completion via interrupt — NO polling of GO/DONE
 *   S.14  One conversion every 500 ms while ACTIVE
 *   S.15  Trigger immediately after $GO# (cold-start)
 *   S.16  Update thermal band and cap on every completed conversion
 *   S.17  Same thresholds in both transition directions (no hysteresis)
 *   S.18  requested_limit init 00; updated only by accepted $LIMxx#
 *   S.19  thermal_cap derived from current band
 *   S.20  ee = min(requested_limit, thermal_cap) computed before each STS
 *   S.50  ADC result affects mode/cap at first tick that sees it
 *   S.53  requested_limit starts 00 at $GO#
 *   S.55  Provisional NORMAL mode until first ADC result
 *   S.56  Cold-start conversion immediately after $GO#
 *   S.57  ee = 00 until $LIMxx# raises requested_limit
 *
 * Rubric rows owned by Member B:
 *   ADC & Thermal (25 pts): configure ADC / 500 ms cadence /
 *                            interrupt completion / thresholds / xxxx+m
 *   Current Limit (15 pts): requested_limit init & update /
 *                            thermal_cap / ee=min / cabinet-wide ee
 */

#include <xc.h>
#include <stdint.h>
#include "pragmas.h"   /* PIC18F8722 at 40 MHz; defines _XTAL_FREQ       */
#include "thermal.h"

/* =======================================================================
 * Shared volatile globals
 * Declared extern in thermal.h; defined (allocated) here.
 * ===================================================================== */

/*
 * adc_last: latest completed 10-bit ADRES value.
 * Written by the ADC ISR. Read by thermal_update(), STS builder (xxxx),
 * and Member C's Page 0 display (under ADIE mask for atomicity).
 * Initialised 0; first real value arrives within ~33 µs of the
 * cold-start conversion triggered at $GO# time.
 */
volatile uint16_t adc_last      = 0u;

/*
 * adc_ready: flag set by ISR when adc_last holds a fresh value.
 * Cleared by thermal_update() after classification.
 */
volatile uint8_t  adc_ready     = 0u;

/*
 * thermal_mode: current band as the STS wire letter.
 * 'N' = NORMAL (cap 24), 'D' = DERATED (cap 8), 'H' = OVERHEAT (cap 0).
 * Provisional 'N' until first ADC result (S.55).
 */
volatile char     thermal_mode  = 'N';

/*
 * thermal_cap: band current cap in amperes (24, 8, or 0).
 * Private: only limit_effective() should read this outside thermal.c.
 */
volatile uint8_t  thermal_cap   = 24u;

/*
 * requested_limit: cabinet-wide limit set by last accepted $LIMxx#.
 * Written by Member A's parser. Initialised 0 (S.53).
 */
volatile uint8_t  requested_limit = 0u;

/*
 * connected_mask: 3-bit port connection mask (bit i = port i connected).
 * Defined here so it is allocated in one translation unit.
 * Written by Member A when CON/DIS commands change port state.
 * Read by Member A's STS builder (c field) and Member C's Page 1 display.
 */
volatile uint8_t  connected_mask  = 0u;

/* -----------------------------------------------------------------------
 * Internal cadence counter — not exposed in thermal.h
 * --------------------------------------------------------------------- */
static uint8_t adc_tick_count = 0u;

/* =======================================================================
 * adc_init()
 *
 * Configures the PIC18F8722 ADC for AN12 on RH4 at Fosc = 40 MHz.
 *
 * Register-by-register explanation:
 *
 * TRISH4 = 1
 *   Make RH4 a digital input (high-Z) so the ADC can drive it.
 *
 * ANCON1 &= ~0x10u
 *   ANCON1 bit 4 is ANSEL12. Setting it to 0 enables the analog function
 *   on AN12 (DS §22.1, Table 22-1: 0 = analog, 1 = digital).
 *   Named-bit alternative: ANCON1bits.ANSEL12 = 0;
 *
 * ADCON0 = 0b00110001
 *   [7:6] unimplemented    = 00
 *   [5:2] CHS3:CHS0        = 1100  → channel 12 (AN12)
 *   [1]   GO/DONE           = 0    → do not start conversion yet
 *   [0]   ADON              = 1    → ADC module on
 *
 * ADCON1 = 0x00
 *   [5:4] VCFG1:VCFG0      = 00   → Vref- = AVss, Vref+ = AVdd
 *
 * ADCON2 = 0b10111110
 *   [7]   ADFM              = 1    → right-justified (S.12)
 *                                    ADRESL[7:0] = result[7:0]
 *                                    ADRESH[1:0] = result[9:8]
 *   [6]   unimplemented     = 0
 *   [5:3] ACQT2:ACQT0       = 111 → 20 TAD acquisition time
 *                                    TAD = 1.6 µs → 20×1.6 = 32 µs
 *                                    >> 2.4 µs minimum for pot source
 *   [2:0] ADCS2:ADCS0       = 110 → Fosc/64
 *                                    TAD = 64/40 MHz = 1.6 µs
 *                                    > 0.7 µs minimum (DS §22.4)
 *
 * Interrupt setup:
 *   Clear ADIF before enabling ADIE to avoid a spurious interrupt.
 *   ADIP = 0: low-priority; adjust if your ISR uses high/low split.
 * ===================================================================== */
void adc_init(void)
{
    TRISHbits.TRISH4 = 1;       /* RH4: high-Z input                    */

    /* Channel AN12, no conversion, module on */
    ADCON0 = 0b00110001;        /* CHS=1100(AN12), GO=0, ADON=1         */

    /* PIC18F8722: ADCON1 PCFG3:0 = 0000 -> AN0..AN12 hepsi analog
     * (AN12 analog secimi burada yapilir; ANCON ailesi bu chip'te yok).
     * VCFG1:0 = 00 -> Vref- = AVss, Vref+ = AVdd. */
    ADCON1 = 0x00u;

    /* Right-justified, 20 TAD acquisition, Fosc/64 clock */
    ADCON2 = 0b10111110;        /* ADFM=1, ACQT=111, ADCS=110           */

    PIR1bits.ADIF = 0;          /* clear stale flag before enabling     */
    PIE1bits.ADIE = 1;          /* ADC-completion interrupt enable      */
    IPR1bits.ADIP = 0;          /* low-priority                         */
}

/* =======================================================================
 * adc_start_conversion()
 *
 * Triggers one ADC conversion by setting GO/DONE. The hardware clears
 * GO when conversion completes and asserts PIR1.ADIF, firing the ISR.
 *
 * Never poll GO/DONE for completion — that violates S.13 (5 pts lost).
 * ===================================================================== */
void adc_start_conversion(void)
{
    ADCON0bits.GO = 1;
}

/* =======================================================================
 * adc_tick()
 *
 * Advances the internal 500 ms cadence counter (S.14 / S.62).
 * Must be called exactly once per 100 ms tick, AFTER thermal_update(),
 * and ONLY while cabinet phase == ACTIVE.
 *
 * Why ACTIVE only: S.14 requires sampling only during a run. Calling
 * this in WAITING or END would fire spurious conversions and corrupt
 * the counter across phase boundaries.
 *
 * Why after thermal_update(): ensures the previous result is always
 * consumed before a new conversion is started.
 *
 * Counter reaches 5 every 500 ms → triggers one new conversion.
 * thermal_reset() zeroes the counter at $GO# time so the cadence
 * starts cleanly from the cold-start conversion.
 * ===================================================================== */
void adc_tick(void)
{
    adc_tick_count++;
    if (adc_tick_count >= 5u) {
        adc_tick_count = 0u;
        adc_start_conversion();     /* 500 ms periodic trigger          */
    }
}

/* =======================================================================
 * thermal_update()
 *
 * Called by Member A at Algorithm-1 tick step 6, ONLY while ACTIVE.
 *
 * If adc_ready == 0, returns immediately (band unchanged, S.17).
 * If adc_ready == 1, atomically reads adc_last under ADIE mask,
 * clears adc_ready, then classifies the raw value:
 *
 *   ADRES < 700       → NORMAL   ('N', cap = 24 A)   S.16 / Figure 5
 *   700 ≤ ADRES < 900 → DERATED  ('D', cap =  8 A)
 *   ADRES ≥ 900       → OVERHEAT ('H', cap =  0 A)
 *
 * Thresholds apply identically in both directions (no hysteresis, S.17).
 *
 * The ADIE mask makes the 16-bit adc_last read atomic: masking for
 * two instructions (~200 ns) prevents the ISR from updating adc_last
 * between the two 8-bit loads the compiler generates for a uint16_t.
 * Clearing adc_ready under the same mask ensures the ISR cannot
 * re-assert it before we commit to having read this result.
 * ===================================================================== */
void thermal_update(void)
{
    uint16_t raw;

    if (!adc_ready) {
        return;                     /* no new result; keep current band  */
    }

    /* Atomic read: mask ADC interrupt for two instructions             */
    PIE1bits.ADIE = 0;
    raw       = adc_last;
    adc_ready = 0u;
    PIE1bits.ADIE = 1;

    /* Thermal band classification (S.16, S.17) */
    if (raw < 700u) {
        thermal_mode = 'N';
        thermal_cap  = 24u;
    } else if (raw < 900u) {
        thermal_mode = 'D';
        thermal_cap  = 8u;
    } else {
        thermal_mode = 'H';
        thermal_cap  = 0u;
    }
}

/* =======================================================================
 * limit_effective()
 *
 * Returns ee = min(requested_limit, thermal_cap) (S.20, S.30).
 * Possible return values: 0, 8, 16, 24.
 *
 * This function is intentionally minimal: no UART, no formatting,
 * no string operations — just a comparison of two uint8_t globals.
 * Member C's display code calls this directly to get the two ee digits.
 *
 * Called by:
 *   - Member A's STS builder  (ee field of $STSmxxxxcee#)
 *   - Member C's display driver (Page 1 ee digits)
 * ===================================================================== */
uint8_t limit_effective(void)
{
    return (requested_limit < thermal_cap) ? requested_limit : thermal_cap;
}

/* =======================================================================
 * thermal_reset()
 *
 * Restores all Member-B state to $GO# initial conditions:
 *
 *   requested_limit = 0    S.53/S.57 — ee starts 00 until $LIMxx#
 *   connected_mask  = 0    no ports connected at start (S.52)
 *   thermal_mode    = 'N'  S.55 — provisional NORMAL
 *   thermal_cap     = 24   matching NORMAL cap
 *   adc_ready       = 0    discard any result that arrived before $GO#
 *   adc_tick_count  = 0    500 ms cadence starts fresh
 *
 * Member A calls this from the $GO# handler BEFORE adc_start_conversion().
 * ===================================================================== */
void thermal_reset(void)
{
    requested_limit = 0u;
    connected_mask  = 0u;
    thermal_mode    = 'N';
    thermal_cap     = 24u;
    adc_ready       = 0u;
    adc_tick_count  = 0u;
}
