#ifndef DISPLAY_H
#define DISPLAY_H

#include <stdint.h>

// Owned by display.c; the cabinet resets these at $GO# acceptance.
extern volatile uint8_t display_page;
extern volatile uint8_t rb6_release_flag;

void display_init(void);
void display_blank(void);
void display_update_buffer(void);

void timer1_display_init(void);
void display_timer1_handler(void);

void rb6_ioc_init(void);
void rb6_ioc_handler(void);
void display_process_button(void);

#endif