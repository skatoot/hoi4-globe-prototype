#define WIN32_LEAN_AND_MEAN
#include "globe_province.h"
#include <stdio.h>

typedef struct Fixture {
    unsigned char map[0x78], eu3[0x700];
    void **provinces, **gfx;
    unsigned char *flags, *native_visible, *views;
    GPUpdate *updates;
    int *leaves, total;
    volatile LONG update_count,leave_count,mock_calls;
    GPArray province_desc,flags_desc,update_desc,leave_desc;
    GPContext context;
} Fixture;
static int failures;
#define CHECK(condition) do { if(!(condition)) { printf("FAIL line %d: %s\n",__LINE__,#condition);failures++; } } while(0)
static void put_i32(unsigned char *p,int v) { memcpy(p,&v,4); }
static void put_pointer(unsigned char *p,void *v) { memcpy(p,&v,8); }
static void bounds(Fixture *f,int id,int x,int z,int width,int height) {
    unsigned char *p=f->provinces[id];
    put_i32(p+0x88,x);put_i32(p+0x8c,z);put_i32(p+0x90,width);put_i32(p+0x94,height);
}
static void setup(Fixture *f,int total) {
    memset(f,0,sizeof(*f)); f->total=total;
    f->provinces=calloc(total,8);f->gfx=calloc(total,8);
    f->flags=calloc(total,1);f->native_visible=calloc(total,1);f->views=calloc(total,1);
    f->updates=calloc(total,sizeof(GPUpdate));f->leaves=calloc(total,4);
    for(int i=0;i<total;i++) {
        f->provinces[i]=calloc(1,0xc0);f->gfx[i]=calloc(1,0x1762);
        bounds(f,i,2800,1000,10,10);
    }
    put_pointer(f->map+0x20,f->eu3);put_pointer(f->map+0x68,f->gfx);
    put_i32(f->map+0x70,total);put_i32(f->map+0x74,total);
    put_pointer(f->map+0x00,f); /* Mock-only back reference, unused by wrapper. */
    float planes[4][4]={{-1,0,0,-1000000},{1,0,0,-1000000},{0,0,-1,-1000000},{0,0,1,-1000000}};
    memcpy(f->eu3+0x1c8,planes,sizeof(planes));
    f->province_desc=(GPArray){f->provinces,total,total,NULL};
    f->flags_desc=(GPArray){f->flags,total,total,NULL};
    f->update_desc=(GPArray){f->updates,total,total,NULL};
    f->leave_desc=(GPArray){f->leaves,total,total,NULL};
    f->context=(GPContext){f->map,&f->province_desc,&f->flags_desc,&f->update_count,&f->update_desc,&f->leave_count,&f->leave_desc};
}
static void cleanup(Fixture *f) {
    for(int i=0;i<f->total;i++) { free(f->provinces[i]);free(f->gfx[i]); }
    free(f->provinces);free(f->gfx);free(f->flags);free(f->native_visible);free(f->views);free(f->updates);free(f->leaves);
}
static void mock_native(GPContext *context,const int *range) {
    Fixture *f=gp_pointer((unsigned char *)context->map);
    InterlockedIncrement(&f->mock_calls);
    if(range[0]<1 || range[1]>f->total) return;
    for(int id=range[0];id<range[1];id++) {
        int visible=f->native_visible[id], view=f->views[id];
        int old=*((unsigned char *)f->gfx[id]+0x1761)&2;
        ((unsigned char *)context->flags->data)[id]|=(unsigned char)((visible?2:0)|(1<<(view+2)));
        if(old || visible) {
            LONG index=InterlockedIncrement(context->update_count)-1;
            void *camera=f->eu3+(view==0?0x10:view==1?0x230:0x450);
            ((GPUpdate *)context->updates->data)[index]=(GPUpdate){id,0,camera};
        }
        if(old && !visible) {
            LONG index=InterlockedIncrement(context->leave_count)-1;
            ((int *)context->leaves->data)[index]=id;
        }
    }
}
static GCamera camera={ {2800,2000,1000},{0,-1,0} };
static void small_merge(void) {
    Fixture f;setup(&f,8);GPStats stats={0}; int range[3]={1,8,1};
    f.flags[0]=0x40;
    f.native_visible[1]=1;f.views[1]=1;
    f.native_visible[5]=1;f.views[5]=2;
    *((unsigned char *)f.gfx[3]+0x1761)=2;
    *((unsigned char *)f.gfx[6]+0x1761)=2;
    for(int id=3;id<=5;id++) bounds(&f,id,5600,1000,10,10);
    bounds(&f,7,2800,2100,10,10);
    CHECK(gp_expand_worker(mock_native,&f.context,range,camera,&stats)==1);
    CHECK(f.mock_calls==1 && f.update_count==5 && f.leave_count==1);
    CHECK(f.flags[0]==0x40 && f.flags[1]==10 && f.flags[2]==6 && f.flags[3]==4 && f.flags[4]==4 && f.flags[5]==18 && f.flags[6]==6 && f.flags[7]==4);
    CHECK(f.leaves[0]==3 && stats.expanded==2 && stats.merge_refused==0);
    for(int i=0;i<f.update_count;i++) {
        int id=f.updates[i].province;
        CHECK(id==1 || id==2 || id==3 || id==5 || id==6);
        CHECK(f.updates[i].camera==f.eu3+(id==1?0x230:id==5?0x450:0x10));
    }
    cleanup(&f);
}
typedef struct ThreadCall { Fixture *f; int range[3]; GPStats *stats; int result; } ThreadCall;
static DWORD WINAPI call_worker(void *pointer) {
    ThreadCall *call=pointer;
    call->result=gp_expand_worker(mock_native,&call->f->context,call->range,camera,call->stats);
    return 0;
}
static void parallel_merge(void) {
    Fixture f;setup(&f,1025);GPStats stats={0};
    for(int id=1;id<f.total;id++) {
        f.native_visible[id]=(unsigned char)(id%2==0);f.views[id]=(unsigned char)(id%3);
        *((unsigned char *)f.gfx[id]+0x1761)=(unsigned char)(id%3==0?2:0);
    }
    f.flags[0]=0x40;
    HANDLE threads[16];ThreadCall calls[16];
    for(int i=0;i<16;i++) {
        calls[i]=(ThreadCall){&f,{1+i*64,1+(i+1)*64,1},&stats,0};
        threads[i]=CreateThread(NULL,0,call_worker,&calls[i],0,NULL);
        CHECK(threads[i]!=NULL);
    }
    CHECK(WaitForMultipleObjects(16,threads,TRUE,10000)==WAIT_OBJECT_0);
    for(int i=0;i<16;i++) { CHECK(calls[i].result==1);CloseHandle(threads[i]); }
    CHECK(f.update_count==1024 && f.leave_count==0 && f.flags[0]==0x40 && stats.expanded==512);
    unsigned char seen[1025]={0};
    for(int i=0;i<f.update_count;i++) {
        int id=f.updates[i].province;
        CHECK(id>=1 && id<f.total && !seen[id]);
        if(id>=1 && id<f.total) {
            seen[id]=1;
            int view=f.native_visible[id]?f.views[id]:0;
            CHECK(f.updates[i].camera==f.eu3+(view==0?0x10:view==1?0x230:0x450));
            CHECK(f.flags[id]==(unsigned char)(2|(1<<(view+2))));
        }
    }
    for(int id=1;id<f.total;id++) CHECK(seen[id]);
    cleanup(&f);
}
static void guards(void) {
    Fixture f;setup(&f,8);GPStats stats={0};int range[3]={1,2,1};
    f.native_visible[1]=1;
    f.flags_desc.capacity=7;
    CHECK(gp_expand_worker(mock_native,&f.context,range,camera,&stats)==0);
    CHECK(stats.fallback==1 && f.mock_calls==1 && f.update_count==1);
    volatile LONG count=3;
    CHECK(gp_reserve(&count,3,5)==-1 && count==3);
    CHECK(gp_reserve(&count,2,5)==3 && count==5);
    CHECK(gp_reserve(&count,1,5)==-1 && count==5);
    cleanup(&f);
}
static void reset_outputs(Fixture *f) {
    memset(f->flags,0,(size_t)f->total);f->update_count=0;f->leave_count=0;
}
static void cache_invalidation(void) {
    Fixture f;setup(&f,8);GPStats stats={0};int range[3]={1,2,1};
    CHECK(gp_expand_worker(mock_native,&f.context,range,camera,&stats)==1 && f.flags[1]==6);
    GPThreadCache *cache=gp_thread_cache();
    uint64_t probes=cache->probes, evaluations=cache->geometry_evaluations, grows=cache->buffer_grows;
    for(int i=0;i<5000;i++) {
        reset_outputs(&f);
        CHECK(gp_expand_worker(mock_native,&f.context,range,camera,&stats)==1 && f.flags[1]==6);
    }
    CHECK(cache->probes==probes && cache->geometry_evaluations==evaluations && cache->buffer_grows==grows);
    bounds(&f,1,5600,1000,10,10);reset_outputs(&f);
    CHECK(gp_expand_worker(mock_native,&f.context,range,camera,&stats)==1 && f.flags[1]==4 && f.update_count==0);
    CHECK(cache->geometry_evaluations==evaluations+1);
    GCamera moved=camera;moved.eye.x=5600;
    reset_outputs(&f);
    CHECK(gp_expand_worker(mock_native,&f.context,range,moved,&stats)==1 && f.flags[1]==6);
    CHECK(cache->geometry_evaluations==evaluations+2);
    float original_plane[4];memcpy(original_plane,f.eu3+0x1c8,sizeof(original_plane));
    float rejecting_plane[4]={1,0,0,1000000};memcpy(f.eu3+0x1c8,rejecting_plane,sizeof(rejecting_plane));
    reset_outputs(&f);
    CHECK(gp_expand_worker(mock_native,&f.context,range,moved,&stats)==1 && f.flags[1]==4);
    memcpy(f.eu3+0x1c8,original_plane,sizeof(original_plane));
    void *old_province=f.provinces[1];
    f.provinces[1]=calloc(1,0xc0);bounds(&f,1,2800,1000,10,10);reset_outputs(&f);
    CHECK(gp_expand_worker(mock_native,&f.context,range,moved,&stats)==1 && f.flags[1]==4);
    free(old_province);
    void *old_gfx=f.gfx[1];f.gfx[1]=calloc(1,0x1762);*((unsigned char *)f.gfx[1]+0x1761)=2;
    reset_outputs(&f);
    CHECK(gp_expand_worker(mock_native,&f.context,range,moved,&stats)==1 && f.flags[1]==4 && f.leave_count==1);
    free(old_gfx);
    void **old_provinces=f.provinces;f.provinces=malloc((size_t)f.total*8);
    memcpy(f.provinces,old_provinces,(size_t)f.total*8);f.province_desc.data=f.provinces;
    reset_outputs(&f);
    CHECK(gp_expand_worker(mock_native,&f.context,range,camera,&stats)==1 && f.flags[1]==6 && f.leave_count==0);
    free(old_provinces);
    GPUpdate *old_updates=f.updates;f.updates=calloc(f.total,sizeof(GPUpdate));f.update_desc.data=f.updates;
    reset_outputs(&f);
    CHECK(gp_expand_worker(mock_native,&f.context,range,camera,&stats)==1 && f.updates[0].province==1);
    free(old_updates);
    GPArray *old_descriptor=f.context.provinces;
    void *unreadable=VirtualAlloc(NULL,4096,MEM_COMMIT|MEM_RESERVE,PAGE_NOACCESS);
    CHECK(unreadable!=NULL);
    f.context.provinces=unreadable;reset_outputs(&f);
    CHECK(gp_expand_worker(mock_native,&f.context,range,camera,&stats)==0);
    f.context.provinces=old_descriptor;VirtualFree(unreadable,0,MEM_RELEASE);
    void *saved=f.provinces[1];f.provinces[1]=NULL;reset_outputs(&f);
    CHECK(gp_expand_worker(mock_native,&f.context,range,camera,&stats)==0);
    f.provinces[1]=saved;reset_outputs(&f);
    CHECK(gp_expand_worker(mock_native,&f.context,range,camera,&stats)==1 && f.flags[1]==6);
    CHECK(stats.merge_refused==0);
    printf("cache invalidation: 5000 warm calls without allocation, probes or geometric evaluation; camera/plane/bbox/object/array changes and guards PASS\n");
    cleanup(&f);
}
typedef struct WarmThreadCall {
    Fixture *fixture;
    GPStats *stats;
    SYNCHRONIZATION_BARRIER *barrier;
    int index,failed;
    uint64_t probes,grows,evaluations,hits;
} WarmThreadCall;
static DWORD WINAPI warm_worker(void *pointer) {
    WarmThreadCall *call=pointer;
    Fixture *f=call->fixture;
    GPThreadCache *cache=gp_thread_cache();
    int range[3]={1+call->index*64,1+(call->index+1)*64,1};
    for(int round=0;round<200;round++) {
        if(call->index==0) reset_outputs(f);
        EnterSynchronizationBarrier(call->barrier,0);
        GCamera current=camera;if(round==50) current.eye.x=5600;
        if(gp_expand_worker(mock_native,&f->context,range,current,call->stats)!=1) call->failed++;
        EnterSynchronizationBarrier(call->barrier,0);
        if(call->index==0) {
            int expected_updates=round==50?683:1024,expected_leaves=round==50?171:0;
            if(f->update_count!=expected_updates || f->leave_count!=expected_leaves) call->failed++;
            unsigned char seen[1025]={0};
            for(int i=0;i<f->update_count;i++) {
                int id=f->updates[i].province;
                if(id<1 || id>=f->total || seen[id]) { call->failed++;continue; }
                seen[id]=1;
                int view=f->native_visible[id]?f->views[id]:0;
                if(f->updates[i].camera!=f->eu3+(view==0?0x10:view==1?0x230:0x450)) call->failed++;
            }
        }
        EnterSynchronizationBarrier(call->barrier,0);
    }
    call->probes=cache->probes;call->grows=cache->buffer_grows;
    call->evaluations=cache->geometry_evaluations;call->hits=cache->geometry_hits;
    return 0;
}
static void parallel_warm_cache(void) {
    Fixture f;setup(&f,1025);GPStats stats={0};
    for(int id=1;id<f.total;id++) {
        f.native_visible[id]=(unsigned char)(id%2==0);f.views[id]=(unsigned char)(id%3);
        *((unsigned char *)f.gfx[id]+0x1761)=(unsigned char)(id%3==0?2:0);
    }
    SYNCHRONIZATION_BARRIER barrier;
    CHECK(InitializeSynchronizationBarrier(&barrier,16,-1));
    HANDLE threads[16];WarmThreadCall calls[16];
    for(int i=0;i<16;i++) {
        calls[i]=(WarmThreadCall){&f,&stats,&barrier,i,0,0,0,0,0};
        threads[i]=CreateThread(NULL,0,warm_worker,&calls[i],0,NULL);CHECK(threads[i]!=NULL);
    }
    CHECK(WaitForMultipleObjects(16,threads,TRUE,30000)==WAIT_OBJECT_0);
    uint64_t evaluations=0,hits=0;
    for(int i=0;i<16;i++) {
        CHECK(calls[i].failed==0 && calls[i].grows==2 && calls[i].evaluations==96);
        evaluations+=calls[i].evaluations;hits+=calls[i].hits;CloseHandle(threads[i]);
    }
    CHECK(stats.calls==3200 && stats.fallback==0 && stats.merge_refused==0);
    CHECK(evaluations==1536 && hits==100864);
    DeleteSynchronizationBarrier(&barrier);cleanup(&f);
    printf("warm concurrency: 16 threads x 200 task groups, moving camera and unique atomic outputs PASS\n");
}
static uint32_t rng=0x1897a42;
static float uniform(float a,float b) { rng=rng*1664525u+1013904223u;return a+(b-a)*(float)(rng>>8)/16777216.0f; }
static GVec3 cross(GVec3 a,GVec3 b) { return g_vec(a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x); }
static void build_planes(GCamera c,float planes[4][4]) {
    GVec3 forward=g_forward(c),right=g_normalize(cross(g_vec(0,1,0),forward));
    if(g_length(right)<0.1f) right=g_vec(1,0,0);
    GVec3 up=g_normalize(cross(forward,right));
    GVec3 p[4]={g_sub(right,g_scale(forward,0.7f)),g_sub(g_scale(right,-1),g_scale(forward,0.7f)),
                g_sub(up,g_scale(forward,0.4f)),g_sub(g_scale(up,-1),g_scale(forward,0.4f))};
    for(int i=0;i<4;i++) { planes[i][0]=p[i].x;planes[i][1]=p[i].y;planes[i][2]=p[i].z;planes[i][3]=-g_dot(p[i],c.eye); }
}
static void conservative_caps(void) {
    int visible_samples=0,boxes=10000;
    for(int b=0;b<boxes;b++) {
        GCamera c={g_vec(uniform(0,5632),uniform(25,3000),uniform(0,2048)),g_normalize(g_vec(0,-1,uniform(-0.5f,0.5f)))};
        float planes[4][4];build_planes(c,planes);
        int x=(int)uniform(-400,5632),z=(int)uniform(0,2048),w=(int)uniform(0,1000),h=(int)uniform(0,400);
        if(z+h>2048) h=2048-z;
        int conservative=gp_globe_visible(x,z,w,h,c,planes);
        GPNodeCache shape={0};GPPreparedCamera prepared;
        int bbox[4]={x,z,w,h};gp_prepare_shape(&shape,bbox);gp_prepare_camera(&prepared,c,planes);
        int optimized=gp_prepared_visible(&shape,&prepared);
        CHECK(optimized==conservative);
        for(int k=0;k<49;k++) {
            GVec3 flat=g_vec(x+(k%7)/6.0f*w,uniform(9.5f,70.0f),z+(k/7)/6.0f*h);
            GVec3 world=g_projected_world(flat,c);
            int visible=g_overlay_visibility(flat,c)>=0;
            for(int p=0;p<4;p++) visible=visible && planes[p][0]*world.x+planes[p][1]*world.y+planes[p][2]*world.z+planes[p][3]<=0;
            if(visible) { visible_samples++;CHECK(conservative && optimized); }
        }
    }
    CHECK(visible_samples>500);
    printf("conservative angular-cap/frustum test: %d boxes, %d visible samples, no false negatives\n",boxes,visible_samples);
}
int main(void) {
    CHECK(gp_call_rvas[0]==0xb5bcb3u && gp_original_calls[0][0]==0xe8 && gp_worker_prefix[0]==0x48);
    small_merge();parallel_merge();guards();cache_invalidation();parallel_warm_cache();conservative_caps();
    printf("province wrapper tests: %s (%d failures)\n",failures?"FAIL":"PASS",failures);
    return failures?1:0;
}
