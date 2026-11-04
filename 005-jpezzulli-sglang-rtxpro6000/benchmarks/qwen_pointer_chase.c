/* Deterministic dependent pointer-chase over a randomized single cycle.
 * Reports average dependent read latency; *not* a physical DRAM specification.
 */
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <time.h>
#include <errno.h>
static double seconds(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC_RAW, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}
static uint64_t state = UINT64_C(0x9e3779b97f4a7c15);
static uint32_t random32(void) {
    state ^= state >> 12; state ^= state << 25; state ^= state >> 27;
    return (uint32_t)((state * UINT64_C(2685821657736338717)) >> 32);
}
int main(int argc, char **argv) {
    long mib = argc > 1 ? strtol(argv[1], NULL, 10) : 64;
    long steps_m = argc > 2 ? strtol(argv[2], NULL, 10) : 2;
    if (mib < 1 || mib > 512 || steps_m < 1 || steps_m > 20) {
        fprintf(stderr, "usage: ptr_chase [working_set_mib:1..512] [steps_million:1..20]\n");
        return 2;
    }
    const size_t n = (size_t)mib * 1024 * 1024 / sizeof(uint32_t);
    uint32_t *next = NULL, *order = NULL;
    if (posix_memalign((void **)&next, 64, n * sizeof(uint32_t)) ||
        posix_memalign((void **)&order, 64, n * sizeof(uint32_t))) {
        fprintf(stderr, "Memory allocation failed\n"); free(next); free(order);
        return 3;
    }
    for (size_t i=0; i<n; i++) order[i] = (uint32_t)i;
    for (size_t i=n-1; i>0; i--) {
        size_t j = (size_t)random32() % (i+1);
        uint32_t temp=order[i]; order[i]=order[j]; order[j]=temp;
    }
    for (size_t i=0; i+1<n; i++) next[order[i]]=order[i+1];
    next[order[n-1]]=order[0];
    uint32_t pos = order[0];
    free(order);
    for (size_t i=0; i<200000; i++) pos=next[pos];
    size_t steps = (size_t)steps_m * 1000000;
    double start=seconds();
    for (size_t i=0; i<steps; i++) pos=next[pos];
    double elapsed=seconds()-start;
    printf("{\"working_set_mib\":%ld,\"steps\":%zu,\"elapsed_s\":%.7f,\"ns_per_access\":%.3f,\"checksum\":%u}\n",
        mib, steps, elapsed, elapsed*1e9/(double)steps, pos);
    free(next);
    return 0;
}
