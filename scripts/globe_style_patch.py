"""Targeted visual material overrides for the HOI4 globe rendering prototype.

Call patch_style(relative_path, shader_text) after the spherical projection pass.
Does not mutate uniforms, texture coordinates, samplers, or shader interfaces.
The original shaders remain the source of terrain, height, and seasonal textures.
"""

import re


STYLE_SUMMARY = {
    "terrain": "Native gradient and occupation colors retain 80% close and 90% orbital weight; uncolored map regions keep natural biome materials.",
    "ocean": "Deep blue water and a matching submerged-terrain fallback prevent coarse spherical water geometry exposing pale terrain colormap water.",
    "lighting": "DEM height normals follow adaptive close-range relief, with stronger local ridge lighting and a restrained atmospheric rim.",
    "labels": "Country names preserve native transparency at every camera height; horizon fading and far-hemisphere clipping remain.",
    "borders": "Ordinary map outlines fade at orbital zoom while selected borders remain legible.",
    "modified_pixel_entrypoints": [
        "pdxmap.shader:PixelShaderTerrain",
        "pdxmap.shader:PixelShaderUnderwater",
        "pdxwater.shader:PixelShader",
        "mapname.shader:PixelShader",
        "border.shader:PixelShader",
    ],
}


def _once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise ValueError(f"Globe style {label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def _replace_function(text, signature, replacement, label):
    matches = list(re.finditer(signature, text))
    if len(matches) != 1:
        raise ValueError(f"Globe style {label}: expected one function, found {len(matches)}")
    match = matches[0]
    opening = text.index("{", match.end())
    depth = 0
    for offset in range(opening, len(text)):
        if text[offset] == "{":
            depth += 1
        elif text[offset] == "}":
            depth -= 1
            if depth == 0:
                return text[:match.start()] + replacement + text[offset + 1:]
    raise ValueError(f"Globe style {label}: unbalanced function")


WATER_MAIN = r'''float4 main( VS_OUTPUT_WATER Input ) : PDX_COLOR
        {
            clip( HOI4GlobeSurfaceVisibility( Input.pos ) );
            // Preserve the stock coast mask and its existing map texture UVs.
            float waterHeight = MultiSampleTexX( HeightTexture, Input.uv ) / ( 95.7f / 255.0f );
            float waterShore = saturate( ( waterHeight - 0.954f ) * 25.0f );
            float globeOrbital = smoothstep( 110.0f, 350.0f, vCamPos.y );
            float globeDepth = saturate( ( 0.965f - waterHeight ) * 20.0f );
            float3 globeOcean = lerp( float3( 0.014f, 0.100f, 0.145f ),
                float3( 0.0035f, 0.028f, 0.066f ), smoothstep( 0.0f, 0.55f, globeDepth ) );

            float3 globeWorld = HOI4GlobePosition( Input.pos );
            float3 globeRadial = HOI4GlobeSurfaceNormal( Input.pos );
            float3 globeView = normalize( HOI4GlobeCameraPosition() - globeWorld );
            float3 globeNormal = globeRadial;
        #ifndef LOW_END_GFX
            // The detailed wave normals disappear in orbit rather than becoming screen noise.
            float2 globeWaveB;
            float3 globeWaveM;
            float3 globeWaveNormal;
            SampleWater( Input.uv, vTime_HalfPixelOffset.x, globeWaveB, globeWaveM,
                globeWaveNormal, LeanTexture1, LeanTexture2 );
            float3 globeEast = normalize( HOI4GlobePosition( Input.pos + float3( 1.0f, 0.0f, 0.0f ) ) - globeWorld );
            float3 globeNorth = normalize( HOI4GlobePosition( Input.pos + float3( 0.0f, 0.0f, 1.0f ) ) - globeWorld );
            float globeDetail = 0.13f * ( 1.0f - globeOrbital );
            globeNormal = normalize( globeRadial + globeEast * globeWaveNormal.x * globeDetail
                + globeNorth * globeWaveNormal.z * globeDetail );
        #endif

            float4 globeSnowData = GetMudSnowColor( Input.pos, SnowMudTexture );
            float globeIce = saturate( ( GetSnow( globeSnowData ) - 0.62f ) * 2.2f )
                * smoothstep( 0.75f, 0.97f, Input.pos.z / MAP_SIZE_Y );
            globeOcean = lerp( globeOcean, float3( 0.47f, 0.57f, 0.65f ), globeIce * 0.8f );

            float3 globeSun = normalize( globeView + float3( -0.50f, 0.45f, -0.18f ) );
            float globeDaylight = 0.58f + 0.42f * saturate( dot( globeRadial, globeSun ) );
            float globeGlint = pow( saturate( dot( reflect( -globeSun, globeNormal ), globeView ) ), 90.0f )
                * 0.045f * ( 1.0f - globeIce );
            float globeRim = pow( 1.0f - saturate( dot( globeRadial, globeView ) ), 4.0f );
            float3 globeColor = globeOcean * globeDaylight + float3( 0.70f, 0.84f, 1.0f ) * globeGlint;
            globeColor = globeColor * ( 1.0f - globeRim * 0.18f )
                + float3( 0.017f, 0.072f, 0.19f ) * globeRim * 0.65f;
            return float4( saturate( globeColor ), 1.0f - waterShore );
        }'''


UNDERWATER_MAIN = r'''float4 main( VS_OUTPUT_TERRAIN Input ) : PDX_COLOR
        {
            clip( WATER_HEIGHT - Input.prepos.y + TERRAIN_WATER_CLIP_HEIGHT );
            clip( HOI4GlobeSurfaceVisibility( Input.prepos ) );
            // Calm coastal substrate also covers the narrow alpha transition in the water pass.
            float globeDepth = saturate( ( WATER_HEIGHT - Input.prepos.y ) / 0.6f );
            float3 globeOcean = lerp( float3( 0.018f, 0.092f, 0.128f ),
                float3( 0.004f, 0.026f, 0.060f ), globeDepth );
            float3 globeRadial = HOI4GlobeSurfaceNormal( Input.prepos );
            float3 globeView = normalize( HOI4GlobeCameraPosition() - HOI4GlobePosition( Input.prepos ) );
            float3 globeSun = normalize( globeView + float3( -0.50f, 0.45f, -0.18f ) );
            float globeRim = pow( 1.0f - saturate( dot( globeRadial, globeView ) ), 4.0f );
            globeOcean *= 0.58f + 0.42f * saturate( dot( globeRadial, globeSun ) );
            globeOcean += float3( 0.017f, 0.072f, 0.19f ) * globeRim * 0.65f;
            return float4( saturate( globeOcean ), 1.0f );
        }'''


def patch_style(relative, text):
    """Return version-checked edits; unowned shaders pass through unchanged."""
    path = str(relative).replace("\\", "/").lower()
    text = text.replace("\r\n", "\n")
    if path == "gfx/fx/pdxmap.shader":
        text = _once(text,
            "//clip( Input.prepos.y + TERRAIN_WATER_CLIP_HEIGHT - WATER_HEIGHT );",
            "//clip( Input.prepos.y + TERRAIN_WATER_CLIP_HEIGHT - WATER_HEIGHT );\n"
            "            clip( HOI4GlobeSurfaceVisibility( Input.prepos ) );",
            "terrain map bounds and horizon")
        text = _once(text, "float4 TerrainColor = tex2D( TerrainColorTint, Input.uv2 );",
            "float4 TerrainColor = tex2D( TerrainColorTint, Input.uv2 );\n"
            "            float globeOrbital = smoothstep( 110.0f, 350.0f, vCamPos.y );",
            "terrain orbital fade")
        text = _once(text, "// Gradient Borders", r'''// Globe materials: use the continuous native biome colormap in orbit.
            // Keep some stock local terrain texture and seasonal snow at close range.
            float3 globeSatelliteBase = max( TerrainColor.rgb * float3( 0.91f, 1.03f, 0.90f ),
                float3( 0.006f, 0.009f, 0.004f ) );
            float globeSnow = min( 0.65f, vSnowAlpha
                + saturate( ( GetSnow( vMudSnow ) - 0.70f ) * 3.0f ) * 0.25f );
            globeSatelliteBase = lerp( globeSatelliteBase, float3( 0.58f, 0.62f, 0.65f ), globeSnow );
            diffuse.rgb = lerp( diffuse.rgb, globeSatelliteBase, 0.35f + 0.55f * globeOrbital );
            float3 globeNaturalBase = diffuse.rgb;

            // Gradient Borders''', "terrain natural material")
        text = _once(text,
            "secondary_color_mask( diffuse.rgb, normal, Input.uv2, ProvinceSecondaryColorMap, vBloomAlpha );",
            "secondary_color_mask( diffuse.rgb, normal, Input.uv2, ProvinceSecondaryColorMap, vBloomAlpha );\n"
            "            // Respect native mapmode gradient colors and occupation stripes.\n"
            "            // Uncolored channels leave the natural biome base unchanged.\n"
            "            diffuse.rgb = lerp( globeNaturalBase, diffuse.rgb, lerp( 0.80f, 0.90f, globeOrbital ) );",
            "readable native mapmode colors")
        text = _once(text, "DebugReturn(vOut, lightingProperties, fShadowTerm);", r'''// Lighting uses the actual sphere, not the original flat heightfield camera.
            float3 globeWorld = HOI4GlobePosition( Input.prepos );
            float3 globeRadial = HOI4GlobeSurfaceNormal( Input.prepos );
            float3 globeView = normalize( HOI4GlobeCameraPosition() - globeWorld );
            float3 globeEast = normalize( HOI4GlobePosition( Input.prepos + float3( 1.0f, 0.0f, 0.0f ) ) - globeWorld );
            float3 globeNorth = normalize( HOI4GlobePosition( Input.prepos + float3( 0.0f, 0.0f, 1.0f ) ) - globeWorld );
        #ifdef LOW_END_GFX
            float3 globeNormal = globeRadial;
        #else
            // Light the regenerated DEM heightfield; atlas normal details would add artificial bumps.
            float3 globeHeightNormal = normalize( tex2D( HeightNormal, Input.uv2 ).rbg - 0.5f );
            // Correct flat heightfield derivatives for the physical Miller tangent scale.
            float globeLatitude = HOI4GlobeLatitude( Input.prepos.z );
            float globeEastScale = max( 0.25f, cos( globeLatitude ) );
            float globeNorthScale = max( 0.25f, cos( globeLatitude * 0.8f ) );
            // Match camera-dependent physical relief rather than inventing atlas bumps.
            float globeRelief = lerp( 0.90f, 0.55f, globeOrbital ) * HOI4GlobeReliefScale();
            float3 globeNormal = normalize( globeRadial * globeHeightNormal.y
                + globeEast * ( globeHeightNormal.x / globeEastScale ) * globeRelief
                + globeNorth * ( globeHeightNormal.z / globeNorthScale ) * globeRelief );
        #endif
            float3 globeSun = normalize( globeView + float3( -0.50f, 0.45f, -0.18f ) );
            float globeLightContrast = lerp( 0.50f, 0.38f, globeOrbital );
            float globeDaylight = 1.0f - globeLightContrast
                + globeLightContrast * saturate( dot( globeNormal, globeSun ) );
            float globeRim = pow( 1.0f - saturate( dot( globeRadial, globeView ) ), 4.0f );
            float3 globeSatelliteLit = diffuse.rgb * globeDaylight * ( 1.0f - globeRim * 0.20f )
                + float3( 0.017f, 0.072f, 0.19f ) * globeRim * 0.65f;
            vOut = lerp( vOut, globeSatelliteLit, 0.75f + 0.20f * globeOrbital );
            // Water's coarse flat mesh can become chords below this finer seabed.
            // Match the globe water material wherever that submerged terrain remains visible.
            float globeWet = 1.0f - smoothstep( WATER_HEIGHT - 0.05f, WATER_HEIGHT + 0.08f, Input.prepos.y );
            float globeOceanDepth = saturate( ( WATER_HEIGHT - Input.prepos.y - 0.08f ) / 0.52f );
            float3 globeOceanBase = lerp( float3( 0.014f, 0.100f, 0.145f ),
                float3( 0.0035f, 0.028f, 0.066f ), globeOceanDepth );
            float3 globeOceanLit = globeOceanBase * ( 0.58f + 0.42f * saturate( dot( globeRadial, globeSun ) ) );
            globeOceanLit = globeOceanLit * ( 1.0f - globeRim * 0.18f )
                + float3( 0.017f, 0.072f, 0.19f ) * globeRim * 0.65f;
            vOut = lerp( vOut, globeOceanLit, globeWet );
            vOut = saturate( vOut );
            DebugReturn(vOut, lightingProperties, fShadowTerm);''', "terrain sphere lighting")
        text = _replace_function(text,
            r"float4\s+main\(\s*VS_OUTPUT_TERRAIN\s+Input\s*\)\s*:\s*PDX_COLOR(?=\s*\{\s*clip\(\s*WATER_HEIGHT)",
            UNDERWATER_MAIN, "underwater material")
    elif path == "gfx/fx/pdxwater.shader":
        text = _replace_function(text,
            r"float4\s+main\(\s*VS_OUTPUT_WATER\s+Input\s*\)\s*:\s*PDX_COLOR",
            WATER_MAIN, "water material")
    elif path == "gfx/fx/mapname.shader":
        text = _once(text, "vSample.a *= Transp_OffsetX.x;// * vFade;", r'''float3 globeRadial = HOI4GlobeSurfaceNormal( v.vPrepos );
            clip( HOI4GlobeOverlayVisibility( v.vPrepos ) );
            float3 globeView = normalize( HOI4GlobeCameraPosition() - HOI4GlobePosition( v.vPrepos ) );
            float globeFacing = dot( globeRadial, globeView );
            clip( globeFacing - 0.04f );
            float globeNameFade = smoothstep( 0.06f, 0.28f, globeFacing );
            vSample.a *= Transp_OffsetX.x * globeNameFade;''', "country name fade")
    elif path == "gfx/fx/border.shader":
        text = _once(text,
            "float4 vColor = tex2D( BorderDiffuse, float2( Input.uv.y * BORDER_TILE, Input.uv.x ) );",
            "clip( HOI4GlobeSurfaceVisibility( Input.pos ) );\n"
            "            float4 vColor = tex2D( BorderDiffuse, float2( Input.uv.y * BORDER_TILE, Input.uv.x ) );",
            "border map bounds and horizon")
        text = _once(text,
            "return float4( vColor.rgb, max( vColor.a, vPulseFactor - 0.2f ) * vTime_Transparency.y );",
            r'''float globeBorderDetail = 1.0f - smoothstep( 70.0f, 330.0f, vCamPos.y );
            float globeBorderFade = lerp( 0.025f, 1.0f, max( globeBorderDetail, saturate( vSelectionColor.a ) ) );
            return float4( vColor.rgb, max( vColor.a, vPulseFactor - 0.2f ) * vTime_Transparency.y * globeBorderFade );''',
            "ordinary border fade")
    return text
