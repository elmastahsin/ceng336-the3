/*
 * cabinet.h - CENG336 THE3 ortak lifecycle tanimlari
 *
 * Modul-ozel API'ler kendi header'larinda:
 *   thermal.h  -> ADC, thermal classifier, effective limit (Uye B)
 *   display.h  -> 7-segment display, RB6 (Uye C)
 *
 * Bu dosya yalnizca her uc modulun paylastigi lifecycle tipini tutar.
 */
#ifndef CABINET_H
#define CABINET_H

typedef enum { ST_WAITING, ST_ACTIVE, ST_END } CabState;

/* the3.c tanimlar; thermal.c kullanmaz, display.c okur. */
extern volatile CabState cab_state;

#endif /* CABINET_H */
