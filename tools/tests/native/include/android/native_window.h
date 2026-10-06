#pragma once
#include <stdint.h>
typedef struct ANativeWindow ANativeWindow;
void ANativeWindow_release(ANativeWindow *window);
int32_t ANativeWindow_getWidth(ANativeWindow *window);
int32_t ANativeWindow_getHeight(ANativeWindow *window);
