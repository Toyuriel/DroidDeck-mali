/* Compile the actual backend, keeping only the tested functions at link time. No GPU needed. */
#include "../../../app/src/main/cpp/waylandcomp/src/vk_present.c"
#include <assert.h>

static unsigned created, destroyed, pending[128], fail_create, present_calls;
static VkResult submit_error;
static uint32_t expected_image;
static VkImageMemoryBarrier recorded[16];
static unsigned barrier_count;

static VKAPI_ATTR VkResult VKAPI_CALL make_sem(VkDevice dev, const VkSemaphoreCreateInfo *ci,
                                               const VkAllocationCallbacks *alloc, VkSemaphore *out) {
    if (fail_create && created + 1 == fail_create) return VK_ERROR_OUT_OF_HOST_MEMORY;
    *out = (VkSemaphore)(uintptr_t)++created;
    return VK_SUCCESS;
}
static VKAPI_ATTR void VKAPI_CALL drop_sem(VkDevice dev, VkSemaphore sem, const VkAllocationCallbacks *alloc) {
    assert(sem && !pending[(uintptr_t)sem]);
    destroyed++;
}
static VKAPI_ATTR VkResult VKAPI_CALL submit(VkQueue q, uint32_t n, const VkSubmitInfo *si, VkFence fence) {
    if (submit_error) return submit_error;
    assert(n == 1 && si->signalSemaphoreCount == 1);
    uintptr_t sem = (uintptr_t)*si->pSignalSemaphores;
    /* A submit fence may signal while the previous present still owns its semaphore. */
    assert(sem && !pending[sem]);
    pending[sem] = 1;
    return VK_SUCCESS;
}
static VKAPI_ATTR VkResult VKAPI_CALL present(VkQueue q, const VkPresentInfoKHR *pi) {
    assert(*pi->pImageIndices == expected_image);
    assert(*pi->pWaitSemaphores == g_present_done[expected_image]);
    assert(pending[(uintptr_t)*pi->pWaitSemaphores]);
    present_calls++;
    /* Deliberately leave the wait pending until that image is acquired again. */
    return VK_SUCCESS;
}
static VKAPI_ATTR void VKAPI_CALL barrier(VkCommandBuffer cmd, VkPipelineStageFlags src,
                                         VkPipelineStageFlags dst, VkDependencyFlags flags,
                                         uint32_t nm, const VkMemoryBarrier *mb, uint32_t nb,
                                         const VkBufferMemoryBarrier *bb, uint32_t ni,
                                         const VkImageMemoryBarrier *ib) {
    assert(src & VK_PIPELINE_STAGE_ALL_COMMANDS_BIT);
    assert(ni == 1 && barrier_count < 16);
    recorded[barrier_count++] = *ib;
}
struct vk_api g_vk = {
    .CreateSemaphore = make_sem, .DestroySemaphore = drop_sem,
    .QueueSubmit = submit, .QueuePresentKHR = present, .CmdPipelineBarrier = barrier,
};

int main(void) {
    g_nimg = 6;
    assert(init_present_sync() == 0);
    /* Six Android buffers, one frame slot: no semaphore may be reused while the display owns it.
     * Include generated-frame slots and a non-sequential acquire order. */
    const uint32_t order[] = {4, 1, 5, 0, 3, 2, 4, 0, 5, 1};
    for (unsigned i = 0; i < sizeof(order) / sizeof(order[0]); i++) {
        expected_image = order[i];
        pending[(uintptr_t)g_present_done[expected_image]] = 0; /* image acquisition completed */
        VkResult qr;
        assert(submit_and_present(i % MAX_PRESENTS, expected_image, VK_NULL_HANDLE, &qr) == VK_SUCCESS);
        assert(qr == VK_SUCCESS);
    }
    assert(present_calls == 10);
    submit_error = VK_ERROR_DEVICE_LOST;
    VkResult qr;
    assert(submit_and_present(0, 0, VK_NULL_HANDLE, &qr) == VK_ERROR_DEVICE_LOST);
    assert(qr == VK_ERROR_DEVICE_LOST && present_calls == 10);
    memset(pending, 0, sizeof(pending));
    destroy_present_sync();
    assert(!g_present_done && destroyed == 6);
    g_nimg = 3; /* resize/rebuild changes the actual image count */
    fail_create = created + 3;
    assert(init_present_sync() == -1 && !g_present_done && destroyed == 8);
    fail_create = 0;
    assert(init_present_sync() == 0);
    destroy_present_sync();
    assert(created == destroyed);

    g_qfam = 2;
    struct vkp_image a = {.image = (VkImage)(uintptr_t)20, .dmabuf = 1};
    struct vkp_image b = {.image = (VkImage)(uintptr_t)21, .dmabuf = 1};
    struct vkp_image shm = {.image = (VkImage)(uintptr_t)22};
    for (unsigned frame = 0; frame < 120; frame++) {
        VkImageMemoryBarrier take = dmabuf_read_barrier(&a, 1);
        assert(take.oldLayout == VK_IMAGE_LAYOUT_GENERAL); /* valid producer pixels must survive */
        assert(take.newLayout == VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
        assert(take.srcQueueFamilyIndex == VK_QUEUE_FAMILY_FOREIGN_EXT && take.dstQueueFamilyIndex == g_qfam);
        barrier_count = 0;
        struct vkp_draw draws[] = {{.img = &a}, {.img = &shm}, {.img = &a}, {.img = NULL}, {.img = &b}};
        record_draws_release(VK_NULL_HANDLE, draws, 5);
        assert(barrier_count == 2); /* distinct shared images only; no duplicate ownership release */
        for (unsigned j = 0; j < barrier_count; j++) {
            assert(recorded[j].oldLayout == VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
            assert(recorded[j].newLayout == VK_IMAGE_LAYOUT_GENERAL);
            assert(recorded[j].srcQueueFamilyIndex == g_qfam);
            assert(recorded[j].dstQueueFamilyIndex == VK_QUEUE_FAMILY_FOREIGN_EXT);
            assert(recorded[j].srcAccessMask & VK_ACCESS_MEMORY_READ_BIT);
        }
    }
    return 0;
}
