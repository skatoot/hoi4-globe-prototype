#include "globe_geometry.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdint.h>
#include <stdio.h>

/* Independent double-precision V3 formula reference; not a GPU execution test. */
typedef struct DVec { double x,y,z; } DVec;
static const double DPI=3.14159265358979323846;
static DVec dv(double x,double y,double z){DVec v={x,y,z};return v;}
static DVec da(DVec a,DVec b){return dv(a.x+b.x,a.y+b.y,a.z+b.z);}
static DVec ds(DVec a,DVec b){return dv(a.x-b.x,a.y-b.y,a.z-b.z);}
static DVec dm(DVec a,double k){return dv(a.x*k,a.y*k,a.z*k);}
static double dd(DVec a,DVec b){return a.x*b.x+a.y*b.y+a.z*b.z;}
static double dl(DVec a){return sqrt(dd(a,a));}
static DVec dn(DVec a){return dm(a,1.0/fmax(dl(a),.00001));}
static DVec from_g(GVec3 v){return dv(v.x,v.y,v.z);}
static double dc(double x,double a,double b){return fmin(b,fmax(a,x));}
static double step(double a,double b,double x){double t=dc((x-a)/(b-a),0,1);return t*t*(3-2*t);}
static double dr(void){return 5632/(2*DPI);}
static DVec df(GCamera c){return dn(from_g(c.forward));}
static DVec focus(GCamera c){DVec f=df(c);double t=fmax(0,c.eye.y-9.5)/fmax(.05,-f.y);DVec p=da(from_g(c.eye),dm(f,t));p.y=9.5;p.z=dc(p.z,0,2048);return p;}
static double lat(double z){double y=(dc(z,0,2048)-672)/dr();return 2.5*atan(exp(.8*y))-.625*DPI;}
static DVec cn(GCamera c){DVec p=focus(c);return dv(p.x,9.5-dr(),p.z);}
static DVec norm(GVec3 p,GCamera c){DVec f=focus(c);double l=lat(p.z),fl=lat(f.z),lo=(p.x-f.x)*2*DPI/5632;double sl=sin(l),cl=cos(l),sf=sin(fl),cf=cos(fl),cd=cos(lo);return dn(dv(cl*sin(lo),cl*cd*cf+sl*sf,sl*cf-cl*cd*sf));}
static double rs(GCamera c){return 1.85+(1-1.85)*step(180,650,fmax(0,c.eye.y-9.5));}
static DVec pos(GVec3 p,GCamera c){double h=p.y-9.5;if(h>0)h*=rs(c);return da(cn(c),dm(norm(p,c),dr()+h));}
static double pb(GCamera c){DVec f=df(c);double h=fmax(0,c.eye.y-9.5);return (h/fmax(.05,-f.y))*.5*step(180,650,h);}
static DVec eye(GCamera c){return ds(from_g(c.eye),dm(df(c),pb(c)));}
static double bounds(GVec3 p){return fmin(p.z+2,2050-p.z);}
static double hor(GVec3 p,GCamera c){return dd(norm(p,c),dn(ds(eye(c),pos(p,c))));}
static double ov(GVec3 p,GCamera c){double b=bounds(p);if(b<0)return b;if(p.y<=9.52)return fmin(b,hor(p,c));DVec de=ds(pos(p,c),eye(c));double distance=dl(de);DVec ray=dm(de,1/fmax(distance,.00001)),off=ds(eye(c),cn(c));double a=dd(off,ray),r=dr()-.25,dis=a*a-dd(off,off)+r*r;if(dis<0)return fmin(b,1);double near=-a-sqrt(fmax(0,dis));if(near<=0)return fmin(b,1);return fmin(b,near-distance+.75);}
static DVec projected(GVec3 p,GCamera c){return da(pos(p,c),dm(df(c),pb(c)));}
static double error_vec(GVec3 a,DVec b){return fmax(fabs(a.x-b.x),fmax(fabs(a.y-b.y),fabs(a.z-b.z)));}
static double max2(double a,double b){return a>b?a:b;}
static uint32_t state=41083u;
static float random_range(float a,float b){state=state*1664525u+1013904223u;float t=(float)(state>>8)/16777216.0f;return a+t*(b-a);}

