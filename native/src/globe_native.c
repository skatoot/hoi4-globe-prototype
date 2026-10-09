/* HOI4 1.19.3 local globe bridge. Scoped icon and terrain CALLs are changed.
   The installed executable is never written. All original instructions remain
   available for restoring the CALL; the bridge stays loaded until process exit. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include "globe_geometry.h"
#include "globe_province.h"

#define ICON_CALL_RVA 0x163fe26u
#define ORIGINAL_PROJECT_RVA 0x11909c0u
#define TERRAIN_CALL_RVA 0x127db2cu
#define TERRAIN_MASK_RVA 0x12812c0u
#define COUNTRY_CALL_RVA 0xb58172u
#define COUNTRY_DRAW_RVA 0x164a300u
static const unsigned char country_call[5]={0xe8,0x89,0x21,0xaf,0x00};
static const unsigned char country_prefix[24]={0x48,0x8b,0xc4,0x48,0x89,0x58,0x08,0x4c,0x89,0x48,0x20,0x4c,0x89,0x40,0x18,0x48,0x89,0x50,0x10,0x55,0x56,0x57,0x41,0x54};
static const unsigned char original_terrain_call[5]={0xe8,0x8f,0x37,0x00,0x00};
static const unsigned char terrain_prefix[15]={0x48,0x8b,0xc4,0x48,0x89,0x58,0x10,0x4c,0x89,0x40,0x18,0x48,0x89,0x48,0x08};
static const unsigned char original_call[5] = {0xe8,0x95,0x0b,0xb5,0xff};
static const unsigned char original_project_prefix[14] = {
    0x48,0x83,0xec,0x68,0xf3,0x0f,0x10,0x62,0x04,0xf3,0x0f,0x10,0x69,0x08};
typedef float (*ProjectFn)(const float *, const GVec3 *, float *, const int *);
typedef void (*TerrainFn)(void *,void *,const void *);
typedef void (*CountryFn)(uintptr_t,uintptr_t,uintptr_t,void *,const void *,void *,float,float,float,float,uintptr_t,uintptr_t);
static HMODULE own_module;
static unsigned char *game_base, *relay;
static ProjectFn original_project;
static TerrainFn original_terrain;
static GPWorkerFn original_province;
static CountryFn original_country;
static volatile LONG country_calls,country_expanded;
static GPStats province_stats;
static volatile LONG province_camera_rejected, province_disabled;
static unsigned char *height_bitmap;
static DWORD height_offset, height_stride;
static int height_bottom_up;
static volatile LONG installed, calls, hidden, bad_camera;
static volatile LONG terrain_calls, expanded_calls, last_patches;
static volatile LONG terrain_bound_rejected;
typedef struct CallPatch { unsigned rva; const unsigned char *original; unsigned char replacement[5]; int active; } CallPatch;
static CallPatch patches[8];
static int patch_count=7;
static HANDLE stop_event;
static wchar_t directory[MAX_PATH], status_path[MAX_PATH], log_path[MAX_PATH];

static void log_line(const char *line) {
    FILE *out = _wfopen(log_path, L"a");
    if (out) { fprintf(out, "%s\n", line); fclose(out); }
}
static void write_status(void) {
    FILE *out = _wfopen(status_path, L"w");
    if (!out) return;
    fprintf(out,"{\"version\":\"0.3\",\"pid\":%lu,\"installed\":%s,\"map_icon_calls\":%ld,\"horizon_hidden\":%ld,\"camera_probe_rejected\":%ld,\"terrain_calls\":%ld,\"terrain_expansions\":%ld,\"last_selected_patches\":%ld,\"terrain_bound_rejected\":%ld,\"province_worker_calls\":%ld,\"globe_added_provinces\":%ld,\"province_fallback_calls\":%ld,\"province_merge_refused\":%ld,\"province_camera_rejected\":%ld,\"country_name_calls\":%ld,\"country_name_expansions\":%ld,\"heightmap_loaded\":%s,\"installed_executable_modified\":false}\n",
        GetCurrentProcessId(), installed?"true":"false", calls, hidden, bad_camera, terrain_calls, expanded_calls, last_patches, terrain_bound_rejected,
        province_stats.calls,province_stats.expanded,province_stats.fallback,province_stats.merge_refused,province_camera_rejected,country_calls,country_expanded,height_bitmap?"true":"false");
    fclose(out);
}
static uint32_t read_u32(const unsigned char *p) { uint32_t v; memcpy(&v,p,4); return v; }
static int load_heightmap(void) {
    wchar_t path[MAX_PATH];
    if (swprintf(path,MAX_PATH,L"%ls\\..\\mod\\map\\heightmap.bmp",directory)<0) return 0;
    HANDLE file = CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if (file==INVALID_HANDLE_VALUE) return 0;
    DWORD bytes = GetFileSize(file,NULL), read=0;
    if (bytes<54 || bytes>20000000) { CloseHandle(file); return 0; }
    unsigned char *data=(unsigned char *)malloc(bytes);
    int ok=data && ReadFile(file,data,bytes,&read,NULL) && read==bytes;
    CloseHandle(file);
    if (!ok) { free(data); return 0; }
    int width=(int)read_u32(data+18), height=(int)read_u32(data+22);
    DWORD offset=read_u32(data+10), stride=((width+3)/4)*4;
    if (data[0]!='B'||data[1]!='M'||width!=5632||abs(height)!=2048||data[28]!=8||data[29]!=0||
        read_u32(data+30)!=0 || offset<54 || (uint64_t)offset+(uint64_t)stride*2048>bytes) {
        free(data); return 0;
    }
    height_bitmap=data; height_offset=offset; height_stride=stride; height_bottom_up=height>0;
    return 1;
}
static float terrain_at(float x,float z) {
    x=x-floorf(x/5632.0f)*5632.0f; z=fmaxf(0.0f,fminf(2047.0f,z));
    int x0=(int)floorf(x), x1=(x0+1)%5632, z0=(int)floorf(z), z1=z0<2047?z0+1:z0;
    int row0=height_bottom_up?z0:2047-z0, row1=height_bottom_up?z1:2047-z1;
    const unsigned char *a=height_bitmap+height_offset+(size_t)row0*height_stride;
    const unsigned char *b=height_bitmap+height_offset+(size_t)row1*height_stride;
    float fx=x-x0, fz=z-z0;
    float value=(a[x0]*(1-fx)+a[x1]*fx)*(1-fz)+(b[x0]*(1-fx)+b[x1]*fx)*fz;
    return fmaxf(9.5f,value*0.1f);
}
static int camera_from_matrix(const float *matrix,GCamera *cam) {
    const float *eye=(const float *)((const unsigned char *)matrix+0x100);
    const float *look=(const float *)((const unsigned char *)matrix+0x10c);
    for (int i=0;i<3;i++) if(!isfinite(eye[i])||!isfinite(look[i])||fabsf(eye[i])>10000000.0f||fabsf(look[i])>10000000.0f) return 0;
    cam->eye=(GVec3){eye[0],eye[1],eye[2]};
    GVec3 delta={look[0]-eye[0],look[1]-eye[1],look[2]-eye[2]};
    float len=sqrtf(delta.x*delta.x+delta.y*delta.y+delta.z*delta.z);
    if (len<0.001f || cam->eye.y<9.5f || cam->eye.y>100000.0f) return 0;
    cam->forward=(GVec3){delta.x/len,delta.y/len,delta.z/len};
    float wlen=sqrtf(matrix[3]*matrix[3]+matrix[7]*matrix[7]+matrix[11]*matrix[11]);
    if(wlen<0.00001f) return 0;
    float agree=(matrix[3]*cam->forward.x+matrix[7]*cam->forward.y+matrix[11]*cam->forward.z)/wlen;
    /* Eye and matrix must describe the same perspective camera. */
    for(int column=0;column<4;column++) if(column!=2) {
        float terms[4]={eye[0]*matrix[column],eye[1]*matrix[4+column],eye[2]*matrix[8+column],matrix[12+column]};
        float residual=terms[0]+terms[1]+terms[2]+terms[3];
        float size=fabsf(terms[0])+fabsf(terms[1])+fabsf(terms[2])+fabsf(terms[3]);
        if(!isfinite(residual)||fabsf(residual)>0.01f+0.00002f*size) return 0;
    }
    return isfinite(agree)&&agree>0.995f;
}
static float hooked_project(const float *matrix,const GVec3 *source,float *screen,const int *viewport) {
    LONG number=InterlockedIncrement(&calls);
    GCamera camera;
    if(!matrix || !source || !screen || !viewport || viewport[0]<=0 || viewport[1]<=0 || !camera_from_matrix(matrix,&camera)) {
        InterlockedIncrement(&bad_camera);
        return original_project(matrix,source,screen,viewport);
    }
    GVec3 flat=*source;
    if(!isfinite(flat.x)||!isfinite(flat.y)||!isfinite(flat.z)) return original_project(matrix,source,screen,viewport);
    flat.y=terrain_at(flat.x,flat.z)+0.15f/g_relief_scale(camera);
    if(g_overlay_visibility(flat,camera)<0.0f) {
        InterlockedIncrement(&hidden); screen[0]=-100000.0f; screen[1]=-100000.0f; return 2.0f;
    }
    GVec3 projected=g_projected_world(flat,camera);
    float clip_w=projected.x*matrix[3]+projected.y*matrix[7]+projected.z*matrix[11]+matrix[15];
    if(clip_w<=0.00001f) {
        InterlockedIncrement(&hidden); screen[0]=-100000.0f; screen[1]=-100000.0f; return 2.0f;
    }
    float depth=original_project(matrix,&projected,screen,viewport);
    depth=g_far_depth(depth,clip_w);
    if(!isfinite(screen[0])||!isfinite(screen[1])||!isfinite(depth)) {
        screen[0]=-100000.0f; screen[1]=-100000.0f; depth=2.0f;
    }
    if(number<=12) {
        char line[512];
        snprintf(line,sizeof(line),"icon %ld: flat=(%.3f,%.3f,%.3f), groundedY=%.3f, camera=(%.3f,%.3f,%.3f), screen=(%.3f,%.3f)",
            number,source->x,source->y,source->z,flat.y,camera.eye.x,camera.eye.y,camera.eye.z,screen[0],screen[1]);
        log_line(line);
    }
    return depth;
}
static void hooked_terrain(void *terrain,void *mapdata,const void *camera) {
    InterlockedIncrement(&terrain_calls);
    const unsigned char *source=(const unsigned char *)camera;
    float lod_y,eye_y; memcpy(&lod_y,source+0x684,4);memcpy(&eye_y,source+0x194,4);
    int count,max_lod;memcpy(&count,(unsigned char *)terrain+0x497c,4);memcpy(&max_lod,(unsigned char *)terrain+0x5cc0,4);
    if(terrain_bound_rejected||!isfinite(lod_y)||!isfinite(eye_y)||fabsf(lod_y-eye_y)>1.0f||eye_y<9.5f||count!=2816||max_lod!=3) {
        original_terrain(terrain,mapdata,camera);return;
    }
    _Alignas(16) unsigned char copy[0x700];memcpy(copy,source,sizeof(copy));
    const float bounds[4][4]={{-1,0,0,0},{1,0,0,-5632},{0,0,-1,0},{0,0,1,-2048}};
    memcpy(copy+0x1c8,bounds,sizeof(bounds));copy[0x6f8]=0;
    original_terrain(terrain,mapdata,copy);
    LONG expanded=InterlockedIncrement(&expanded_calls);int patches=0;
    unsigned char *mask;memcpy(&mask,(unsigned char *)terrain+0x4970,sizeof(mask));
    if(mask) for(int i=0;i<count;i++) if((signed char)mask[2*i]>0 && (mask[2*i+1]&1)) patches++;
    if(patches>188) {
        InterlockedIncrement(&terrain_bound_rejected);original_terrain(terrain,mapdata,camera);
        log_line("Terrain patch count exceeded verified bound; reverted to native visibility.");return;
    }
    InterlockedExchange(&last_patches,patches);
    if(expanded<=3) {char line[200];snprintf(line,sizeof(line),"globe terrain: storedY=%.3f, eyeY=%.3f, selectedPatches=%d (bounded to188)",lod_y,eye_y,patches);log_line(line);}
}
static void hooked_province(GPContext *context,const int *range) {
    GCamera camera;unsigned char *eu3=NULL;GPThreadCache *cache=gp_thread_cache();
    if(cache && !cache->busy && gp_probe(cache,context,sizeof(*context),0) && gp_probe(cache,context->map,0x28,0))eu3=(unsigned char *)gp_pointer((unsigned char *)context->map+0x20);
    if(province_disabled || !cache || cache->busy || !gp_probe(cache,eu3,0x6f9,0) || !camera_from_matrix((const float *)(eu3+0x90),&camera)) {
        InterlockedIncrement(&province_stats.calls);InterlockedIncrement(&province_stats.fallback);
        InterlockedIncrement(&province_camera_rejected);original_province(context,range);return;
    }
    int result=gp_expand_worker(original_province,context,range,camera,&province_stats);
    if(result<0 && !InterlockedExchange(&province_disabled,1))log_line("Province merge was refused by bounds; further expansion disabled.");
}
static void hooked_country(uintptr_t a,uintptr_t b,uintptr_t c,void *effect,const void *camera,void *group,
                            float range,float opacity,float daytime,float fade,uintptr_t extra1,uintptr_t extra2) {
    InterlockedIncrement(&country_calls);GCamera validated;
    if(opacity==0.0f || !gp_readable(camera,0x700,0) || !camera_from_matrix((const float *)((const unsigned char *)camera+0x90),&validated)) {
        original_country(a,b,c,effect,camera,group,range,opacity,daytime,fade,extra1,extra2);return;
    }
    _Alignas(16) unsigned char copy[0x700];memcpy(copy,camera,sizeof(copy));
    memset(copy+0x1c8,0,4*4*sizeof(float));copy[0x6f8]=0;
    InterlockedIncrement(&country_expanded);
    original_country(a,b,c,effect,copy,group,range,opacity,daytime,fade,extra1,extra2);
}

