"""Geographic Earth color backdrop and thin atmosphere behind the game map mesh."""

def patch_sky(text):
    anchor = '"standardfuncsgfx.fxh"'
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor + '\n\t"hoi4_globe.fxh"', 1)
    start = text.index('float3 color = texCUBE(')
    end = text.index('return float4( color, 1.0f );', start) + len('return float4( color, 1.0f );')
    body = r'''// The source artwork stops short of both poles. Sample the verified
            // geographic cube behind that cropped map and native terrain culling.
            float3 ray = normalize( Input.pos - vCamPos );
            float3 eye = HOI4GlobeCameraPosition();
            float3 center = HOI4GlobeCenter();
            float radius = HOI4GlobeRadius();
            float3 offset = eye - center;
            float along = dot( offset, ray );
            float closest = max( 0.0f, -along );
            float miss = length( offset + ray * closest );
            float3 color = float3( 0.0015f, 0.0030f, 0.0080f );
            float halo = exp( -max( 0.0f, miss - radius ) / ( radius * 0.013f ) )
                * ( 1.0f - smoothstep( radius * 1.04f, radius * 1.08f, miss ) );
            if ( closest > 0.0f && miss >= radius )
                color += float3( 0.022f, 0.11f, 0.28f ) * halo * 0.60f;

            float discriminant = along * along - dot( offset, offset ) + radius * radius;
            if ( discriminant >= 0.0f && along < 0.0f )
            {
                float distance = -along - sqrt( max( 0.0f, discriminant ) );
                if ( distance > 0.0f )
                {
                    float3 radial = normalize( offset + ray * distance );
                    float2 focus = HOI4GlobeFocus();
                    float focusLatitude = HOI4GlobeLatitude( focus.y );
                    float focusLongitude = ( focus.x - 2793.0f ) / radius;
                    // Undo the focus-oriented globe basis without clamping polar latitude.
                    // Cube directions are +Y north, +Z Greenwich and +X 90 degrees east.
                    float north = radial.y * sin( focusLatitude ) + radial.z * cos( focusLatitude );
                    float meridian = radial.y * cos( focusLatitude ) - radial.z * sin( focusLatitude );
                    float3 geographic = float3(
                        radial.x * cos( focusLongitude ) + meridian * sin( focusLongitude ),
                        north,
                        meridian * cos( focusLongitude ) - radial.x * sin( focusLongitude ) );
                    float3 material = texCUBE( ReflectionCubeMap, geographic ).rgb;
                    float3 view = -ray;
                    float3 sun = normalize( view + float3( -0.50f, 0.45f, -0.18f ) );
                    float rim = pow( 1.0f - saturate( dot( radial, view ) ), 4.0f );
                    color = material * ( 0.58f + 0.42f * saturate( dot( radial, sun ) ) );
                    color = color * ( 1.0f - rim * 0.18f )
                        + float3( 0.017f, 0.072f, 0.19f ) * rim * 0.65f;
                }
            }
            return float4( saturate( color ), 1.0f );'''
    return text[:start] + body + text[end:]
