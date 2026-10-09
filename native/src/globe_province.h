#ifndef HOI4_GLOBE_PROVINCE_H
#define HOI4_GLOBE_PROVINCE_H

/* Verified for hoi4.exe SHA256
 * 7dc947be34970da1e1c787bcddbe7f62b610ff258aebf8f06aa8b348f3a031d5.
 * This header installs no hooks and never changes a camera or gameplay state.
 * The caller supplies the unmodified native worker and a separately validated
 * primary camera. Native task ranges have exclusive ownership of province IDs;
 * all workers finish before the caller consumes flags and output records.
 */
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include "globe_geometry.h"

#define GP_WORKER_RVA 0xb51740u
static const unsigned gp_call_rvas[4] = {0xb5bcb3u,0xb4ef9au,0xb4efefu,0xb5c659u};
static const unsigned char gp_original_calls[4][5] = {
    {0xe8,0x88,0x5a,0xff,0xff}, {0xe8,0xa1,0x27,0x00,0x00},
    {0xe8,0x4c,0x27,0x00,0x00}, {0xe8,0xe2,0x50,0xff,0xff}};
static const unsigned char gp_worker_prefix[17] = {
    0x48,0x8b,0xc4,0x48,0x89,0x50,0x10,0x56,0x41,0x56,
    0x48,0x81,0xec,0xb8,0x00,0x00,0x00};

typedef struct GPArray {
    void *data;
    int capacity, count;
    void *allocator;
} GPArray;
typedef struct GPUpdate { int province, padding; void *camera; } GPUpdate;
typedef struct GPContext {
    void *map;
    GPArray *provinces, *flags;
    volatile LONG *update_count;
    GPArray *updates;
    volatile LONG *leave_count;
    GPArray *leaves;
} GPContext;
typedef void (*GPWorkerFn)(GPContext *, const int *);
typedef struct GPStats {
    volatile LONG calls, expanded, fallback, merge_refused;
} GPStats;
_Static_assert(sizeof(void *)==8, "64-bit game ABI required");
_Static_assert(sizeof(LONG)==4 && sizeof(GPArray)==24, "Native array ABI");
_Static_assert(sizeof(GPContext)==56 && offsetof(GPUpdate,camera)==8 &&
               sizeof(GPUpdate)==16, "Native worker/record ABI");

static inline int gp_readable(const void *pointer, size_t size, int writable) {
    uintptr_t current=(uintptr_t)pointer, end=current+size;
    if(!pointer || end<current) return 0;
    while(current<end) {
        MEMORY_BASIC_INFORMATION info;
        if(!VirtualQuery((const void *)current,&info,sizeof(info)) ||
           info.State!=MEM_COMMIT || (info.Protect&(PAGE_GUARD|PAGE_NOACCESS))) return 0;
        DWORD protection=info.Protect&0xff;
        if(protection!=PAGE_READONLY && protection!=PAGE_READWRITE &&
           protection!=PAGE_WRITECOPY && protection!=PAGE_EXECUTE_READ &&
           protection!=PAGE_EXECUTE_READWRITE && protection!=PAGE_EXECUTE_WRITECOPY) return 0;
        if(writable && protection!=PAGE_READWRITE && protection!=PAGE_WRITECOPY &&
           protection!=PAGE_EXECUTE_READWRITE && protection!=PAGE_EXECUTE_WRITECOPY) return 0;
        uintptr_t next=(uintptr_t)info.BaseAddress+info.RegionSize;
        if(next<=current) return 0;
        current=next;
    }
    return 1;
}
static inline int gp_i32(const void *p) { int v; memcpy(&v,p,4); return v; }
static inline void *gp_pointer(const void *p) { void *v; memcpy(&v,p,sizeof(v)); return v; }

/* A latitude/longitude AABB is enclosed by a spherical angular cap. The cap
 * radius uses a meridian-plus-longitude path bound, including seam-spanning
 * provinces. It is conservative: no centroid-only rejection is used.
 * A radial interval enclosing the native worker's 0..70 height bound produces
 * a Euclidean sphere for four side-plane tests. Native near/far planes are not
 * used. Elevated markers may reach over the horizon, so the opaque-body test
 * includes the maximum-height tangent angle as well as the camera tangent.
 */
