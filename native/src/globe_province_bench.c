#define WIN32_LEAN_AND_MEAN
#ifdef GP_BASELINE
#include "globe_province_baseline.h"
#else
#include "globe_province.h"
#endif
#include <stdio.h>

/* Isolated overhead comparison, not a game-frame benchmark. Native worker
 * mock reproduces the invisible-new/invisible-old no-record case. Every task
 * contains one province, with real map total 13414 and stable camera/planes.
 */
static void native_stub(GPContext *ctx,const int *range) {
    for(int id=range[0];id<range[1];id++) ((unsigned char *)ctx->flags->data)[id]|=4;
}
int main(void) {
    const int total=13414,iterations=200000;
    unsigned char map[0x78]={0},eu3[0x700]={0};
    void **provinces=calloc(total,8),**gfx=calloc(total,8);
    unsigned char *province_storage=calloc(total,0xc0),*gfx_storage=calloc(total,0x1770),*flags=calloc(total,1);
    GPUpdate *updates=calloc(total,sizeof(*updates));int *leaves=calloc(total,4);
    if(!provinces||!gfx||!province_storage||!gfx_storage||!flags||!updates||!leaves) return 2;
    for(int id=0;id<total;id++) {
        provinces[id]=province_storage+(size_t)id*0xc0;gfx[id]=gfx_storage+(size_t)id*0x1770;
        int bbox[4]={2800,1000,10,10};memcpy((unsigned char *)provinces[id]+0x88,bbox,16);
    }
    memcpy(map+0x20,&(void *){eu3},8);memcpy(map+0x68,&gfx,8);
    memcpy(map+0x70,&total,4);memcpy(map+0x74,&total,4);
    float planes[4][4]={{-1,0,0,-1000000},{1,0,0,-1000000},{0,0,-1,-1000000},{0,0,1,-1000000}};
    memcpy(eu3+0x1c8,planes,sizeof(planes));
    GPArray p={provinces,total,total,NULL},f={flags,total,total,NULL},u={updates,total,total,NULL},l={leaves,total,total,NULL};
    volatile LONG uc=0,lc=0;GPStats stats={0};GPContext ctx={map,&p,&f,&uc,&u,&lc,&l};
    GCamera camera={{2800,2000,1000},{0,-1,0}};
    for(int id=1;id<total;id++) {
        int range[3]={id,id+1,1};flags[id]=0;uc=lc=0;
        if(gp_expand_worker(native_stub,&ctx,range,camera,&stats)!=1 || flags[id]!=6) return 3;
    }
#ifndef GP_BASELINE
    GPThreadCache *cache=gp_thread_cache();
    uint64_t probes=cache->probes,geometry=cache->geometry_evaluations,grows=cache->buffer_grows;
#endif
    LARGE_INTEGER start,end,freq;QueryPerformanceFrequency(&freq);QueryPerformanceCounter(&start);
    for(int i=0;i<iterations;i++) {
        int id=1+i%(total-1),range[3]={id,id+1,1};flags[id]=0;uc=lc=0;
        if(gp_expand_worker(native_stub,&ctx,range,camera,&stats)!=1 || flags[id]!=6 || uc!=1 || lc!=0) return 4;
    }
    QueryPerformanceCounter(&end);
    double seconds=(double)(end.QuadPart-start.QuadPart)/freq.QuadPart;
    printf("%s: %d one-province tasks, %.6f seconds, %.3f us/task, %.0f tasks/sec\n",
#ifdef GP_BASELINE
        "baseline",
#else
        "optimized",
#endif
        iterations,seconds,seconds*1000000/iterations,iterations/seconds);
#ifndef GP_BASELINE
    printf("warm workload: probes=%llu, geometry_evaluations=%llu, buffer_grows=%llu, geometry_hits=%llu\n",
        (unsigned long long)(cache->probes-probes),(unsigned long long)(cache->geometry_evaluations-geometry),
        (unsigned long long)(cache->buffer_grows-grows),(unsigned long long)cache->geometry_hits);
    if(cache->probes!=probes || cache->geometry_evaluations!=geometry || cache->buffer_grows!=grows) return 5;
#endif
    return stats.fallback||stats.merge_refused?6:0;
}
