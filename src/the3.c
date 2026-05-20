/*
 * CENG336 THE3 - Three-Port EV Charging Cabinet
 * Uye A: Parser + State Machine + Tick + EUSART + Integration
 *
 * Ring buffer ve ISR icindeki RX/TX byte enqueue/dequeue iskeleti
 * the3_template.c'den alinmistir.
 */
#include <xc.h>
#include <stdint.h>
#include <stdio.h>
#include "pragmas.h"
#include "cabinet.h"

#define RB_SIZE 64u

/* ======================================================================
 * 1) RING BUFFER
 * ====================================================================== */
typedef struct {
    volatile uint8_t head;
    volatile uint8_t tail;
    volatile uint8_t data[RB_SIZE];
} ByteRing;

static volatile ByteRing rx_ring;
static volatile ByteRing tx_ring;

static uint8_t rb_next(uint8_t index) {
    index++;
    if (index >= RB_SIZE) index = 0;
    return index;
}
static uint8_t rb_is_empty(volatile ByteRing *rb) { return rb->head == rb->tail; }
static uint8_t rb_is_full(volatile ByteRing *rb) { return rb_next(rb->head) == rb->tail; }

static uint8_t rb_push(volatile ByteRing *rb, uint8_t value) {
    if (rb_is_full(rb)) return 0;
    rb->data[rb->head] = value;
    rb->head = rb_next(rb->head);
    return 1;
}
static uint8_t rb_pop(volatile ByteRing *rb, uint8_t *value) {
    if (rb_is_empty(rb)) return 0;
    *value = rb->data[rb->tail];
    rb->tail = rb_next(rb->tail);
    return 1;
}

uint8_t uart_rx_available(void) { return !rb_is_empty(&rx_ring); }

uint8_t uart_read_byte(uint8_t *value) { return rb_pop(&rx_ring, value); }

uint8_t uart_write_byte(uint8_t value) {
    if (!rb_push(&tx_ring, value)) return 0;
    PIE1bits.TX1IE = 1;   /* TX interrupt yalnizca kuyrukta veri varken acik */
    return 1;
}

/* ======================================================================
 * 2) GLOBAL STATE  (sahip: Uye A)
 * ====================================================================== */
volatile CabState cab_state      = ST_WAITING;
volatile uint8_t  connected_mask = 0;
volatile uint8_t  tick_flag      = 0;

/* Pending in-run komut: bir sonraki tick'te uygulanir (S.48).
 * Simulator iki tick arasi en fazla 1 komut yollar -> tek slot yeterli. */
typedef enum { CMD_NONE, CMD_CON, CMD_DIS, CMD_LIM } PendKind;
static volatile PendKind pend_kind = CMD_NONE;
static volatile uint8_t  pend_arg  = 0;

static volatile uint8_t ack_pending = 0;
static volatile uint8_t ack_code    = 0;

static uint8_t adc_div = 0;

/* ======================================================================
 * 3) EUSART INIT  (115200 8N1, RC6/RC7)
 * ====================================================================== */
void eusart_init(void) {
    TRISCbits.TRISC6 = 1;
    TRISCbits.TRISC7 = 1;

    /* BRG16=1, BRGH=1: baud = Fosc/(4*(SPBRG+1)); SPBRG=86 -> ~115200 */
    BAUDCON1bits.BRG16 = 1;
    TXSTA1bits.BRGH    = 1;
    SPBRGH1 = 0;
    SPBRG1  = 86;

    TXSTA1bits.SYNC = 0;
    RCSTA1bits.SPEN = 1;
    TXSTA1bits.TXEN = 1;
    RCSTA1bits.CREN = 1;

    PIE1bits.RC1IE = 1;
    PIE1bits.TX1IE = 0;
}

/* ======================================================================
 * 4) TIMER0 - 100 ms cabinet tick
 * ====================================================================== */
/* Fosc/4=10MHz, prescaler 1:64 -> 156250Hz; 100ms=15625 sayim
 * preload = 65536-15625 = 0xC2F7 */
#define T0_RELOAD_H 0xC2
#define T0_RELOAD_L 0xF7

void cabinet_tick_init(void) {
    T0CONbits.T08BIT = 0;
    T0CONbits.T0CS   = 0;
    T0CONbits.PSA    = 0;
    T0CONbits.T0PS2  = 1;   /* 101 -> 1:64 prescaler */
    T0CONbits.T0PS1  = 0;
    T0CONbits.T0PS0  = 1;
    TMR0H = T0_RELOAD_H;    /* 16-bit yazimda once H, sonra L commit eder */
    TMR0L = T0_RELOAD_L;
    INTCONbits.TMR0IF = 0;
    INTCONbits.TMR0IE = 1;
    T0CONbits.TMR0ON  = 1;
}

