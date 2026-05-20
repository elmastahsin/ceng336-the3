/*
 * CENG336 THE3 - Three-Port EV Charging Cabinet
 * Uye A: Parser + State Machine + Tick + EUSART + Integration
 *
 * Bu dosya template'ten evrilmistir. Hazir gelen kisim: ring buffer + ISR
 * icindeki RX/TX byte enqueue/dequeue iskeleti.
 */
#include <xc.h>
#include <stdint.h>
#include <stdio.h>      /* sprintf - STS frame'i kurmak icin */
#include "pragmas.h"
#include "cabinet.h"

/* _XTAL_FREQ pragmas.h icinde zaten tanimli */
#define RB_SIZE 64u     /* S.67: en az 32 byte; 64 fazlasiyla yeterli */

/* ======================================================================
 * 1) RING BUFFER  (template'ten - dokunmadik)
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

static uint8_t rb_push(volatile ByteRing *rb, uint8_t value) {
    uint8_t next = rb_next(rb->head);
    if (next == rb->tail) return 0;          /* dolu - byte dusuruluyor */
    rb->data[rb->head] = value;
    rb->head = next;
    return 1;
}
static uint8_t rb_pop(volatile ByteRing *rb, uint8_t *value) {
    if (rb_is_empty(rb)) return 0;
    *value = rb->data[rb->tail];
    rb->tail = rb_next(rb->tail);
    return 1;
}

uint8_t uart_read_byte(uint8_t *value) { return rb_pop(&rx_ring, value); }

uint8_t uart_write_byte(uint8_t value) {
    if (!rb_push(&tx_ring, value)) return 0;
    PIE1bits.TX1IE = 1;   /* byte kuyruga girdi -> TX-empty interrupt'i ac */
    return 1;
}

/* ======================================================================
 * 2) GLOBAL STATE  (sahip: Uye A)
 * ====================================================================== */
volatile CabState cab_state     = ST_WAITING;
volatile uint8_t  connected_mask = 0;
volatile uint8_t  tick_flag     = 0;

/* Pending in-run komut (S.48: bir sonraki tick'te uygulanir).
 * Simulator iki tick arasi en fazla 1 komut yollar -> tek slot yeterli. */
typedef enum { CMD_NONE, CMD_CON, CMD_DIS, CMD_LIM } PendKind;
static volatile PendKind pend_kind = CMD_NONE;
static volatile uint8_t  pend_arg  = 0;     /* CON/DIS: port no | LIM: amper */

/* Pending ACK (S.27: ayni anda en fazla 1 ACK). */
static volatile uint8_t ack_pending = 0;
static volatile uint8_t ack_code    = 0;    /* 0,1,2,3 */

static uint8_t adc_div = 0;                 /* 500 ms = her 5. tick (S.14) */

/* ======================================================================
 * 3) EUSART INIT  (S.60: 115200 8N1, RC6/RC7)
 * ====================================================================== */
void eusart_init(void) {
    /* TRISC6/7 input: datasheet EUSART pinlerini input olarak ister */
    TRISCbits.TRISC6 = 1;
    TRISCbits.TRISC7 = 1;

    /* Baud: BRG16=1, BRGH=1 modunda  baud = Fosc / (4*(SPBRG+1))
     * SPBRG = 40e6/(4*115200) - 1 = 85.8 -> 86 (hata ~ -0.2%) */
    BAUDCON1bits.BRG16 = 1;
    TXSTA1bits.BRGH    = 1;
    SPBRGH1 = 0;
    SPBRG1  = 86;

    TXSTA1bits.SYNC = 0;   /* asenkron mod */
    RCSTA1bits.SPEN = 1;   /* seri port enable */
    TXSTA1bits.TXEN = 1;   /* verici enable */
    RCSTA1bits.CREN = 1;   /* surekli alim enable */

    PIE1bits.RC1IE = 1;    /* RX interrupt aktif */
    PIE1bits.TX1IE = 0;    /* TX interrupt sadece veri kuyruktayken acilir */
}

/* ======================================================================
 * 4) TIMER0 - 100 ms cabinet tick  (S.46, S.62)
 * ====================================================================== */
