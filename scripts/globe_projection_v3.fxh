# Globe view v3: shared visibility, spherical background inverse, stable overview.
# Source map coordinates stay unchanged in shader varyings and province textures.
Code
[[
static const float HOI4_GLOBE_PI = 3.14159265358979323846f;
static const float HOI4_GLOBE_OVERVIEW_PULLBACK = 0.50f;
static const float HOI4_GLOBE_EQUATOR_FRACTION = 672.0f / 2048.0f;

float HOI4GlobeRadius()
{
    return MAP_SIZE_X / (2.0f * HOI4_GLOBE_PI);
}

float3 HOI4GlobeCameraForward()
{
    return vCamLookAtDir / max(length(vCamLookAtDir), 0.00001f);
}

float2 HOI4GlobeFocus()
{
    float3 forward = HOI4GlobeCameraForward();
    float travel = max(0.0f, vCamPos.y - WATER_HEIGHT) / max(0.05f, -forward.y);
    float2 focus = vCamPos.xz + forward.xz * travel;
    focus.y = clamp(focus.y, 0.0f, MAP_SIZE_Y);
    return focus;
}

float HOI4GlobeLatitude(float mapNorth)
{
    // The map has no physical poles. Natural-scale Miller is an approximate inverse
    // of its artwork: radius preserves equatorial scale, landmark centroids fit672.
    // Stock SOUTH_POLE/NORTH_POLE lighting offsets are not geodetic latitude bounds.
    float equator = HOI4_GLOBE_EQUATOR_FRACTION * MAP_SIZE_Y;
    float projected = (clamp(mapNorth, 0.0f, MAP_SIZE_Y) - equator) / HOI4GlobeRadius();
    return 2.5f * atan(exp(0.8f * projected)) - 0.625f * HOI4_GLOBE_PI;
}

float3 HOI4GlobeCenter()
{
    float2 focus = HOI4GlobeFocus();
    return float3(focus.x, WATER_HEIGHT - HOI4GlobeRadius(), focus.y);
}

float3 HOI4GlobeSurfaceNormal(float3 flatPosition)
{
    float2 focus = HOI4GlobeFocus();
    float latitude = HOI4GlobeLatitude(flatPosition.z);
    float focusLatitude = HOI4GlobeLatitude(focus.y);
    float longitude = (flatPosition.x - focus.x) * (2.0f * HOI4_GLOBE_PI / MAP_SIZE_X);
    float sinLat = sin(latitude);
    float cosLat = cos(latitude);
    float sinFocus = sin(focusLatitude);
    float cosFocus = cos(focusLatitude);
    float cosLon = cos(longitude);
    return normalize(float3(cosLat * sin(longitude),
        cosLat * cosLon * cosFocus + sinLat * sinFocus,
        sinLat * cosFocus - cosLat * cosLon * sinFocus));
}

float HOI4GlobeReliefScale()
{
    float cameraAltitude = max(0.0f, vCamPos.y - WATER_HEIGHT);
    return lerp(1.85f, 1.0f, smoothstep(180.0f, 650.0f, cameraAltitude));
}

float3 HOI4GlobePosition(float3 flatPosition)
{
    float altitude = flatPosition.y - WATER_HEIGHT;
    if (altitude > 0.0f)
        altitude *= HOI4GlobeReliefScale();
    return HOI4GlobeCenter() + HOI4GlobeSurfaceNormal(flatPosition) * (HOI4GlobeRadius() + altitude);
}

float3 HOI4GlobeObjectPosition(float3 flatPosition, float baseSurfaceHeight)
{
    // Optional world-mesh variant: move the base with terrain relief while retaining
    // the local tree/building/vehicle model height instead of stretching it vertically.
    float baseAltitude = baseSurfaceHeight - WATER_HEIGHT;
    if (baseAltitude > 0.0f)
        baseAltitude *= HOI4GlobeReliefScale();
    float altitude = baseAltitude + flatPosition.y - baseSurfaceHeight;
    return HOI4GlobeCenter() + HOI4GlobeSurfaceNormal(flatPosition) * (HOI4GlobeRadius() + altitude);
}

float HOI4GlobeViewPullback()
{
    float height = max(0.0f, vCamPos.y - WATER_HEIGHT);
    float3 forward = HOI4GlobeCameraForward();
    float focusDistance = height / max(0.05f, -forward.y);
    // Do not force a large orbital distance onto close-range terrain views.
    return focusDistance * HOI4_GLOBE_OVERVIEW_PULLBACK * smoothstep(180.0f, 650.0f, height);
}

float3 HOI4GlobeCameraPosition()
{
    // Effective eye for atmosphere/radial lighting; native camera state is unchanged.
    return vCamPos - HOI4GlobeCameraForward() * HOI4GlobeViewPullback();
}

float HOI4GlobeMapBounds(float3 flatPosition)
{
    // Wrapping x is intentional. Only reject north/south buffer and skirt geometry.
    // A small tolerance retains triangles stitching the exact map border.
    return min(flatPosition.z + 2.0f, MAP_SIZE_Y + 2.0f - flatPosition.z);
}

float HOI4GlobeHorizon(float3 flatPosition)
{
    float3 view = HOI4GlobeCameraPosition() - HOI4GlobePosition(flatPosition);
    view /= max(length(view), 0.00001f);
    return dot(HOI4GlobeSurfaceNormal(flatPosition), view);
}

float HOI4GlobeSurfaceVisibility(float3 flatPosition)
{
    // clip(HOI4GlobeSurfaceVisibility(flat)) in world terrain/water/border pixels.
    // Do not apply this to unrelated HUD or model-preview shaders.
    return min(HOI4GlobeMapBounds(flatPosition), HOI4GlobeHorizon(flatPosition));
}

float HOI4GlobeOverlayVisibility(float3 flatPosition)
{
    float bounds = HOI4GlobeMapBounds(flatPosition);
    if (bounds < 0.0f)
        return bounds;
    // Surface/submerged overlays use orientation; a sea-level sphere would falsely
    // occlude deliberately submerged coast/river pixels.
    if (flatPosition.y <= WATER_HEIGHT + 0.02f)
        return min(bounds, HOI4GlobeHorizon(flatPosition));
    float3 overlayPosition = HOI4GlobePosition(flatPosition);
    float3 eye = HOI4GlobeCameraPosition();
    float3 delta = overlayPosition - eye;
    float distance = length(delta);
    float3 ray = delta / max(distance, 0.00001f);
    float3 offset = eye - HOI4GlobeCenter();
    float along = dot(offset, ray);
    float bodyRadius = HOI4GlobeRadius() - 0.25f;
    float discriminant = along * along - dot(offset, offset) + bodyRadius * bodyRadius;
    if (discriminant < 0.0f)
        return min(bounds, 1.0f);
    float nearHit = -along - sqrt(max(0.0f, discriminant));
    if (nearHit <= 0.0f)
        return min(bounds, 1.0f);
    // A raised ship/building can legitimately protrude above the sea horizon.
    // Discard only when the planet is in front of it; tolerate sub-unit bias noise.
    return min(bounds, nearHit - distance + 0.75f);
}

float HOI4GlobeSurfaceFade(float3 flatPosition)
{
    // For alpha-blended map overlays, use a narrow horizon fade after visibility.
    return smoothstep(0.0f, 0.06f, HOI4GlobeHorizon(flatPosition));
}

float4 HOI4GlobeRaySurface(float3 worldRay)
{
    float3 ray = worldRay / max(length(worldRay), 0.00001f);
    float3 eye = HOI4GlobeCameraPosition();
    float3 offset = eye - HOI4GlobeCenter();
    float along = dot(offset, ray);
    float radius = HOI4GlobeRadius();
    float discriminant = along * along - dot(offset, offset) + radius * radius;
    if (discriminant < 0.0f)
        return float4(0.0f, 0.0f, 0.0f, -1.0f);
    float distance = -along - sqrt(max(0.0f, discriminant));
    if (distance <= 0.0f || length(worldRay) <= 0.00001f)
        return float4(0.0f, 0.0f, 0.0f, -1.0f);
    return float4(eye + ray * distance, distance);
}

float3 HOI4GlobeMapFromSurface(float3 spherePosition)
{
    // Inverse used by a full-screen sphere color fallback or future native picking.
    // Return north/z unclamped so the caller can identify genuinely absent polar art.
    float3 radial = spherePosition - HOI4GlobeCenter();
    radial /= max(length(radial), 0.00001f);
    float2 focus = HOI4GlobeFocus();
    float focusLatitude = HOI4GlobeLatitude(focus.y);
    float sf = sin(focusLatitude);
    float cf = cos(focusLatitude);
    float latitude = asin(clamp(radial.y * sf + radial.z * cf, -1.0f, 1.0f));
    float relativeLongitude = atan2(radial.x, radial.y * cf - radial.z * sf);
    float radius = HOI4GlobeRadius();
    float mapX = focus.x + relativeLongitude * radius;
    mapX -= floor(mapX / MAP_SIZE_X) * MAP_SIZE_X;
    float projected = 1.25f * log(max(0.00001f, tan(0.25f * HOI4_GLOBE_PI + 0.4f * latitude)));
    float mapNorth = HOI4_GLOBE_EQUATOR_FRACTION * MAP_SIZE_Y + radius * projected;
    return float3(mapX, WATER_HEIGHT, mapNorth);
}

float4 HOI4GlobeFarDepth(float4 clipPosition)
{
    if (clipPosition.w > 0.00001f)
    {
        float depth = clipPosition.z / clipPosition.w;
        if (depth > 0.995f)
        {
            // The overview eye can exceed the engine's flat-world far distance.
            // Monotonic tail compression retains near precision and depth ordering.
            float tail = depth - 0.995f;
            clipPosition.z = clipPosition.w * (0.995f + tail / (1.0f + 200.0f * tail));
        }
    }
    return clipPosition;
}

float4 HOI4GlobeProjectWorld(float3 spherePosition)
{
    // Moving all rendered geometry forward is equivalent to moving the camera back.
    // A uniform world translation preserves the original projection aspect ratio.
    spherePosition += HOI4GlobeCameraForward() * HOI4GlobeViewPullback();
    return HOI4GlobeFarDepth(mul(ViewProjectionMatrix, float4(spherePosition, 1.0f)));
}

float4 HOI4GlobeProject(float4 flatPosition)
{
    float inverseW = 1.0f / max(abs(flatPosition.w), 0.00001f);
    return HOI4GlobeProjectWorld(HOI4GlobePosition(flatPosition.xyz * inverseW));
}
]]