static inline int gp_globe_visible(int east, int north, int width, int height,
                                    GCamera camera, const float planes[4][4]) {
    if(width<0 || height<0 || width>5632 || height>2048) return 0;
    double top=(double)north+height;
    if(top<0.0 || north>2048) return 0;
    float z0=g_clamp((float)north,0.0f,G_MAP_HEIGHT);
    float z1=g_clamp((float)top,0.0f,G_MAP_HEIGHT), zc=0.5f*(z0+z1);
    float latitude=g_latitude(zc);
    float latitude_radius=g_max(fabsf(latitude-g_latitude(z0)),fabsf(g_latitude(z1)-latitude));
    float angle=g_min(G_PI,latitude_radius+0.5f*(float)width/g_radius()+0.0005f);
    GVec3 normal=g_surface_normal(g_vec((float)east+0.5f*width,G_SEA_LEVEL,zc),camera);
    float radius=g_radius(), high=radius+(70.0f-G_SEA_LEVEL)*g_relief_scale(camera);
    GVec3 effective=g_sub(g_camera_effective(camera),g_center(camera));
    float distance=g_length(effective), body=radius-1.0f;
    if(distance>body && angle<G_PI) {
        float center_angle=acosf(g_clamp(g_dot(normal,g_scale(effective,1.0f/distance)),-1.0f,1.0f));
        float visible_angle=acosf(g_clamp(body/distance,0.0f,1.0f))+
                            acosf(g_clamp(body/high,0.0f,1.0f));
        if(center_angle-angle>visible_angle+0.001f) return 0;
    }
    float low=radius-G_SEA_LEVEL, middle=0.5f*(low+high);
    float enclosing=2.0f*middle*sinf(0.5f*angle)+0.5f*(high-low)+2.0f;
    GVec3 center=g_add(g_center(camera),g_scale(normal,middle));
    center=g_projected_sphere_world(center,camera);
    for(int i=0;i<4;i++) {
        GVec3 p=g_vec(planes[i][0],planes[i][1],planes[i][2]);
        float signed_distance=g_dot(p,center)+planes[i][3];
        if(signed_distance>g_length(p)*enclosing+0.001f) return 0;
    }
    return 1;
}

/* Counts are entries, not bytes. Bounded CAS never advances a count beyond
 * available storage, including when another native task appends concurrently.
 * Native workers produce at most one update and one leave entry per exclusive
 * ID, and the caller allocates at least one entry per province.
 */
static inline int gp_reserve(volatile LONG *counter, int count, int capacity) {
    LONG observed=InterlockedCompareExchange(counter,0,0);
    for(;;) {
        if(observed<0 || count<0 || observed>capacity-count) return -1;
        LONG previous=InterlockedCompareExchange(counter,observed+count,observed);
        if(previous==observed) return (int)observed;
        observed=previous;
    }
}

/* Reused only by one native worker thread at a time. Verified call sites supply
 * engine-owned live objects until their task group has joined. Cached committed
 * regions are a bounds check for those live inputs, not a general memory-reader
 * API: native object lifetime remains the native caller's responsibility.
 */