/* Fosc/4 = 10 MHz instruction clock; prescaler 1:64 -> 156250 Hz
 * 100 ms = 15625 sayim ; preload = 65536-15625 = 49911 = 0xC2F7 */
#define T0_RELOAD_H 0xC2
#define T0_RELOAD_L 0xF7

void cabinet_tick_init(void) {
    T0CONbits.T08BIT = 0;   /* 16-bit mod */
    T0CONbits.T0CS   = 0;   /* internal instruction clock (Fosc/4) */
    T0CONbits.PSA    = 0;   /* prescaler kullaniliyor */
    T0CONbits.T0PS2  = 1;   /* 101 -> 1:64 prescaler */
    T0CONbits.T0PS1  = 0;
    T0CONbits.T0PS0  = 1;
    TMR0H = T0_RELOAD_H;    /* 16-bit yazimda once H (buffer), sonra L commit */
    TMR0L = T0_RELOAD_L;
    INTCONbits.TMR0IF = 0;
    INTCONbits.TMR0IE = 1;
    T0CONbits.TMR0ON  = 1;
}

/* ======================================================================
 * 5) FRAME PARSER  ($...# - S.1, S.2)
 * ====================================================================== */
/* En uzun gecerli body "LIM24" = 5 char. Buffer biraz fazlasiyla 8. */
#define FRAME_MAX 8
static uint8_t frame_buf[FRAME_MAX];
static uint8_t frame_len   = 0;
static uint8_t collecting  = 0;   /* '$' gorulduyse 1 */

/* Pending in-run komutu kuyruga koyar (sonraki tick uygular). */
static void queue_in_run(PendKind k, uint8_t arg) {
    pend_kind = k;
    pend_arg  = arg;
}

/* Tamamlanmis frame body'sini siniflandirir ve uygular.
 * body: '$' ve '#' arasi karakterler, len uzunluk. */
static void dispatch_frame(uint8_t *body, uint8_t len) {
    /* --- lifecycle komutlari: HEMEN etki eder (S.47) --- */
    if (len == 2 && body[0]=='G' && body[1]=='O') {
        /* $GO# yalnizca WAITING'de kabul (S.4, tablo) */
        if (cab_state == ST_WAITING) {
            cab_state = ST_ACTIVE;
            ack_pending = 1; ack_code = 0;        /* S.33: ACK00 kuyrukla */
            adc_div = 0;
            adc_start_conversion();               /* S.15/S.56: cold-start ADC */
            cabinet_tick_init();                  /* S.46: ilk tick 100 ms sonra */
        }
        return;
    }
    if (len == 3 && body[0]=='E' && body[1]=='N' && body[2]=='D') {
        /* $END# yalnizca ACTIVE'de kabul */
        if (cab_state == ST_ACTIVE) {
            cab_state = ST_END;
            T0CONbits.TMR0ON = 0;                 /* tick dur */
            INTCONbits.TMR0IE = 0;
            display_blank();                      /* S.5, S.37: ekran sondur */
            /* S.36: ACK yok, S.5: bundan sonra TX yok */
        }
        return;
    }

    /* in-run komutlar yalnizca ACTIVE'de anlamli */
    if (cab_state != ST_ACTIVE) return;

    /* --- $CONp# / $DISp# : len 4, p in {0,1,2} (S.6) --- */
    if (len == 4 && body[1]=='O' && body[2]=='N' && body[0]=='C') {
        uint8_t p = body[3] - '0';
        if (p <= 2) queue_in_run(CMD_CON, p);     /* gecersiz p -> sessiz drop */
        return;
    }
    if (len == 4 && body[0]=='D' && body[1]=='I' && body[2]=='S') {
        uint8_t p = body[3] - '0';
        if (p <= 2) queue_in_run(CMD_DIS, p);
        return;
    }

    /* --- $LIMxx# : len 5, xx in {00,08,16,24} (S.9) --- */
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
    /* eslesmeyen body -> sessizce yok say (S.2, S.66) */
}

/* Tek byte'i parser'a verir. $...# cercevesini cikarir. */
static void parser_feed(uint8_t b) {
    if (b == '$') {                  /* yeni frame baslangici */
        collecting = 1;
        frame_len  = 0;
        return;
    }
    if (!collecting) return;         /* frame disindaki byte'lar ignore (S.1) */
    if (b == '#') {                  /* frame tamam */
        collecting = 0;
        dispatch_frame(frame_buf, frame_len);
        return;
    }
    if (frame_len >= FRAME_MAX) {    /* asiri uzun -> bozuk, frame'i iptal et */
        collecting = 0;
        return;
    }
    frame_buf[frame_len++] = b;
}

