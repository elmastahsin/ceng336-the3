#include <xc.h>
#include <stdint.h>
#include "cabinet.h"   // shared CabState enum and cab_state
#include "display.h"

// cab_state comes from cabinet.h. adc_last, connected_mask and
// limit_effective() are owned by thermal.c, read here via extern.
extern volatile uint16_t adc_last;
extern volatile uint8_t connected_mask;
extern uint8_t limit_effective(void);

// Owned by this display module (single definition here).
volatile uint8_t display_page = 0;
volatile uint8_t rb6_release_flag = 0;

#define SEG_BLANK 0x00

// Common-cathode 7-segment patterns.
// PORTJ0..PORTJ6 correspond to segments A..G.
// Since the board uses common-cathode displays, logic 1 turns a segment on.
static const uint8_t SEG_PATTERNS[10] = {
    0x3F, // 0
    0x06, // 1
    0x5B, // 2
    0x4F, // 3
    0x66, // 4
    0x6D, // 5
    0x7D, // 6
    0x07, // 7
    0x7F, // 8
    0x6F  // 9
};

// Digit select masks.
// According to the board/spec:
// PORTH0 -> leftmost digit
// PORTH1 -> second digit
// PORTH2 -> third digit
// PORTH3 -> rightmost digit
static const uint8_t DIGIT_MASKS[4] = {
    0x01, 
    0x02, 
    0x04,
    0x08 
};

// Display buffer.
// display_digits[0] is the leftmost digit.
// display_digits[3] is the rightmost digit.
static volatile uint8_t display_digits[4] = {
    SEG_BLANK, SEG_BLANK, SEG_BLANK, SEG_BLANK
};

static volatile uint8_t current_digit = 0;
static volatile uint8_t rb6_prev = 1;

// ============================================================
// DISPLAY INITIALIZATION AND BUFFER UPDATE PART
// ============================================================

void display_init(void)
{
    // RJ0-RJ6 drive segments A-G.
    // RJ7 is DP and is not used in this assignment.
    TRISJ &= 0x80;

    // RH0-RH3 select the four display digits.
    TRISH &= 0xF0;   

    LATJ = 0x00;
    LATH &= 0xF0;

    display_page = 0;
    display_blank();
}

void display_blank(void)
{
    display_digits[0] = SEG_BLANK;
    display_digits[1] = SEG_BLANK;
    display_digits[2] = SEG_BLANK;
    display_digits[3] = SEG_BLANK;

    LATJ = 0x00;
    LATH &= 0xF0;
}

void display_update_buffer(void)
{
    if (cab_state != ST_ACTIVE) {
        display_blank();
        return;
    }

    if (display_page == 0) {
        // Page 0 displays the latest ADC value as four decimal digits.
        // Example: adc_last = 480 is displayed as 0480.
        uint16_t value = adc_last;

        if (value > 1023) {
            value = 1023;
        }

        display_digits[0] = SEG_PATTERNS[(value / 1000) % 10];
        display_digits[1] = SEG_PATTERNS[(value / 100)  % 10];
        display_digits[2] = SEG_PATTERNS[(value / 10)   % 10];
        display_digits[3] = SEG_PATTERNS[value % 10];
    }
    else {
         // Page 1 displays:
         // digit 0: effective limit tens
         // digit 1: effective limit ones
         // digit 2: blank
         // digit 3: connected port mask
         // Example: ee = 24, connected_mask = 5 -> 24_5
        uint8_t ee = limit_effective();
        uint8_t mask = connected_mask & 0x07;

         // Defensive note:
         // limit_effective() should only return 0, 8, 16, or 24.
         // If another value is returned, the display may show an unexpected number.
        display_digits[0] = SEG_PATTERNS[(ee / 10) % 10];
        display_digits[1] = SEG_PATTERNS[ee % 10];
        display_digits[2] = SEG_BLANK;
        display_digits[3] = SEG_PATTERNS[mask];
    }
}

void display_process_button(void)
{
     // Button releases outside ACTIVE should not change the display page.
    if (cab_state != ST_ACTIVE) {
        rb6_release_flag = 0;
        return;
    }

    if (rb6_release_flag) {
        rb6_release_flag = 0;
        display_page ^= 1;
    }
}

// ============================================================
// TIMER1 DISPLAY MULTIPLEX INITIALIZATION
// ============================================================

void timer1_display_init(void)
{
    T1CON = 0x00;

    TMR1H = 0xF6;
    TMR1L = 0x3C;

    T1CONbits.T1CKPS0 = 1;
    T1CONbits.T1CKPS1 = 1;

    PIR1bits.TMR1IF = 0;
    PIE1bits.TMR1IE = 1;

    T1CONbits.TMR1ON = 1;
}

void rb6_ioc_init(void)
{
    TRISBbits.TRISB6 = 1;

    rb6_prev = PORTBbits.RB6;

    INTCONbits.RBIF = 0;
    INTCONbits.RBIE = 1;
}

// ============================================================
// INTERRUPT HANDLER PART
// IMPORTANT:
// These are NOT standalone __interrupt() functions.
// The final project must have only one global ISR.
// The main ISR should call these handler functions when the
// corresponding interrupt flag is set.
// ============================================================

void display_timer1_handler(void)
{
    PIR1bits.TMR1IF = 0;

    TMR1H = 0xF6;
    TMR1L = 0x3C;

    LATH &= 0xF0;

    if (cab_state != ST_ACTIVE) {
        LATJ = 0x00;
        return;
    }

    LATJ = display_digits[current_digit] & 0x7F;
    LATH = (LATH & 0xF0) | DIGIT_MASKS[current_digit];

    current_digit++;
    if (current_digit >= 4) {
        current_digit = 0;
    }
}

void rb6_ioc_handler(void)
{
    uint8_t now;

    now = PORTBbits.RB6;

    if (rb6_prev == 0 && now == 1) {
        rb6_release_flag = 1;
    }

    rb6_prev = now;

    INTCONbits.RBIF = 0;
}