typedef struct GPRegion { uintptr_t begin,end; int writable; } GPRegion;
typedef struct GPNodeCache {
    void *province,*gfx;
    int bbox[4];
    uint64_t camera_epoch;
    unsigned char visible,shape_valid,bbox_known;
    float east_center,north_center,sin_lat,cos_lat,angle,sin_half_angle;
} GPNodeCache;
typedef struct GPPreparedCamera {
    GCamera original;
    float planes[4][4],plane_lengths[4];
    GVec3 center,pullback,effective_direction;
    float focus_x,sin_focus,cos_focus,distance,visible_angle,middle,half_thickness;
} GPPreparedCamera;
typedef struct GPThreadCache {
    unsigned char *flags;
    GPUpdate *updates;
    int *leaves;
    void **chosen;
    GPNodeCache *nodes;
    int total_capacity,range_capacity,busy;
    void *scene_map,*scene_provinces,*scene_gfx,*scene_camera;
    int scene_total,scene_capacity;
    GPRegion regions[32];
    int region_count,region_cursor;
    uint64_t camera_epoch,probes,geometry_evaluations,geometry_hits,buffer_grows;
    GPPreparedCamera camera;
} GPThreadCache;
static DWORD gp_fls_index=FLS_OUT_OF_INDEXES;
static volatile LONG gp_fls_state;
static void NTAPI gp_destroy_thread(void *pointer) {
    GPThreadCache *cache=(GPThreadCache *)pointer;
    if(!cache) return;
    free(cache->flags);free(cache->updates);free(cache->leaves);free(cache->chosen);free(cache->nodes);free(cache);
}
static inline GPThreadCache *gp_thread_cache(void) {
    LONG ready=gp_fls_state;
    if(ready!=2) {
        if(InterlockedCompareExchange(&gp_fls_state,1,0)==0) {
            gp_fls_index=FlsAlloc(gp_destroy_thread);
            InterlockedExchange(&gp_fls_state,2);
        } else while(InterlockedCompareExchange(&gp_fls_state,0,0)!=2) Sleep(0);
    }
    if(gp_fls_index==FLS_OUT_OF_INDEXES) return NULL;
    GPThreadCache *cache=(GPThreadCache *)FlsGetValue(gp_fls_index);
    if(!cache) {
        cache=(GPThreadCache *)calloc(1,sizeof(*cache));
        if(!cache) return NULL;
        if(!FlsSetValue(gp_fls_index,cache)) { free(cache);return NULL; }
    }
    return cache;
}
static inline int gp_probe(GPThreadCache *cache,const void *pointer,size_t size,int writable) {
    uintptr_t current=(uintptr_t)pointer,end=current+size;
    if(!pointer || end<current) return 0;
    while(current<end) {
        uintptr_t next=0;
        for(int i=0;i<cache->region_count;i++) {
            GPRegion r=cache->regions[i];
            if(current>=r.begin && current<r.end && (!writable || r.writable)) { next=r.end;break; }
        }
        if(!next) {
            MEMORY_BASIC_INFORMATION info;cache->probes++;
            if(!VirtualQuery((const void *)current,&info,sizeof(info)) || info.State!=MEM_COMMIT ||
               (info.Protect&(PAGE_GUARD|PAGE_NOACCESS))) return 0;
            DWORD protection=info.Protect&0xff;
            int can_write=protection==PAGE_READWRITE || protection==PAGE_WRITECOPY ||
                          protection==PAGE_EXECUTE_READWRITE || protection==PAGE_EXECUTE_WRITECOPY;
            int can_read=can_write || protection==PAGE_READONLY || protection==PAGE_EXECUTE_READ;
            if(!can_read || (writable && !can_write)) return 0;
            next=(uintptr_t)info.BaseAddress+info.RegionSize;
            if(next<=current) return 0;
            int slot=cache->region_count<32?cache->region_count++:cache->region_cursor++%32;
            cache->regions[slot]=(GPRegion){(uintptr_t)info.BaseAddress,next,can_write};
        }
        if(next<=current) return 0;
        current=next;
    }
    return 1;
}
static inline int gp_resize_cache(GPThreadCache *cache,int total,int length) {
    if(total>cache->total_capacity) {
        unsigned char *flags=(unsigned char *)malloc((size_t)total);
        GPNodeCache *nodes=(GPNodeCache *)calloc((size_t)total,sizeof(*nodes));
        if(!flags || !nodes) { free(flags);free(nodes);return 0; }
        free(cache->flags);free(cache->nodes);cache->flags=flags;cache->nodes=nodes;cache->total_capacity=total;cache->buffer_grows++;
        cache->scene_map=NULL;
    }
    if(length>cache->range_capacity) {
        int capacity=length<64?64:length;
        GPUpdate *updates=(GPUpdate *)malloc((size_t)capacity*sizeof(*updates));
        int *leaves=(int *)malloc((size_t)capacity*sizeof(*leaves));
        void **chosen=(void **)malloc((size_t)capacity*sizeof(*chosen));
        if(!updates || !leaves || !chosen) { free(updates);free(leaves);free(chosen);return 0; }
        free(cache->updates);free(cache->leaves);free(cache->chosen);
        cache->updates=updates;cache->leaves=leaves;cache->chosen=chosen;cache->range_capacity=capacity;cache->buffer_grows++;
    }
    return 1;
}
static inline void gp_prepare_camera(GPPreparedCamera *out,GCamera camera,const float planes[4][4]) {
    out->original=camera;memcpy(out->planes,planes,sizeof(out->planes));
    GVec3 focus=g_focus(camera);
    out->focus_x=focus.x;
    float focus_lat=g_latitude(focus.z);
    out->sin_focus=sinf(focus_lat);out->cos_focus=cosf(focus_lat);
    out->center=g_center(camera);
    out->pullback=g_scale(g_forward(camera),g_view_pullback(camera));
    GVec3 effective=g_sub(g_camera_effective(camera),out->center);
    out->distance=g_length(effective);out->effective_direction=g_scale(effective,1.0f/g_max(0.00001f,out->distance));
    float radius=g_radius(),body=radius-1.0f,high=radius+(70.0f-G_SEA_LEVEL)*g_relief_scale(camera),low=radius-G_SEA_LEVEL;
    out->middle=0.5f*(low+high);out->half_thickness=0.5f*(high-low);
    out->visible_angle=out->distance>body?acosf(g_clamp(body/out->distance,0,1))+acosf(g_clamp(body/high,0,1)):G_PI;
    for(int i=0;i<4;i++) out->plane_lengths[i]=g_length(g_vec(planes[i][0],planes[i][1],planes[i][2]));
}
static inline void gp_prepare_shape(GPNodeCache *node,const int bbox[4]) {
    memcpy(node->bbox,bbox,16);node->camera_epoch=0;node->bbox_known=1;
    int east=bbox[0],north=bbox[1],width=bbox[2],height=bbox[3];
    double top=(double)north+height;
    node->shape_valid=width>=0 && height>=0 && width<=5632 && height<=2048 && top>=0 && north<=2048;
    if(!node->shape_valid) return;
    float z0=g_clamp((float)north,0,G_MAP_HEIGHT),z1=g_clamp((float)top,0,G_MAP_HEIGHT);
    node->east_center=(float)east+0.5f*width;node->north_center=0.5f*(z0+z1);
    float latitude=g_latitude(node->north_center);
    node->sin_lat=sinf(latitude);node->cos_lat=cosf(latitude);
    float delta=g_max(fabsf(latitude-g_latitude(z0)),fabsf(g_latitude(z1)-latitude));
    node->angle=g_min(G_PI,delta+0.5f*(float)width/g_radius()+0.0005f);
    node->sin_half_angle=sinf(0.5f*node->angle);
}
static inline int gp_prepared_visible(const GPNodeCache *node,const GPPreparedCamera *camera) {
    if(!node->shape_valid) return 0;
    float longitude=(node->east_center-camera->focus_x)/g_radius();
    float sl=node->sin_lat,cl=node->cos_lat,cd=cosf(longitude);
    GVec3 normal=g_normalize(g_vec(cl*sinf(longitude),cl*cd*camera->cos_focus+sl*camera->sin_focus,
                                  sl*camera->cos_focus-cl*cd*camera->sin_focus));
    if(camera->distance>g_radius()-1 && node->angle<G_PI) {
        float center_angle=acosf(g_clamp(g_dot(normal,camera->effective_direction),-1,1));
        if(center_angle-node->angle>camera->visible_angle+0.001f) return 0;
    }
    float enclosing=2*camera->middle*node->sin_half_angle+camera->half_thickness+2;
    GVec3 center=g_add(g_add(camera->center,g_scale(normal,camera->middle)),camera->pullback);
    for(int i=0;i<4;i++) {
        const float *p=camera->planes[i];
        if(p[0]*center.x+p[1]*center.y+p[2]*center.z+p[3]>camera->plane_lengths[i]*enclosing+0.001f) return 0;
    }
    return 1;
}