/* ======================================================================
 * 6) FRAME TX  (ACK / STS - S.24, S.25)
 * ====================================================================== */
static void send_ack(uint8_t code) {
    char buf[8];
    /* $ACKCC#  - 7 byte */
    sprintf(buf, "$ACK%02u#", (unsigned)code);
    for (uint8_t i = 0; buf[i]; i++) uart_write_byte((uint8_t)buf[i]);
}

static void send_sts(void) {
    char buf[16];
    uint8_t ee = limit_effective();          /* B: min(requested, cap) - S.20 */
    /* $STSmxxxxcee#  - 13 byte. xxxx ve ee leading-zero'lu (S.28-S.31) */
    sprintf(buf, "$STS%c%04u%u%02u#",
            thermal_band, (unsigned)adc_last,
            (unsigned)(connected_mask & 0x07), (unsigned)ee);
    for (uint8_t i = 0; buf[i]; i++) uart_write_byte((uint8_t)buf[i]);
}

/* ======================================================================
 * 7) CABINET TICK  (Algorithm 1 - her 100 ms)
 * ====================================================================== */
static void cabinet_tick(void) {
    /* Algoritma adim 2-4: ACTIVE degilsek hicbir sey yapma, cikis */
    if (cab_state != ST_ACTIVE) return;

    /* Adim 5: pending in-run komutu uygula, kabul edilirse ACK kuyrukla.
     * S.3/S.11: idempotent komut state degistirmez -> ACK yok. */
    switch (pend_kind) {
        case CMD_CON: {
            uint8_t bit = (uint8_t)(1u << pend_arg);
            if (!(connected_mask & bit)) {       /* zaten bagli degilse */
                connected_mask |= bit;
                ack_pending = 1; ack_code = 1;   /* ACK01 (S.7) */
            }
            break;
        }
        case CMD_DIS: {
            uint8_t bit = (uint8_t)(1u << pend_arg);
            if (connected_mask & bit) {          /* bagliysa */
                connected_mask &= (uint8_t)~bit;
                ack_pending = 1; ack_code = 2;   /* ACK02 (S.8) */
            }
            break;
        }
        case CMD_LIM:
            if (requested_limit != pend_arg) {   /* deger degisiyorsa */
                requested_limit = pend_arg;
                ack_pending = 1; ack_code = 3;   /* ACK03 (S.10) */
            }
            break;
        default: break;
    }
    pend_kind = CMD_NONE;

    /* Adim 6: tamamlanmis ADC sonucunu isle (B'nin fonksiyonu).
     * S.50: adc_done_flag set ise band/cap guncellenir. */
    if (adc_done_flag) {
        thermal_process();
        adc_done_flag = 0;
    }

    /* Adim 7: RB6 release flag'i -> display sayfasi (C'nin sorumlulugu).
     * BAGIMLILIK: C, RB6 IOC ISR'inde release edge yakalar ve
     * display_page'i gunceller; debounce'u kendi tick sayaci ile yapar.
     * A burada ekstra is yapmaz. */

    /* Adim 8-9: ee zaten send_sts() icinde limit_effective() ile
     * hesaplaniyor; display buffer'i C dolduruyor. */
    display_update_buffer();

    /* Adim 10: tek frame TX - ACK oncelikli, yoksa STS (S.25, S.51) */
    if (ack_pending) {
        send_ack(ack_code);
        ack_pending = 0;                          /* S.26: slot'u temizle */
    } else {
        send_sts();
    }

    /* 500 ms ADC cadence: her 5. tick'te yeni conversion (S.14) */
    if (++adc_div >= 5) {
        adc_div = 0;
        adc_start_conversion();
    }
}

/* ======================================================================
 * 8) INTERRUPT SERVICE ROUTINE  (tek seviye - high/low bolme yok)
 * ====================================================================== */
