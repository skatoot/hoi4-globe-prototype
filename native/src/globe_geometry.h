#ifndef HOI4_GLOBE_GEOMETRY_H
#define HOI4_GLOBE_GEOMETRY_H

/* C11 float reference for work/globe_projection_v3.fxh.
 * Camera.eye is the native flat-map camera; Camera.forward is its look direction.
 * Geometry methods return canonical sphere coordinates unless named projected_world.
 * This header does not read/write process memory, change a matrix, or install hooks.
 */
#include <math.h>

typedef struct GVec3 { float x, y, z; } GVec3;
typedef struct GCamera { GVec3 eye, forward; } GCamera;

#define G_MAP_WIDTH 5632.0f
#define G_MAP_HEIGHT 2048.0f
#define G_SEA_LEVEL 9.5f
#define G_PI 3.14159265358979323846f
#define G_OVERVIEW_PULLBACK 0.50f
#define G_EQUATOR_FRACTION (672.0f / 2048.0f)

static inline float g_min(float a, float b) { return a < b ? a : b; }
static inline float g_max(float a, float b) { return a > b ? a : b; }
static inline float g_clamp(float x, float a, float b) { return g_min(b, g_max(a, x)); }
static inline float g_lerp(float a, float b, float t) { return a + t * (b - a); }
static inline float g_smoothstep(float a, float b, float x) {
    float t = g_clamp((x - a) / (b - a), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}
static inline GVec3 g_vec(float x, float y, float z) { GVec3 v = {x, y, z}; return v; }
static inline GVec3 g_add(GVec3 a, GVec3 b) { return g_vec(a.x+b.x, a.y+b.y, a.z+b.z); }
static inline GVec3 g_sub(GVec3 a, GVec3 b) { return g_vec(a.x-b.x, a.y-b.y, a.z-b.z); }
static inline GVec3 g_scale(GVec3 v, float s) { return g_vec(v.x*s, v.y*s, v.z*s); }
static inline float g_dot(GVec3 a, GVec3 b) { return a.x*b.x + a.y*b.y + a.z*b.z; }
static inline float g_length(GVec3 v) { return sqrtf(g_dot(v, v)); }
static inline GVec3 g_normalize(GVec3 v) { return g_scale(v, 1.0f/g_max(g_length(v), 0.00001f)); }

static inline float g_radius(void) { return G_MAP_WIDTH / (2.0f * G_PI); }
static inline GVec3 g_forward(GCamera cam) { return g_normalize(cam.forward); }

/* Flat focus expressed as a 3-vector {east, sea level, north}, not a latitude. */
static inline GVec3 g_focus(GCamera cam) {
    GVec3 forward = g_forward(cam);
    float travel = g_max(0.0f, cam.eye.y-G_SEA_LEVEL) / g_max(0.05f, -forward.y);
    GVec3 focus = g_add(cam.eye, g_scale(forward, travel));
    focus.y = G_SEA_LEVEL;
    focus.z = g_clamp(focus.z, 0.0f, G_MAP_HEIGHT);
    return focus;
}
static inline float g_latitude(float map_north) {
    float equator = G_EQUATOR_FRACTION * G_MAP_HEIGHT;
    float projected = (g_clamp(map_north, 0.0f, G_MAP_HEIGHT)-equator) / g_radius();
    return 2.5f*atanf(expf(0.8f*projected)) - 0.625f*G_PI;
}
static inline GVec3 g_center(GCamera cam) {
    GVec3 focus = g_focus(cam);
    return g_vec(focus.x, G_SEA_LEVEL-g_radius(), focus.z);
}
static inline GVec3 g_surface_normal(GVec3 flat, GCamera cam) {
    GVec3 focus = g_focus(cam);
    float lat = g_latitude(flat.z), focus_lat = g_latitude(focus.z);
    float lon = (flat.x-focus.x)*(2.0f*G_PI/G_MAP_WIDTH);
    float sl = sinf(lat), cl = cosf(lat), sf = sinf(focus_lat), cf = cosf(focus_lat), cd = cosf(lon);
    return g_normalize(g_vec(cl*sinf(lon), cl*cd*cf + sl*sf, sl*cf - cl*cd*sf));
}
static inline float g_relief_scale(GCamera cam) {
    float altitude = g_max(0.0f, cam.eye.y-G_SEA_LEVEL);
    return g_lerp(1.85f, 1.0f, g_smoothstep(180.0f, 650.0f, altitude));
}
static inline GVec3 g_position(GVec3 flat, GCamera cam) {
    float altitude = flat.y-G_SEA_LEVEL;
    if (altitude > 0.0f) altitude *= g_relief_scale(cam);
    return g_add(g_center(cam), g_scale(g_surface_normal(flat,cam),g_radius()+altitude));
}
/* Use only with a verified base height. Generic position also scales model height. */
static inline GVec3 g_object_position(GVec3 flat, float base_surface_height, GCamera cam) {
    float base_altitude = base_surface_height-G_SEA_LEVEL;
    if (base_altitude > 0.0f) base_altitude *= g_relief_scale(cam);
    float altitude = base_altitude + flat.y-base_surface_height;
    return g_add(g_center(cam),g_scale(g_surface_normal(flat,cam),g_radius()+altitude));
}
static inline float g_view_pullback(GCamera cam) {
    float height = g_max(0.0f,cam.eye.y-G_SEA_LEVEL);
    GVec3 forward = g_forward(cam);
    float focus_distance = height/g_max(0.05f,-forward.y);
    return focus_distance*G_OVERVIEW_PULLBACK*g_smoothstep(180.0f,650.0f,height);
}
static inline GVec3 g_camera_effective(GCamera cam) {
    return g_sub(cam.eye,g_scale(g_forward(cam),g_view_pullback(cam)));
}
static inline float g_map_bounds(GVec3 flat) {
    return g_min(flat.z+2.0f,G_MAP_HEIGHT+2.0f-flat.z);
}
static inline float g_horizon(GVec3 flat, GCamera cam) {
    GVec3 view = g_normalize(g_sub(g_camera_effective(cam),g_position(flat,cam)));
    return g_dot(g_surface_normal(flat,cam),view);
}
static inline float g_surface_visibility(GVec3 flat, GCamera cam) {
    return g_min(g_map_bounds(flat),g_horizon(flat,cam));
}
static inline float g_overlay_visibility(GVec3 flat, GCamera cam) {
    float bounds = g_map_bounds(flat);
    if (bounds < 0.0f) return bounds;
    if (flat.y <= G_SEA_LEVEL+0.02f) return g_min(bounds,g_horizon(flat,cam));
    GVec3 overlay = g_position(flat,cam), eye = g_camera_effective(cam);
    GVec3 delta = g_sub(overlay,eye);
    float distance = g_length(delta);
    GVec3 ray = g_scale(delta,1.0f/g_max(distance,0.00001f));
    GVec3 offset = g_sub(eye,g_center(cam));
    float along = g_dot(offset,ray), body_radius = g_radius()-0.25f;
    float discriminant = along*along-g_dot(offset,offset)+body_radius*body_radius;
    if (discriminant < 0.0f) return g_min(bounds,1.0f);
    float near_hit = -along-sqrtf(g_max(0.0f,discriminant));
    if (near_hit <= 0.0f) return g_min(bounds,1.0f);
    return g_min(bounds,near_hit-distance+0.75f);
}
static inline float g_surface_fade(GVec3 flat, GCamera cam) {
    return g_smoothstep(0.0f,0.06f,g_horizon(flat,cam));
}

/* Translation matches HOI4GlobeProjectWorld, before applying the native VP matrix. */
static inline GVec3 g_projected_sphere_world(GVec3 sphere_position, GCamera cam) {
    return g_add(sphere_position,g_scale(g_forward(cam),g_view_pullback(cam)));
}
static inline GVec3 g_projected_world(GVec3 flat, GCamera cam) {
    return g_projected_sphere_world(g_position(flat,cam),cam);
}
/* Pass clip.z/clip.w and original clip.w; this returns the remapped NDC depth. */
static inline float g_far_depth(float depth, float clip_w) {
    if (clip_w > 0.00001f && depth > 0.995f) {
        float tail = depth-0.995f;
        return 0.995f+tail/(1.0f+200.0f*tail);
    }
    return depth;
}

#endif /* HOI4_GLOBE_GEOMETRY_H */