/* ======================================================================
 * 5) FRAME PARSER  ($...#)
 * ====================================================================== */
#define FRAME_MAX 8
static uint8_t frame_buf[FRAME_MAX];
static uint8_t frame_len  = 0;
static uint8_t collecting = 0;

static void queue_in_run(PendKind k, uint8_t arg) {
    pend_kind = k;
    pend_arg  = arg;
}

/* body: '$' ve '#' arasi karakterler. */
static void dispatch_frame(uint8_t *body, uint8_t len) {
    /* lifecycle komutlari hemen etki eder (S.47) */
    if (len == 2 && body[0]=='G' && body[1]=='O') {
        if (cab_state == ST_WAITING) {
            cab_state = ST_ACTIVE;
            ack_pending = 1; ack_code = 0;
            adc_div = 0;
            adc_start_conversion();
            cabinet_tick_init();
        }
        return;
    }
    if (len == 3 && body[0]=='E' && body[1]=='N' && body[2]=='D') {
        if (cab_state == ST_ACTIVE) {
            cab_state = ST_END;
            T0CONbits.TMR0ON = 0;
            INTCONbits.TMR0IE = 0;
            display_blank();
        }
        return;
    }

    if (cab_state != ST_ACTIVE) return;

    if (len == 4 && body[0]=='C' && body[1]=='O' && body[2]=='N') {
        uint8_t p = body[3] - '0';
        if (p <= 2) queue_in_run(CMD_CON, p);
        return;
    }
    if (len == 4 && body[0]=='D' && body[1]=='I' && body[2]=='S') {
        uint8_t p = body[3] - '0';
        if (p <= 2) queue_in_run(CMD_DIS, p);
        return;
    }
    if (len == 5 && body[0]=='L' && body[1]=='I' && body[2]=='M') {
        uint8_t d0 = body[3] - '0';
        uint8_t d1 = body[4] - '0';
        if (d0 <= 9 && d1 <= 9) {
            uint8_t amps = d0*10 + d1;
            if (amps==0 || amps==8 || amps==16 || amps==24)
                queue_in_run(CMD_LIM, amps);
        }
        return;
    }
}

static void parser_feed(uint8_t b) {
    if (b == '$') {
        collecting = 1;
        frame_len  = 0;
        return;
    }
    if (!collecting) return;
    if (b == '#') {
        collecting = 0;
        dispatch_frame(frame_buf, frame_len);
        return;
    }
    if (frame_len >= FRAME_MAX) {   /* asiri uzun -> bozuk, frame'i iptal et */
        collecting = 0;
        return;
    }
    frame_buf[frame_len++] = b;
}

/* ======================================================================
 * 6) FRAME TX  (ACK / STS)
 * ====================================================================== */
static void send_ack(uint8_t code) {
    char buf[8];
    sprintf(buf, "$ACK%02u#", (unsigned)code);
    for (uint8_t i = 0; buf[i]; i++) uart_write_byte((uint8_t)buf[i]);
}

static void send_sts(void) {
    char buf[16];
    uint8_t ee = limit_effective();
    sprintf(buf, "$STS%c%04u%u%02u#",
            thermal_band, (unsigned)adc_last,
            (unsigned)(connected_mask & 0x07), (unsigned)ee);
    for (uint8_t i = 0; buf[i]; i++) uart_write_byte((uint8_t)buf[i]);
}

/* ======================================================================
 * 7) CABINET TICK  (Algorithm 1)
 * ====================================================================== */