/* Prepare handles first, then suspend only sibling threads in this game process.
   No file I/O or CRT allocation occurs while those threads are suspended. */
static int change_calls(int enable) {
    HANDLE handles[512]; int count=0, suspended=0, ok=1;
    HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
    if(snapshot==INVALID_HANDLE_VALUE) return 0;
    THREADENTRY32 entry={0}; entry.dwSize=sizeof(entry);
    if(Thread32First(snapshot,&entry)) do {
        if(entry.th32OwnerProcessID==GetCurrentProcessId()&&entry.th32ThreadID!=GetCurrentThreadId()) {
            if(count==512) { ok=0; break; }
            handles[count]=OpenThread(THREAD_SUSPEND_RESUME|THREAD_GET_CONTEXT,FALSE,entry.th32ThreadID);
            if(!handles[count]) { ok=0; break; } count++;
        }
    } while(Thread32Next(snapshot,&entry));
    CloseHandle(snapshot);
    if(ok) for(int i=0;i<count;i++) {
        if(SuspendThread(handles[i])==(DWORD)-1) { ok=0; break; }
        suspended++;
        CONTEXT context={0}; context.ContextFlags=CONTEXT_CONTROL;
        if(!GetThreadContext(handles[i],&context)) { ok=0; break; }
        for(int j=0;j<patch_count;j++) {
            unsigned char *call=game_base+patches[j].rva;
            if(context.Rip>(DWORD64)call&&context.Rip<(DWORD64)call+5) {ok=0;break;}
        }
        if(!ok)break;
    }
    DWORD protection[8];int protected_count=0;
    if(ok)for(int j=0;j<patch_count;j++) {
        const unsigned char *expected=patches[j].active?patches[j].replacement:patches[j].original;
        if(memcmp(game_base+patches[j].rva,expected,5)) {ok=0;break;}
    }
    if(ok)for(int j=0;j<patch_count;j++) {
        if(!VirtualProtect(game_base+patches[j].rva,5,PAGE_EXECUTE_READWRITE,&protection[j])) {ok=0;break;}
        protected_count++;
    }
    /* All sites are verified and writable before any instruction is changed. */
    if(ok)for(int j=0;j<patch_count;j++) {
        unsigned char *call=game_base+patches[j].rva;
        memcpy(call,enable?patches[j].replacement:patches[j].original,5);
        FlushInstructionCache(GetCurrentProcess(),call,5);patches[j].active=enable;
    }
    /* Multiple CALLs share a page; unwind protections in reverse order. */
    for(int j=protected_count-1;j>=0;j--) {DWORD ignored;VirtualProtect(game_base+patches[j].rva,5,protection[j],&ignored);}
    for(int i=0;i<suspended;i++) ResumeThread(handles[i]);
    for(int i=0;i<count;i++) CloseHandle(handles[i]);
    return ok;
}
__declspec(dllexport) DWORD WINAPI GlobeUninstall(void *unused) {
    (void)unused;
    if(!installed) return 1;
    if(!change_calls(0)) return 0;
    InterlockedExchange(&installed,0); SetEvent(stop_event); log_line("Restored all original scoped CALLs."); write_status();
    return 1;
}
/* Tests can load this library into Python without installing any game hooks. */
__declspec(dllexport) int GlobeTestWorld(const float *flat,const float *eye,const float *forward,float *out) {
    GVec3 point={flat[0],flat[1],flat[2]}; GCamera cam={{eye[0],eye[1],eye[2]},{forward[0],forward[1],forward[2]}};
    GVec3 p=g_projected_world(point,cam);
    out[0]=p.x;out[1]=p.y;out[2]=p.z;out[3]=g_overlay_visibility(point,cam);out[4]=g_relief_scale(cam);
    return 1;
}
__declspec(dllexport) int GlobeTestCamera(const float *matrix,float *out) {
    GCamera cam;
    if(!camera_from_matrix(matrix,&cam))return 0;
    out[0]=cam.eye.x;out[1]=cam.eye.y;out[2]=cam.eye.z;
    out[3]=cam.forward.x;out[4]=cam.forward.y;out[5]=cam.forward.z;return 1;
}
__declspec(dllexport) int GlobeDescribeCall(int index,unsigned *rva,unsigned char *bytes) {
    const unsigned char *original;
    if(index==0){*rva=ICON_CALL_RVA;original=original_call;}
    else if(index==1){*rva=TERRAIN_CALL_RVA;original=original_terrain_call;}
    else if(index>=2&&index<6){*rva=gp_call_rvas[index-2];original=gp_original_calls[index-2];}
    else if(index==6){*rva=COUNTRY_CALL_RVA;original=country_call;}
    else return 0;
    memcpy(bytes,original,5);return 1;
}
static DWORD WINAPI initialize(void *unused) {
    (void)unused;
    wchar_t executable[MAX_PATH]; GetModuleFileNameW(NULL,executable,MAX_PATH);
    wchar_t *name=wcsrchr(executable,L'\\'); name=name?name+1:executable;
    if(_wcsicmp(name,L"hoi4.exe")!=0) return 0;
    GetModuleFileNameW(own_module,directory,MAX_PATH);
    wchar_t *slash=wcsrchr(directory,L'\\'); if(!slash) return 0; *slash=0;
    swprintf(status_path,MAX_PATH,L"%ls\\bridge-status.json",directory);
    swprintf(log_path,MAX_PATH,L"%ls\\bridge.log",directory);
    FILE *reset=_wfopen(log_path,L"w"); if(reset) fclose(reset);
    game_base=(unsigned char *)GetModuleHandleW(NULL);
    IMAGE_DOS_HEADER *dos=(IMAGE_DOS_HEADER *)game_base;
    IMAGE_NT_HEADERS64 *pe=(IMAGE_NT_HEADERS64 *)(game_base+dos->e_lfanew);
    if(pe->OptionalHeader.SizeOfImage<ICON_CALL_RVA+16 || memcmp(game_base+ICON_CALL_RVA,original_call,5) ||
        memcmp(game_base+ORIGINAL_PROJECT_RVA,original_project_prefix,sizeof(original_project_prefix)) ||
        memcmp(game_base+TERRAIN_CALL_RVA,original_terrain_call,5) || memcmp(game_base+TERRAIN_MASK_RVA,terrain_prefix,sizeof(terrain_prefix))) {
        log_line("Unsupported executable instructions; no hook installed.");write_status();return 0;
    }
    if(memcmp(game_base+GP_WORKER_RVA,gp_worker_prefix,sizeof(gp_worker_prefix))) {
        log_line("Unsupported province worker instructions; no hook installed.");write_status();return 0;
    }
    for(int i=0;i<4;i++)if(memcmp(game_base+gp_call_rvas[i],gp_original_calls[i],5)) {
        log_line("Unsupported province CALL instructions; no hook installed.");write_status();return 0;
    }
    if(memcmp(game_base+COUNTRY_CALL_RVA,country_call,5)||memcmp(game_base+COUNTRY_DRAW_RVA,country_prefix,sizeof(country_prefix))) {
        log_line("Unsupported country-name instructions; no hook installed.");write_status();return 0;
    }
    if(!load_heightmap()) {log_line("Validated heightmap missing or invalid; no hook installed.");write_status();return 0;}
    original_project=(ProjectFn)(game_base+ORIGINAL_PROJECT_RVA);
    original_terrain=(TerrainFn)(game_base+TERRAIN_MASK_RVA);
    original_province=(GPWorkerFn)(game_base+GP_WORKER_RVA);
    original_country=(CountryFn)(game_base+COUNTRY_DRAW_RVA);
    SYSTEM_INFO system;GetSystemInfo(&system); uintptr_t site=(uintptr_t)(game_base+ICON_CALL_RVA);
    uintptr_t aligned=site&~((uintptr_t)system.dwAllocationGranularity-1);
    for(uintptr_t distance=system.dwAllocationGranularity;distance<0x70000000u;distance+=system.dwAllocationGranularity) {
        uintptr_t candidate=aligned+distance;
        relay=(unsigned char *)VirtualAlloc((void *)candidate,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
        if(relay) break;
        if(aligned>distance) relay=(unsigned char *)VirtualAlloc((void *)(aligned-distance),4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
        if(relay) break;
    }
    if(!relay) {log_line("No near relay allocation; no hook installed.");write_status();return 0;}
    relay[0]=0xff;relay[1]=0x25;memset(relay+2,0,4); uintptr_t target=(uintptr_t)&hooked_project;memcpy(relay+6,&target,8);
    relay[32]=0xff;relay[33]=0x25;memset(relay+34,0,4);target=(uintptr_t)&hooked_terrain;memcpy(relay+38,&target,8);
    relay[64]=0xff;relay[65]=0x25;memset(relay+66,0,4);target=(uintptr_t)&hooked_province;memcpy(relay+70,&target,8);
    relay[96]=0xff;relay[97]=0x25;memset(relay+98,0,4);target=(uintptr_t)&hooked_country;memcpy(relay+102,&target,8);
    DWORD ignored; if(!VirtualProtect(relay,4096,PAGE_EXECUTE_READ,&ignored)) return 0;
    FlushInstructionCache(GetCurrentProcess(),relay,110);
    patches[0]=(CallPatch){.rva=ICON_CALL_RVA,.original=original_call};
    patches[1]=(CallPatch){.rva=TERRAIN_CALL_RVA,.original=original_terrain_call};
    for(int i=0;i<4;i++)patches[i+2]=(CallPatch){.rva=gp_call_rvas[i],.original=gp_original_calls[i]};
    patches[6]=(CallPatch){.rva=COUNTRY_CALL_RVA,.original=country_call};
    for(int i=0;i<patch_count;i++) {
        intptr_t delta=(intptr_t)(relay+32*(i<2?i:(i==6?3:2)))-((intptr_t)(game_base+patches[i].rva)+5);
        if(delta<INT32_MIN||delta>INT32_MAX) return 0;
        patches[i].replacement[0]=0xe8;int32_t relative=(int32_t)delta;memcpy(patches[i].replacement+1,&relative,4);
    }
    stop_event=CreateEventW(NULL,TRUE,FALSE,NULL);
    int patched=0;if(stop_event)for(int attempt=0;attempt<5&&!patched;attempt++){patched=change_calls(1);if(!patched)Sleep(30);}
    if(!patched) {log_line("CALL transaction refused; no hook installed.");write_status();return 0;}
    InterlockedExchange(&installed,1);log_line("Installed seven verified icon, terrain, province and country-name CALL bridges. No executable file was modified.");write_status();
    while(WaitForSingleObject(stop_event,1000)==WAIT_TIMEOUT) write_status();
    return 1;
}
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,LPVOID reserved) {
    (void)reserved;
    if(reason==DLL_PROCESS_ATTACH) {
        own_module=module;DisableThreadLibraryCalls(module);
        HANDLE worker=CreateThread(NULL,0,initialize,NULL,0,NULL);if(worker)CloseHandle(worker);
    }
    return TRUE;
}
