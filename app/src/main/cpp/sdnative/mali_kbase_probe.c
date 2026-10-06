/*
 * Minimal read-only-ish probe for ARM mali_kbase (/dev/mali0).
 *
 * DroidDeck needs to know which Linux guest ABI a stock Mali phone exposes before choosing a
 * Vulkan ICD.  The Android system Vulkan driver already knows this information, but the glibc
 * guest cannot query it through bionic.  Kbase exposes a tiny public UAPI that is stable enough
 * for capability discovery: VERSION_CHECK and GET_GPUPROPS.  We only open the node, negotiate a
 * version on a throw-away fd, read properties, then close it; no queues/jobs are submitted.
 *
 * CSF kernels moved VERSION_CHECK to ioctl 52 (major 1.x); JM kernels keep it at ioctl 0
 * (major 11.x).  GET_GPUPROPS remains ioctl 3 in both families.
 */
#include <jni.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define KBASE_IOCTL_TYPE 0x80

struct kbase_ioctl_version_check {
    uint16_t major;
    uint16_t minor;
};

struct kbase_ioctl_get_gpuprops {
    uint64_t buffer;
    uint32_t size;
    uint32_t flags;
};

struct kbase_ioctl_set_flags {
    uint32_t create_flags;
};

#define KBASE_IOCTL_VERSION_CHECK_JM  _IOWR(KBASE_IOCTL_TYPE, 0, struct kbase_ioctl_version_check)
#define KBASE_IOCTL_SET_FLAGS         _IOW(KBASE_IOCTL_TYPE, 1, struct kbase_ioctl_set_flags)
#define KBASE_IOCTL_GET_GPUPROPS      _IOW(KBASE_IOCTL_TYPE, 3, struct kbase_ioctl_get_gpuprops)
#define KBASE_IOCTL_VERSION_CHECK_CSF _IOWR(KBASE_IOCTL_TYPE, 52, struct kbase_ioctl_version_check)

#define KBASE_GPUPROP_PRODUCT_ID         1u
#define KBASE_GPUPROP_VERSION_STATUS     2u
#define KBASE_GPUPROP_MINOR_REVISION     3u
#define KBASE_GPUPROP_MAJOR_REVISION     4u
#define KBASE_GPUPROP_RAW_SHADER_PRESENT 25u
#define KBASE_GPUPROP_RAW_GPU_ID         55u

/* Result layout consumed by MaliKbaseProbe.kt. */
enum {
    OUT_USABLE = 0,
    OUT_FRONTEND = 1,       /* 0 unknown, 1 JM, 2 CSF */
    OUT_UAPI_MAJOR = 2,
    OUT_UAPI_MINOR = 3,
    OUT_PRODUCT_ID = 4,
    OUT_VERSION_STATUS = 5,
    OUT_MAJOR_REVISION = 6,
    OUT_MINOR_REVISION = 7,
    OUT_SHADER_PRESENT = 8,
    OUT_ERRNO = 9,
    OUT_RAW_GPU_ID = 10,
    OUT_COUNT = 11,
};

static uint64_t read_le(const uint8_t *p, unsigned n) {
    uint64_t v = 0;
    for (unsigned i = 0; i < n; ++i) v |= ((uint64_t)p[i]) << (8u * i);
    return v;
}

static int version_check(int fd, int *frontend, uint16_t *major, uint16_t *minor) {
    struct kbase_ioctl_version_check v = {1, UINT16_MAX};
    if (ioctl(fd, KBASE_IOCTL_VERSION_CHECK_CSF, &v) == 0 && v.major == 1) {
        *frontend = 2;
        *major = v.major;
        *minor = v.minor;
        return 0;
    }

    v.major = 11;
    v.minor = UINT16_MAX;
    if (ioctl(fd, KBASE_IOCTL_VERSION_CHECK_JM, &v) == 0 && v.major == 11) {
        *frontend = 1;
        *major = v.major;
        *minor = v.minor;
        return 0;
    }
    return -1;
}

