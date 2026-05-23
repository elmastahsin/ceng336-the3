#include <xc.h>
#include <stdint.h>
#include "cabinet.h"
#include "display.h"

extern volatile uint16_t adc_last;
extern volatile uint8_t connected_mask;
extern uint8_t limit_effective(void);

volatile uint8_t display_page = 0;
volatile uint8_t rb6_release_flag = 0;

#define SEG_BLANK 0x00

static const uint8_t SEG_PATTERNS[10] = {
    0x3F, 
    0x06, 
    0x5B, 
    0x4F, 
    0x66, 
    0x6D, 
    0x7D, 
    0x07, 
    0x7F, 
    0x6F  
};

static const uint8_t DIGIT_MASKS[4] = {
    0x01, 
    0x02, 
    0x04,
    0x08 
};

static volatile uint8_t display_digits[4] = {
    SEG_BLANK, SEG_BLANK, SEG_BLANK, SEG_BLANK
};

static volatile uint8_t current_digit = 0;
static volatile uint8_t rb6_prev = 1;

void display_init(void)
{
    TRISJ &= 0x80;
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
        PIE1bits.ADIE = 0;
        uint16_t value = adc_last;
        PIE1bits.ADIE = 1;

        if (value > 1023) {
            value = 1023;
        }

        display_digits[0] = SEG_PATTERNS[(value / 1000) % 10];
        display_digits[1] = SEG_PATTERNS[(value / 100)  % 10];
        display_digits[2] = SEG_PATTERNS[(value / 10)   % 10];
        display_digits[3] = SEG_PATTERNS[value % 10];
    }
    else {
        uint8_t ee = limit_effective();
        uint8_t mask = connected_mask & 0x07;

        display_digits[0] = SEG_PATTERNS[(ee / 10) % 10];
        display_digits[1] = SEG_PATTERNS[ee % 10];
        display_digits[2] = SEG_BLANK;
        display_digits[3] = SEG_PATTERNS[mask];
    }
}

void display_process_button(void)
{
    if (cab_state != ST_ACTIVE) {
        rb6_release_flag = 0;
        return;
    }

    if (rb6_release_flag) {
        rb6_release_flag = 0;
        display_page ^= 1;
    }
}

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