void __interrupt() isr(void) {
    /* --- EUSART RX --- */
    if (PIE1bits.RC1IE && PIR1bits.RC1IF) {
        /* S.65: OERR/FERR sessiz kurtarma. FERR biti RCREG okunmadan
         * ONCE okunmali (okuma FERR'i temizler). */
        uint8_t ferr = RCSTA1bits.FERR;
        if (RCSTA1bits.OERR) {          /* overrun: CREN cevir, FIFO bosalt */
            RCSTA1bits.CREN = 0;
            RCSTA1bits.CREN = 1;
        }
        uint8_t byte = RCREG1;          /* okuma FERR'i de temizler */
        /* framing error'lu byte at; S.5: END sonrasi frame'leri yok say */
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
            PIE1bits.TX1IE = 0;         /* kuyruk bos -> TX interrupt'i kapat */
        }
    }

    /* --- Timer0: 100 ms tick --- */
    if (INTCONbits.TMR0IE && INTCONbits.TMR0IF) {
        TMR0H = T0_RELOAD_H;            /* once H buffer'a, sonra L commit eder */
        TMR0L = T0_RELOAD_L;
        INTCONbits.TMR0IF = 0;
        tick_flag = 1;                  /* agir is main loop'a ertelenir (S.68) */
    }

    /* --- ADC tamamlandi (sahip: Uye B) ---
     * BAGIMLILIK: B, ADIF/ADIE branch'ini buraya ekleyecek; ADRES'i
     * adc_last'a yazip adc_done_flag = 1 yapacak. */

    /* --- RB6 interrupt-on-change (sahip: Uye C) ---
     * BAGIMLILIK: C, RBIF branch'ini buraya ekleyecek; release (rising)
     * edge'i yakalayip display_page'i toggle edecek. */
}

/* ======================================================================
 * 9) MAIN
 * ====================================================================== */
void main(void) {
    /* Init - WAITING modunda baslar (S.4: GO oncesi sessiz) */
    eusart_init();
    adc_init();          /* B */
    rb6_ioc_init();      /* C */
    display_init();      /* C */
    /* cabinet_tick_init() $GO# kabul edilince cagrilir (S.46) */

    /* Tek seviyeli interrupt: high/low priority bolme yok (template ISR). */
    RCONbits.IPEN = 0;
    INTCONbits.PEIE = 1;
    INTCONbits.GIE  = 1;

    for (;;) {
        /* Gelen byte'lari parser'a besle */
        uint8_t byte;
        while (uart_read_byte(&byte)) {
            parser_feed(byte);
        }

        /* Tick geldiyse cabinet_tick calistir (agir is burada, ISR'da degil) */
        if (tick_flag) {
            tick_flag = 0;
            cabinet_tick();
        }
    }
}

/* ======================================================================
 * 10) GECICI STUB'LAR  -  ENTEGRASYONDA SILINECEK
 * ----------------------------------------------------------------------
 * Asagidaki tanimlar Uye B ve Uye C'nin modulleri main'e merge edilince
 * SILINECEK. Su an A'nin branch'i tek basina derlensin / test edilsin
 * diye konuldu. B -> adc.c , C -> display.c kendi dosyalarini ekleyince
 * bu blok kaldirilir.
 * ====================================================================== */
volatile uint16_t adc_last        = 0;
volatile char     thermal_band    = 'N';   /* S.55: ilk ADC oncesi NORMAL */
volatile uint8_t  thermal_cap     = 24;
volatile uint8_t  requested_limit = 0;     /* S.53: baslangic 00 */
volatile uint8_t  adc_done_flag   = 0;
volatile uint8_t  display_page    = 0;
volatile uint8_t  display_active  = 0;

void adc_init(void)             { /* B yazacak */ }
void adc_start_conversion(void) { /* B yazacak */ }
void rb6_ioc_init(void)         { /* C yazacak */ }
void display_init(void)         { /* C yazacak */ }
void thermal_process(void)      { /* B yazacak */ }
void display_update_buffer(void){ /* C yazacak */ }
void display_blank(void)        { /* C yazacak */ }

uint8_t limit_effective(void) {
    /* B'nin gercek surumu min(requested_limit, thermal_cap) dondurur (S.20) */
    uint8_t r = requested_limit, c = thermal_cap;
    return (r < c) ? r : c;
}