/* Return 1 when expanded processing was used, 0 after an untouched native
 * fallback, -1 for a refused bounded merge. On -1 the caller must NOT rerun the
 * original worker: a previous output reservation may already be committed.
 * Each reservation is filled immediately, so refused merges leave no holes.
 */
static inline int gp_expand_worker(GPWorkerFn original, GPContext *context,
                                    const int *range, GCamera camera, GPStats *stats) {
    if(stats) InterlockedIncrement(&stats->calls);
    GPThreadCache *cache=gp_thread_cache();
    if(!cache || cache->busy) {
        if(stats) InterlockedIncrement(&stats->fallback);
        if(original) original(context,range);
        return 0;
    }
    cache->busy=1;
    int valid=original && gp_probe(cache,context,sizeof(*context),0) && gp_probe(cache,range,8,0);
    int first=valid?range[0]:0, end=valid?range[1]:0, total=0;
    GPArray descriptors[4];
    void **province_data=NULL, **gfx_data=NULL;
    unsigned char *shared_flags=NULL, *eu3=NULL;
    float planes[4][4];
    if(valid) {
        valid=gp_probe(cache,context->map,0x78,0) && gp_probe(cache,context->provinces,sizeof(GPArray),0) &&
              gp_probe(cache,context->flags,sizeof(GPArray),0) && gp_probe(cache,context->updates,sizeof(GPArray),0) &&
              gp_probe(cache,context->leaves,sizeof(GPArray),0) &&
              gp_probe(cache,(const void *)context->update_count,4,1) &&
              gp_probe(cache,(const void *)context->leave_count,4,1) &&
              (((uintptr_t)context->update_count| (uintptr_t)context->leave_count)&3)==0;
    }
    if(valid) {
        descriptors[0]=*context->provinces; descriptors[1]=*context->flags;
        descriptors[2]=*context->updates; descriptors[3]=*context->leaves;
        total=gp_i32((unsigned char *)context->map+0x74);
        valid=total>1 && total<=65536 && first>=1 && end>=first && end<=total &&
              gp_i32((unsigned char *)context->map+0x70)>=total;
        for(int i=0;i<4 && valid;i++) valid=descriptors[i].count>=total &&
            descriptors[i].capacity>=descriptors[i].count && descriptors[i].capacity<=1048576;
        if(valid) {
            province_data=(void **)descriptors[0].data;
            shared_flags=(unsigned char *)descriptors[1].data;
            gfx_data=(void **)gp_pointer((unsigned char *)context->map+0x68);
            eu3=(unsigned char *)gp_pointer((unsigned char *)context->map+0x20);
            int scene_changed=cache->scene_map!=context->map || cache->scene_provinces!=province_data ||
                cache->scene_gfx!=gfx_data || cache->scene_camera!=eu3 || cache->scene_total!=total ||
                cache->scene_capacity!=gp_i32((unsigned char *)context->map+0x70);
            if(scene_changed) { cache->region_count=0;cache->region_cursor=0; }
            valid=gp_probe(cache,province_data,(size_t)total*8,0) && gp_probe(cache,gfx_data,(size_t)total*8,0) &&
                  gp_probe(cache,shared_flags,(size_t)total,1) &&
                  gp_probe(cache,descriptors[2].data,(size_t)descriptors[2].capacity*16,1) &&
                  gp_probe(cache,descriptors[3].data,(size_t)descriptors[3].capacity*4,1) &&
                  gp_probe(cache,eu3,0x6f9,0) && gp_resize_cache(cache,total,end-first);
            if(valid && (scene_changed || cache->scene_map!=context->map)) {
                memset(cache->nodes,0,(size_t)total*sizeof(*cache->nodes));
                cache->scene_map=context->map;cache->scene_provinces=province_data;cache->scene_gfx=gfx_data;
                cache->scene_camera=eu3;cache->scene_total=total;cache->scene_capacity=gp_i32((unsigned char *)context->map+0x70);
            }
        }
    }
    if(valid) {
        memcpy(planes,eu3+0x1c8,sizeof(planes));
        for(int i=0;i<4 && valid;i++) {
            for(int j=0;j<4;j++) if(!isfinite(planes[i][j])) valid=0;
            if(g_length(g_vec(planes[i][0],planes[i][1],planes[i][2]))<0.00001f) valid=0;
        }
        LONG updates=InterlockedCompareExchange(context->update_count,0,0);
        LONG leaves=InterlockedCompareExchange(context->leave_count,0,0);
        valid=valid && updates>=0 && updates<=total && leaves>=0 && leaves<=total;
        for(int id=first;id<end && valid;id++) {
            GPNodeCache *node=&cache->nodes[id];
            valid=province_data[id] && gfx_data[id] && (shared_flags[id]&0x1e)==0;
            if(valid && node->province!=province_data[id]) {
                valid=gp_probe(cache,(unsigned char *)province_data[id]+0x88,0x38,0);
                if(valid) { node->province=province_data[id];node->bbox_known=0;node->camera_epoch=0; }
            }
            if(valid && node->gfx!=gfx_data[id]) {
                valid=gp_probe(cache,(unsigned char *)gfx_data[id]+0x1761,1,0);
                if(valid) node->gfx=gfx_data[id];
            }
        }
    }
    if(!valid || first==end) {
        cache->busy=0;
        if(stats) InterlockedIncrement(&stats->fallback);
        if(original) original(context,range);
        return 0;
    }
    int length=end-first;
    if(cache->camera_epoch==0 || memcmp(&cache->camera.original,&camera,sizeof(camera)) ||
        memcmp(cache->camera.planes,planes,sizeof(planes))) {
        gp_prepare_camera(&cache->camera,camera,planes);
        cache->camera_epoch++;
        if(cache->camera_epoch==0) {
            for(int id=0;id<total;id++) cache->nodes[id].camera_epoch=0;
            cache->camera_epoch=1;
        }
    }
    unsigned char *flags=cache->flags;
    GPUpdate *updates=cache->updates;
    int *leaves=cache->leaves;
    void **chosen=cache->chosen;
    memset(chosen,0,(size_t)length*sizeof(*chosen));
    memcpy(flags+first,shared_flags+first,(size_t)length);
    GPArray flag_array={flags,total,total,NULL}, update_array={updates,length,length,NULL}, leave_array={leaves,length,length,NULL};
    volatile LONG update_count=0,leave_count=0;
    GPContext private_context=*context;
    private_context.flags=&flag_array;private_context.update_count=&update_count;private_context.updates=&update_array;
    private_context.leave_count=&leave_count;private_context.leaves=&leave_array;
    original(&private_context,range);
    valid=update_count>=0 && update_count<=length && leave_count>=0 && leave_count<=length;
    int previous=first-1;
    for(int i=0;i<update_count && valid;i++) {
        int id=updates[i].province; void *selected=updates[i].camera;
        valid=id>previous && id>=first && id<end &&
              (selected==eu3+0x10 || selected==eu3+0x230 || selected==eu3+0x450);
        if(valid) chosen[id-first]=selected;
        previous=id;
    }
    previous=first-1;
    for(int i=0;i<leave_count && valid;i++) {
        valid=leaves[i]>previous && leaves[i]>=first && leaves[i]<end;
        previous=leaves[i];
    }
    int leave_index=0;
    for(int id=first;id<end && valid;id++) {
        int old_visible=*((unsigned char *)gfx_data[id]+0x1761)&2;
        int visible=flags[id]&2;
        int should_update=old_visible || visible;
        valid=(chosen[id-first]!=NULL)==(should_update!=0);
        if(old_visible && !visible) {
            valid=valid && leave_index<leave_count && leaves[leave_index]==id;
            leave_index++;
        }
    }
    valid=valid && leave_index==leave_count;
    if(!valid) {
        cache->busy=0;
        if(stats) InterlockedIncrement(&stats->fallback);
        original(context,range);return 0;
    }
    int final_updates=0,final_leaves=0,expanded=0;
    for(int id=first;id<end;id++) {
        int old_visible=*((unsigned char *)gfx_data[id]+0x1761)&2;
        int visible=flags[id]&2;
        unsigned char *province=(unsigned char *)province_data[id];
        GPNodeCache *node=&cache->nodes[id];
        if(!visible) {
            int bbox[4];memcpy(bbox,province+0x88,sizeof(bbox));
            if(!node->bbox_known || memcmp(node->bbox,bbox,sizeof(bbox))) gp_prepare_shape(node,bbox);
            if(node->camera_epoch!=cache->camera_epoch) {
                node->visible=(unsigned char)gp_prepared_visible(node,&cache->camera);
                node->camera_epoch=cache->camera_epoch;cache->geometry_evaluations++;
            } else cache->geometry_hits++;
        }
        if(!visible && node->visible) {
            flags[id]=(unsigned char)((flags[id]&~0x1c)|2|4);
            chosen[id-first]=eu3+0x10;visible=2;expanded++;
        }
        if(old_visible || visible) {
            updates[final_updates++]=(GPUpdate){id,0,chosen[id-first]?chosen[id-first]:eu3+0x10};
        }
        if(old_visible && !visible) leaves[final_leaves++]=id;
    }
    int offset=gp_reserve(context->update_count,final_updates,descriptors[2].capacity);
    int result=1;
    if(offset<0) result=-1;
    else {
        memcpy((GPUpdate *)descriptors[2].data+offset,updates,(size_t)final_updates*sizeof(*updates));
        int leave_offset=gp_reserve(context->leave_count,final_leaves,descriptors[3].capacity);
        if(leave_offset<0) result=-1;
        else memcpy((int *)descriptors[3].data+leave_offset,leaves,(size_t)final_leaves*4);
        memcpy(shared_flags+first,flags+first,(size_t)length);
    }
    if(stats) {
        InterlockedExchangeAdd(&stats->expanded,expanded);
        if(result<0) InterlockedIncrement(&stats->merge_refused);
    }
    cache->busy=0;
    return result;
}
#endif
