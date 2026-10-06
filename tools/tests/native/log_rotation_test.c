#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#define WLOGI(...) ((void)0)
#define WLOGE(...) ((void)0)
#include "compositor_log_under_test.c"

static int contains(const char *path, const char *text) {
    char buf[4096] = {0};
    FILE *f = fopen(path, "r");
    assert(f);
    fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    return strstr(buf, text) != NULL;
}
int main(void) {
    banner_log("test", "before-first-session");
    assert(banner_wayland_set_log_path("first.log") == 0);
    banner_log("test", "first-session");
    assert(banner_wayland_set_log_path("first.log") == 0); /* reattach must not truncate */
    assert(contains("first.log", "before-first-session") && contains("first.log", "first-session"));
    assert(banner_wayland_set_log_path("second.log") == 0);
    banner_log("test", "second-session");
    assert(contains("second.log", "second-session") && !contains("first.log", "second-session"));
    assert(banner_wayland_set_log_path("missing/directory/log") == -1);
    banner_log("test", "still-second-session");
    assert(contains("second.log", "still-second-session"));
    fclose(g_log);
    return 0;
}
