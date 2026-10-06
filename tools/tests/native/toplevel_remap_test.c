/* Exercise the production surface requests with a client waiting for configure before drawing.
 * Wayland transport and GPU import are mocked; commit/configure logic is extracted unchanged. */
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-server-core.h>
#include <wayland-server-protocol.h>
#include <xdg-shell-server-protocol.h>

enum resource_kind { SURFACE, TOPLEVEL, XDG_SURFACE, SHM_BUFFER, DMA_BUFFER };
struct wl_shm_buffer { int width, height; };
struct dmabuf_buffer { int width, height; };
#include "compositor_surface_types.c"

static struct wl_display *g_display;
static int g_output_w = 1564, g_output_h = 720;
static unsigned configures, role_configures, serial, render_requests;
static unsigned gpu_releases, shm_releases;
static int configured_width, configured_height, configured_fullscreen;

void wl_list_init(struct wl_list *list) { list->prev = list->next = list; }
void wl_list_remove(struct wl_list *list) {
    list->prev->next = list->next;
    list->next->prev = list->prev;
}
void wl_list_insert_list(struct wl_list *list, struct wl_list *other) {
    if (other->next == other) return;
    other->next->prev = list;
    other->prev->next = list->next;
    list->next->prev = other->prev;
    list->next = other->next;
}
void wl_array_init(struct wl_array *array) { memset(array, 0, sizeof(*array)); }
void *wl_array_add(struct wl_array *array, size_t size) {
    size_t offset = array->size;
    array->data = realloc(array->data, offset + size);
    assert(array->data);
    array->size = array->alloc = offset + size;
    return (char *)array->data + offset;
}
void wl_array_release(struct wl_array *array) { free(array->data); }
void *wl_resource_get_user_data(struct wl_resource *resource) { return resource->data; }
uint32_t wl_display_next_serial(struct wl_display *display) { return ++serial; }
void wl_resource_add_destroy_listener(struct wl_resource *resource, struct wl_listener *listener) {}
struct wl_shm_buffer *wl_shm_buffer_get(struct wl_resource *resource) {
    return resource->object.id == SHM_BUFFER ? resource->data : NULL;
}
void wl_resource_post_event(struct wl_resource *resource, uint32_t opcode, ...) {
    va_list args;
    va_start(args, opcode);
    if (resource->object.id == TOPLEVEL) {
        role_configures++;
        configured_width = va_arg(args, int);
        configured_height = va_arg(args, int);
        struct wl_array *states = va_arg(args, struct wl_array *);
        configured_fullscreen = 0;
        uint32_t *state;
        wl_array_for_each(state, states)
            if (*state == XDG_TOPLEVEL_STATE_FULLSCREEN) configured_fullscreen = 1;
    } else if (resource->object.id == XDG_SURFACE) {
        configures++;
        assert(role_configures == configures); /* role state must precede its serial */
        assert(va_arg(args, uint32_t) == serial);
    } else if (resource->object.id == SHM_BUFFER || resource->object.id == DMA_BUFFER) {
        if (resource->object.id == DMA_BUFFER) gpu_releases++;
        else shm_releases++;
    } else {
        assert(!"unexpected Wayland event");
    }
    va_end(args);
}

static void on_pending_buffer_destroyed(struct wl_listener *listener, void *data) {}
static struct dmabuf_buffer *get_dmabuf(struct wl_resource *resource) {
    return resource && resource->object.id == DMA_BUFFER ? resource->data : NULL;
}
static void drop_dmabuf(struct surface *surface, int paced) {
    if (surface->dmabuf) wl_buffer_send_release(surface->dmabuf);
    surface->dmabuf = NULL;
    surface->dmabuf_buf = NULL;
}
static void take_dmabuf(struct surface *surface, struct dmabuf_buffer *buffer, struct wl_resource *resource) {
    drop_dmabuf(surface, 1);
    surface->dmabuf = resource;
    surface->dmabuf_buf = buffer;
    surface->buf_w = buffer->width;
    surface->buf_h = buffer->height;
    surface->has_content = 1;
}
static void take_shm(struct surface *surface, struct wl_shm_buffer *buffer, struct wl_resource *resource) {
    surface->buf_w = buffer->width;
    surface->buf_h = buffer->height;
    surface->has_content = 1;
    wl_buffer_send_release(resource);
}
static void feedback_discard_all(struct wl_list *list) {}
static void surface_drop_idle(struct surface *surface) {}
static void surface_hold_idle(struct surface *surface, struct wl_resource *buffer) {}
static void cursor_publish_hidden(void) {}
static void cursor_publish_buffer(struct surface *surface, struct wl_resource *buffer) {}
static int has_fullsize_gamescope_frame(const struct surface *surface) { return 0; }
static void describe(const struct surface *surface, char *out, size_t size) { snprintf(out, size, "Gamescope"); }
static void banner_log(const char *area, const char *format, ...) {}
static void constraints_surface_commit(struct surface *surface) {}
static void banner_color_commit(struct wl_resource *resource) {}
static void map_toplevel(struct surface *surface) { surface->mapped = 1; }
static void unmap_toplevel(struct surface *surface) { surface->mapped = 0; }
static void schedule_render(void) { render_requests++; }

