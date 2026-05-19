/*
 * CENG 336 THE3 optional starter template.
 *
 * Provided here:
 *   - byte-level RX/TX ring buffers
 *   - interrupt-side EUSART byte enqueue/dequeue structure
 *
 * Left to you, and graded:
 *   - EUSART register setup for 115200 8N1 on RC6/RC7
 *   - timer configuration and 100 ms cabinet tick generation
 *   - ADC setup, sampling, and thermal-band classification
 *   - all protocol logic: frame parsing, ACK/STS construction, lifecycle
 *   - RB6 interrupt-on-change handling and 7-segment display driving
 *
 * You may use this file, ignore it, or rewrite it. Grading is based on
 * the externally visible behavior in the THE3 specification.
 */

#include <xc.h>
#include <stdint.h>

#include "pragmas.h"

#define _XTAL_FREQ 40000000UL
#define RB_SIZE 64u

typedef struct {
    volatile uint8_t head;
    volatile uint8_t tail;
    volatile uint8_t data[RB_SIZE];
} ByteRing;

static volatile ByteRing rx_ring;
static volatile ByteRing tx_ring;

static uint8_t rb_next(uint8_t index)
{
    index++;
    if (index >= RB_SIZE) {
        index = 0;
    }
    return index;
}

static uint8_t rb_is_empty(volatile ByteRing *rb)
{
    return rb->head == rb->tail;
}

static uint8_t rb_is_full(volatile ByteRing *rb)
{
    return rb_next(rb->head) == rb->tail;
}

static uint8_t rb_push(volatile ByteRing *rb, uint8_t value)
{
    uint8_t next = rb_next(rb->head);
    if (next == rb->tail) {
        return 0;
    }
    rb->data[rb->head] = value;
    rb->head = next;
    return 1;
}

static uint8_t rb_pop(volatile ByteRing *rb, uint8_t *value)
{
    if (rb_is_empty(rb)) {
        return 0;
    }
    *value = rb->data[rb->tail];
    rb->tail = rb_next(rb->tail);
    return 1;
}

uint8_t uart_rx_available(void)
{
    return !rb_is_empty(&rx_ring);
}

uint8_t uart_read_byte(uint8_t *value)
{
    return rb_pop(&rx_ring, value);
}

uint8_t uart_write_byte(uint8_t value)
{
    if (!rb_push(&tx_ring, value)) {
        return 0;
    }

    /*
     * Enable the TX-empty interrupt after queueing a byte. Complete
     * EUSART register setup belongs in eusart_init().
     */
    PIE1bits.TX1IE = 1;
    return 1;
}

void eusart_init(void)
{
    /*
     * TODO: configure EUSART1 for 115200 baud, 8 data bits, no parity,
     * and 1 stop bit on RC6/RC7. Enable receive interrupts. Leave TX1IE
     * disabled until uart_write_byte() has queued data.
     */
}

void cabinet_tick_init(void)
{
    /*
     * TODO: configure a hardware timer to produce the 100 ms cabinet
     * tick. Use Fosc = 40 MHz and show your timer calculation in
     * comments.
     */
}

void adc_init(void)
{
    /*
     * TODO: configure AN12/RH4 as a 10-bit right-adjusted ADC input.
     * Show the relevant register choices in comments.
     */
}

void adc_start_conversion(void)
{
    /*
     * TODO: start one ADC conversion.
     */
}

void rb6_ioc_init(void)
{
    /*
     * TODO: configure RB6 interrupt-on-change. RB6 actions shall fire
     * only on the release (rising) edge.
     */
}

void display_init(void)
{
    /*
     * TODO: configure PORTJ and PORTH[0:3] for the 7-segment display.
     */
}

void __interrupt() isr(void)
{
    if (PIE1bits.RC1IE && PIR1bits.RC1IF) {
        uint8_t byte = RCREG1;
        (void)rb_push(&rx_ring, byte);
    }

    if (PIE1bits.TX1IE && PIR1bits.TX1IF) {
        uint8_t byte;
        if (rb_pop(&tx_ring, &byte)) {
            TXREG1 = byte;
        } else {
            PIE1bits.TX1IE = 0;
        }
    }

    /* TODO: handle your 100 ms timer interrupt here. */

    /* TODO: handle ADC completion here. */

    /* TODO: handle RB6 interrupt-on-change here. */
}

void main(void)
{
    /*
     * TODO: call your initialization functions after implementing them,
     * then enable peripheral and global interrupts.
     */

    for (;;) {
        uint8_t byte;

        while (uart_read_byte(&byte)) {
            /* TODO: feed `byte` into your $...# frame parser. */
        }

        /* TODO: implement the rest of the cabinet's tick / main-loop
         * behavior here. */
    }
}