static int fill_gpuprops(int fd, uint64_t out[OUT_COUNT]) {
    /* 64 KiB is far above current property tables and avoids relying on the optional size query. */
    const uint32_t cap = 64u * 1024u;
    uint8_t *buf = (uint8_t *)calloc(1, cap);
    if (!buf) {
        errno = ENOMEM;
        return -1;
    }
    struct kbase_ioctl_get_gpuprops p = {(uint64_t)(uintptr_t)buf, cap, 0};
    int n = ioctl(fd, KBASE_IOCTL_GET_GPUPROPS, &p);
    if (n < 0 && (errno == EPERM || errno == EINVAL)) {
        /* Older JM releases gate normal ioctls until SET_FLAGS completes the one-shot setup. */
        struct kbase_ioctl_set_flags flags = {0};
        if (ioctl(fd, KBASE_IOCTL_SET_FLAGS, &flags) == 0) {
            memset(buf, 0, cap);
            n = ioctl(fd, KBASE_IOCTL_GET_GPUPROPS, &p);
        }
    }
    if (n < 0) {
        free(buf);
        return -1;
    }

    size_t len = n > 0 ? (size_t)n : (size_t)cap;
    if (len > cap) len = cap;
    size_t pos = 0;
    while (pos + 4 <= len) {
        uint32_t key;
        memcpy(&key, buf + pos, sizeof(key));
        if (key == 0) break;
        pos += 4;
        unsigned size_code = key & 3u;
        unsigned value_size = 1u << size_code;
        uint32_t prop = key >> 2;
        if (pos + value_size > len) break;
        uint64_t value = read_le(buf + pos, value_size);
        pos += value_size;
        switch (prop) {
            case KBASE_GPUPROP_PRODUCT_ID:         out[OUT_PRODUCT_ID] = value; break;
            case KBASE_GPUPROP_VERSION_STATUS:     out[OUT_VERSION_STATUS] = value; break;
            case KBASE_GPUPROP_MAJOR_REVISION:     out[OUT_MAJOR_REVISION] = value; break;
            case KBASE_GPUPROP_MINOR_REVISION:     out[OUT_MINOR_REVISION] = value; break;
            case KBASE_GPUPROP_RAW_SHADER_PRESENT: out[OUT_SHADER_PRESENT] = value; break;
            case KBASE_GPUPROP_RAW_GPU_ID:         out[OUT_RAW_GPU_ID] = value; break;
            default: break;
        }
    }
    free(buf);
    return 0;
}

JNIEXPORT jlongArray JNICALL
Java_com_droiddeck_launcher_gpu_MaliKbaseProbe_nativeProbe(JNIEnv *env, jclass clazz) {
    (void)clazz;
    uint64_t out[OUT_COUNT] = {0};
    int fd = open("/dev/mali0", O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        out[OUT_ERRNO] = (uint64_t)errno;
        goto done;
    }

    int frontend = 0;
    uint16_t major = 0, minor = 0;
    if (version_check(fd, &frontend, &major, &minor) != 0) {
        out[OUT_ERRNO] = (uint64_t)errno;
        close(fd);
        goto done;
    }

    out[OUT_USABLE] = 1;
    out[OUT_FRONTEND] = (uint64_t)frontend;
    out[OUT_UAPI_MAJOR] = major;
    out[OUT_UAPI_MINOR] = minor;

    /* A failed property read does not invalidate the node/version handshake. */
    int saved = 0;
    if (fill_gpuprops(fd, out) != 0) saved = errno;
    if (saved) out[OUT_ERRNO] = (uint64_t)saved;
    close(fd);

done:
    jlongArray arr = (*env)->NewLongArray(env, OUT_COUNT);
    if (!arr) return NULL;
    jlong tmp[OUT_COUNT];
    for (int i = 0; i < OUT_COUNT; ++i) tmp[i] = (jlong)out[i];
    (*env)->SetLongArrayRegion(env, arr, 0, OUT_COUNT, tmp);
    return arr;
}