#include "compositor_remap_under_test.c"

static void init_surface(struct surface *surface, struct wl_resource *resource) {
    memset(surface, 0, sizeof(*surface));
    resource->object.id = SURFACE;
    resource->data = surface;
    surface->resource = resource;
    wl_list_init(&surface->pending_buffer_destroy.link);
    wl_list_init(&surface->children);
    wl_list_init(&surface->pending_frames);
    wl_list_init(&surface->frames);
    wl_list_init(&surface->pending_feedback);
    wl_list_init(&surface->feedback);
}

int main(void) {
    struct surface surface;
    struct wl_resource resource, toplevel = {.object = {.id = TOPLEVEL}}, xdg = {.object = {.id = XDG_SURFACE}};
    init_surface(&surface, &resource);
    toplevel.data = &surface;
    surface.role = ROLE_TOPLEVEL;
    surface.xdg_toplevel = &toplevel;
    surface.xdg_surface = &xdg;
    surface_commit(NULL, &resource); /* initial empty commit */
    assert(configures == 1 && !surface.mapped && surface.toplevel_committed);
    assert(configured_width == 1564 && configured_height == 720);
    surface_commit(NULL, &resource); /* metadata-only commit is not an unmap */
    assert(configures == 1);

    struct dmabuf_buffer gpu = {.width = 1564, .height = 720};
    struct wl_resource gpu_resource = {.object = {.id = DMA_BUFFER}, .data = &gpu};
    struct wl_shm_buffer shm = {.width = 1564, .height = 720};
    struct wl_resource shm_resource = {.object = {.id = SHM_BUFFER}, .data = &shm};
    for (unsigned cycle = 0; cycle < 120; cycle++) {
        xdg_toplevel_set_fullscreen(NULL, &toplevel, NULL);
        assert(configured_fullscreen);
        struct wl_resource *buffer = cycle & 1 ? &shm_resource : &gpu_resource;
        surface_attach(NULL, &resource, buffer, 0, 0);
        surface_commit(NULL, &resource);
        assert(surface.has_content && surface.mapped);
        unsigned configured_before_unmap = configures;
        unsigned released_before_unmap = gpu_releases;

        surface_attach(NULL, &resource, NULL, 0, 0);
        surface_commit(NULL, &resource);
        assert(!surface.has_content && !surface.mapped && !surface.dmabuf);
        assert(!surface.toplevel_committed && !surface.fullscreen);
        assert(configures == configured_before_unmap); /* no configure before remap is requested */
        if (!(cycle & 1)) assert(gpu_releases == released_before_unmap + 1);

        /* A libdecor client waits for this configure before it may submit the next GPU frame. */
        surface_commit(NULL, &resource);
        assert(configures == configured_before_unmap + 1 && surface.toplevel_committed);
        assert(!configured_fullscreen);
        surface_commit(NULL, &resource);
        assert(configures == configured_before_unmap + 1); /* no configure loop */
    }

    unsigned before = configures;
    xdg_toplevel_set_fullscreen(NULL, &toplevel, NULL);
    xdg_toplevel_set_fullscreen(NULL, &toplevel, NULL);
    assert(configures == before + 2 && configured_fullscreen); /* repeated requests still need a reply */
    xdg_toplevel_unset_fullscreen(NULL, &toplevel);
    xdg_toplevel_unset_fullscreen(NULL, &toplevel);
    assert(configures == before + 4 && !configured_fullscreen);

    struct surface child;
    struct wl_resource child_resource;
    init_surface(&child, &child_resource);
    child.role = ROLE_SUBSURFACE;
    child.parent = &surface;
    surface_attach(NULL, &child_resource, &gpu_resource, 0, 0);
    surface_commit(NULL, &child_resource);
    before = configures;
    surface_attach(NULL, &child_resource, NULL, 0, 0);
    surface_commit(NULL, &child_resource);
    assert(configures == before && !child.has_content); /* subsurfaces do not get xdg configure */
    assert(render_requests >= 480);
    return 0;
}