int main(void){
    double max_focus=0,max_position=0,max_normal=0,max_projected=0,max_eye=0,max_relief=0,max_horizon=0,max_overlay=0,max_pullback=0,max_seam=0,max_unit=0,max_anchor=0;
    unsigned overlay_sign_mismatch=0;
    const unsigned count=10000;
    for(unsigned i=0;i<count;i++){
        GCamera c={g_vec(random_range(0,G_MAP_WIDTH),random_range(50,3600),random_range(0,G_MAP_HEIGHT)),g_vec(random_range(-.45f,.45f),random_range(-1,-.55f),random_range(-.4f,.4f))};
        GVec3 p=g_vec(random_range(-G_MAP_WIDTH,2*G_MAP_WIDTH),random_range(-15,100),random_range(-128,G_MAP_HEIGHT+128));
        GVec3 gp=g_position(p,c),gn=g_surface_normal(p,c),gpr=g_projected_world(p,c),ge=g_camera_effective(c),gf=g_focus(c);
        assert(isfinite(gp.x)&&isfinite(gp.y)&&isfinite(gp.z));
        max_focus=max2(max_focus,error_vec(gf,focus(c)));
        max_position=max2(max_position,error_vec(gp,pos(p,c)));
        max_normal=max2(max_normal,error_vec(gn,norm(p,c)));
        max_projected=max2(max_projected,error_vec(gpr,projected(p,c)));
        max_eye=max2(max_eye,error_vec(ge,eye(c)));
        max_relief=max2(max_relief,fabs(g_relief_scale(c)-rs(c)));
        max_pullback=max2(max_pullback,fabs(g_view_pullback(c)-pb(c)));
        max_horizon=max2(max_horizon,fabs(g_horizon(p,c)-hor(p,c)));
        float go=g_overlay_visibility(p,c);double ro=ov(p,c);
        max_overlay=max2(max_overlay,fabs(go-ro));
        if(fabs(ro)>.05&&((go>=0)!=(ro>=0)))overlay_sign_mismatch++;
        max_unit=max2(max_unit,fabs(g_dot(gn,gn)-1));
        GVec3 seam=p;seam.x+=G_MAP_WIDTH;
        max_seam=max2(max_seam,error_vec(g_position(seam,c),from_g(gp)));
        max_anchor=max2(max_anchor,error_vec(g_position(gf,c),from_g(gf)));
    }
    /* Practical tolerances cover float trig and ordinary world-coordinate arithmetic. */
    assert(max_focus<.01&&max_position<.01&&max_projected<.02&&max_eye<.01);
    assert(max_normal<.00001&&max_unit<.00001&&max_anchor<.001&&max_seam<.02);
    assert(max_relief<.000001&&max_horizon<.00001&&max_pullback<.01);
    assert(max_overlay<.25);
    assert(overlay_sign_mismatch==0);
    GCamera close={g_vec(2800,50,1000),g_vec(0,-1,0)};
    GCamera far=close;far.eye.y=3000;
    assert(g_relief_scale(close)==1.85f&&g_relief_scale(far)==1.0f);
    for(int h=50;h<3000;h++){GCamera a=close,b=close;a.eye.y=(float)h;b.eye.y=(float)h+1;assert(g_relief_scale(a)>=g_relief_scale(b));}
    for(int y=0;y<10;y++){GVec3 p=g_vec(2800,(float)y,1000);if(p.y<=G_SEA_LEVEL){assert(fabsf(g_length(g_sub(g_position(p,close),g_center(close)))-g_length(g_sub(g_position(p,far),g_center(far))))<.001f);}}
    GVec3 base=g_position(g_vec(2800,20,1000),close),top=g_object_position(g_vec(2800,30,1000),20,close);
    assert(fabsf(g_length(g_sub(top,base))-10)<.001f);
    assert(g_map_bounds(g_vec(0,9.5f,-3))<0&&g_map_bounds(g_vec(0,9.5f,2051))<0);
    GCamera equator={g_vec(2816,850,672),g_vec(0,-1,0)};
    assert(g_overlay_visibility(g_vec(2816,20,672),equator)>0);
    assert(g_overlay_visibility(g_vec(0,20,672),equator)<0);
    float depths[]={0,.1f,.5f,.994f,.995f,.996f,.999f,1,1.0001f,1.001f,2,100};
    float previous=-1;
    for(unsigned i=0;i<sizeof(depths)/sizeof(depths[0]);i++){float d=g_far_depth(depths[i],1);assert(d>previous);previous=d;assert(g_far_depth(depths[i],-1)==depths[i]);if(depths[i]<=.995f)assert(d==depths[i]);else assert(d<1&&d>.995f);}
    printf("{\n  \"passed\":true,\n  \"cases\":%u,\n  \"scope\":\"Portable C11 float geometry versus independent double V3 formulas; no GPU or hook execution\",\n",count);
    printf("  \"radius_float\":%.9g,\n  \"max_focus_world_error\":%.9g,\n  \"max_position_world_error\":%.9g,\n  \"max_projected_world_error\":%.9g,\n  \"max_effective_eye_world_error\":%.9g,\n",g_radius(),max_focus,max_position,max_projected,max_eye);
    printf("  \"max_surface_normal_error\":%.9g,\n  \"max_normal_length_squared_error\":%.9g,\n  \"max_relief_scale_error\":%.9g,\n  \"max_pullback_world_error\":%.9g,\n  \"max_horizon_error\":%.9g,\n  \"max_overlay_visibility_world_error\":%.9g,\n",max_normal,max_unit,max_relief,max_pullback,max_horizon,max_overlay);
    printf("  \"max_seam_world_error\":%.9g,\n  \"max_focus_anchor_world_error\":%.9g,\n  \"overlay_sign_mismatch_away_from_boundary\":%u,\n  \"near_far_depth_and_relief_edge_cases\":true,\n  \"model_base_height_preservation\":true,\n  \"geometry_tolerance_world_units\":0.02,\n  \"overlay_clearance_tolerance_world_units\":0.25,\n  \"overlay_sign_boundary_excluded_world_units\":0.05,\n  \"camera_height_range\":[50,3600]\n}\n",max_seam,max_anchor,overlay_sign_mismatch);
    return 0;
}