static void cabinet_tick(void) {
    /* Parser $END#'i tick'ten once isleyebilir; o durumda hicbir sey
     * yapmadan ve TX etmeden cik (Algorithm 1, erken donus). */
    if (cab_state != ST_ACTIVE) return;

    switch (pend_kind) {
        case CMD_CON: {
            uint8_t bit = (uint8_t)(1u << pend_arg);
            if (!(connected_mask & bit)) {       /* idempotent ise ACK yok */
                connected_mask |= bit;
                ack_pending = 1; ack_code = 1;
            }
            break;
        }
        case CMD_DIS: {
            uint8_t bit = (uint8_t)(1u << pend_arg);
            if (connected_mask & bit) {
                connected_mask &= (uint8_t)~bit;
                ack_pending = 1; ack_code = 2;
            }
            break;
        }
        case CMD_LIM:
            if (requested_limit != pend_arg) {
                requested_limit = pend_arg;
                ack_pending = 1; ack_code = 3;
            }
            break;
        default: break;
    }
    pend_kind = CMD_NONE;

    if (adc_done_flag) {
        thermal_process();
        adc_done_flag = 0;
    }

    display_update_buffer();

    if (ack_pending) {
        send_ack(ack_code);
        ack_pending = 0;
    } else {
        send_sts();
    }

    if (++adc_div >= 5) {   /* 500 ms = her 5. tick */
        adc_div = 0;
        adc_start_conversion();
    }
}

/* ======================================================================
 * 8) INTERRUPT SERVICE ROUTINE
 * Tek seviye - high/low priority bolunmemeli: display mux cok sik fire
 * eder, bolersek RX byte kaybedilir.
 * ====================================================================== */
void __interrupt() isr(void) {
    /* --- EUSART RX --- */
    if (PIE1bits.RC1IE && PIR1bits.RC1IF) {
        /* FERR biti RCREG okunmadan ONCE okunmali (okuma onu temizler) */
        uint8_t ferr = RCSTA1bits.FERR;
        if (RCSTA1bits.OERR) {          /* overrun: CREN cevir, FIFO bosalt */
            RCSTA1bits.CREN = 0;
            RCSTA1bits.CREN = 1;
        }
        uint8_t byte = RCREG1;
        if (!ferr && cab_state != ST_END) {
            (void)rb_push(&rx_ring, byte);
        }
    }

    /* --- EUSART TX --- */
    if (PIE1bits.TX1IE && PIR1bits.TX1IF) {
        uint8_t byte;
        if (rb_pop(&tx_ring, &byte)) {
            TXREG1 = byte;
        } else {
            PIE1bits.TX1IE = 0;
        }
    }

    /* --- Timer0: 100 ms tick --- */
    if (INTCONbits.TMR0IE && INTCONbits.TMR0IF) {
        TMR0H = T0_RELOAD_H;
        TMR0L = T0_RELOAD_L;
        INTCONbits.TMR0IF = 0;
        tick_flag = 1;
    }

    /* BAGIMLILIK - Uye B: ADIF/ADIE branch'ini buraya ekleyecek;
     * ADRES'i adc_last'a yazip adc_done_flag = 1 yapacak. */

    /* BAGIMLILIK - Uye C: RBIF branch'ini buraya ekleyecek; RB6 release
     * (rising) edge'i yakalayip display_page'i toggle edecek. */
}

/* ======================================================================
 * 9) MAIN
 * ====================================================================== */
void main(void) {
    eusart_init();
    adc_init();          /* B */
    rb6_ioc_init();      /* C */
    display_init();      /* C */
    /* cabinet_tick_init() $GO# kabul edilince cagrilir */

    RCONbits.IPEN   = 0;   /* tek seviyeli interrupt */
    INTCONbits.PEIE = 1;
    INTCONbits.GIE  = 1;

    for (;;) {
        while (uart_rx_available()) {
            uint8_t byte;
            uart_read_byte(&byte);
            parser_feed(byte);
        }
        if (tick_flag) {
            tick_flag = 0;
            cabinet_tick();
        }
    }
}

/* ======================================================================
 * 10) GECICI STUB'LAR  -  ENTEGRASYONDA SILINECEK
 * Uye B (adc.c) ve Uye C (display.c) kendi dosyalarini ekleyince bu blok
 * kaldirilir. Su an A'nin branch'i tek basina derlensin diye konuldu.
 * ====================================================================== */
volatile uint16_t adc_last        = 0;
volatile char     thermal_band    = 'N';
volatile uint8_t  thermal_cap     = 24;
volatile uint8_t  requested_limit = 0;
volatile uint8_t  adc_done_flag   = 0;
volatile uint8_t  display_page    = 0;
volatile uint8_t  display_active  = 0;

void adc_init(void)             { }
void adc_start_conversion(void) { }
void rb6_ioc_init(void)         { }
void display_init(void)         { }
void thermal_process(void)      { }
void display_update_buffer(void){ }
void display_blank(void)        { }

uint8_t limit_effective(void) {
    uint8_t r = requested_limit, c = thermal_cap;
    return (r < c) ? r : c;
}
