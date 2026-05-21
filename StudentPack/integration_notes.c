/*
 * integration_notes.c  —  NOT compiled; reference only.
 *
 * Shows Member A exactly where each thermal.c hook goes in main.c.
 * Shows Member C what to call in display.c.
 * Search "STEP N" or "MEMBER C" and act on each block.
 */

/* =====================================================================
 * MEMBER A — STEP 1
 * Add at the top of main.c alongside your other includes.
 * =================================================================== */
#include "thermal.h"


/* =====================================================================
 * MEMBER A — STEP 2
 * ADC ISR branch. Paste into __interrupt() isr() AFTER the two EUSART
 * branches and BEFORE the timer and RB6 branches.
 * =================================================================== */
    if (PIE1bits.ADIE && PIR1bits.ADIF) {
        /* Right-adjusted: ADRESL = bits[7:0], ADRESH[1:0] = bits[9:8].
         * Read ADRESL first: PIC18F8722 hardware freezes ADRESH until
         * ADRESL is read (DS §22.3).                                   */
        uint8_t lo    = ADRESL;
        uint8_t hi    = ADRESH & 0x03u;
        adc_last      = (uint16_t)lo | ((uint16_t)hi << 8u);
        adc_ready     = 1u;
        PIR1bits.ADIF = 0;
    }


/* =====================================================================
 * MEMBER A — STEP 3
 * Call adc_init() in main() before enabling GIE/PEIE.
 * =================================================================== */
    adc_init();
    /* ... your other inits ... */
    INTCONbits.PEIE = 1;
    INTCONbits.GIE  = 1;


/* =====================================================================
 * MEMBER A — STEP 4
 * $GO# acceptance handler.
 * Call thermal_reset() then adc_start_conversion() IN THAT ORDER.
 *   thermal_reset() zeros requested_limit, connected_mask, thermal state.
 *   adc_start_conversion() fires the mandatory cold-start conversion (S.56).
 * =================================================================== */
    thermal_reset();            /* zero all B-state to initial conditions   */
    adc_start_conversion();     /* cold-start ADC; result ready in ~33 µs   */


/* =====================================================================
 * MEMBER A — STEP 5
 * $LIMxx# acceptance handler.
 * Write the parsed amps value to requested_limit.
 * Replace `parsed_amps` with your local variable (value is 0, 8, 16, 24).
 * =================================================================== */
    requested_limit = parsed_amps;


/* =====================================================================
 * MEMBER A — STEP 6
 * $CONp# and $DISp# acceptance handlers.
 * Update connected_mask when a port connects or disconnects.
 * =================================================================== */
    /* $CONp# accepted — set bit p */
    connected_mask |= (1u << p);

    /* $DISp# accepted — clear bit p */
    connected_mask &= ~(1u << p);


/* =====================================================================
 * MEMBER A — STEP 7
 * 100 ms tick handler, Algorithm-1 step 6.
 * These two calls must be made ONLY while phase == ACTIVE (S.14).
 * thermal_update() must come BEFORE adc_tick().
 * =================================================================== */
    /* Algorithm-1 step 6 — only reached when phase == ACTIVE */
    thermal_update();       /* classify latest ADC result if ready          */
    adc_tick();             /* trigger new conversion every 500 ms          */


/* =====================================================================
 * MEMBER A — STEP 8
 * STS frame builder.
 * Read adc_last under an ADIE mask (16-bit read is non-atomic on 8-bit CPU).
 * =================================================================== */
    /* Atomic snapshot of adc_last for the xxxx field */
    PIE1bits.ADIE = 0;
    uint16_t adc_snap = adc_last;
    PIE1bits.ADIE = 1;

    char sts_buf[14];   /* "$STSmxxxxcee#" = 13 chars + null             */
    sprintf(sts_buf,
            "$STS%c%04u%u%02u#",
            (char)    thermal_mode,       /* m    — 'N', 'D', or 'H'    */
            (unsigned)adc_snap,           /* xxxx — 0000 to 1023        */
            (unsigned)connected_mask,     /* c    — 0 to 7              */
            (unsigned)limit_effective()   /* ee   — 00, 08, 16, or 24   */
    );
    /* Transmit sts_buf byte-by-byte via uart_write_byte().             */


/* =====================================================================
 * MEMBER C — display.c
 *
 * #include "thermal.h" at the top of display.c.
 *
 * Page 0 — 4-digit ADC reading (0000–1023):
 *   Read adc_last under ADIE mask for a consistent 16-bit value.
 *
 *     PIE1bits.ADIE = 0;
 *     uint16_t raw = adc_last;
 *     PIE1bits.ADIE = 1;
 *     digits[3] = raw / 1000;
 *     digits[2] = (raw / 100) % 10;
 *     digits[1] = (raw /  10) % 10;
 *     digits[0] =  raw        % 10;
 *
 * Page 1 — ee (2 digits), blank, connected_mask (1 digit):
 *   Call limit_effective() for the ee value. It is short and has no
 *   side effects (no UART, no formatting — Member C's requirement met).
 *
 *     uint8_t ee = limit_effective();   // returns 0, 8, 16, or 24
 *     digits[3] = ee / 10;              // tens:  0, 0, 1, 2
 *     digits[2] = ee % 10;              // units: 0, 8, 6, 4
 *     digits[1] = BLANK;
 *     digits[0] = connected_mask;       // 0-7 — written by Member A
 * =================================================================== */
