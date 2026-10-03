// Minimal URP lit shader: main directional light (Lambert) + ambient, no shadows, no keywords.
// The stock URP/Lit shader depends on multi_compile variants that a WebGL build can strip when the
// lighting is created at runtime, which leaves the geometry invisible; this shader has exactly one variant.
Shader "AakashDrishti/SimpleLit"
{
    Properties
    {
        _BaseMap ("Base Map", 2D) = "white" {}
        _BaseColor ("Base Color", Color) = (1, 1, 1, 1)
        _EmissionColor ("Emission", Color) = (0, 0, 0, 1)
        // 0 = ignore mesh vertex colours (terrain). 1 = buildings/objects: vertex rgb is the surface colour and
        // vertex alpha says how much of the base map to mix in (1 = photographed roof, 0 = flat colour).
        _UseVertexColor ("Use vertex colour", Float) = 0
    }
    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Geometry" "RenderPipeline" = "UniversalPipeline" }
        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }
            ZWrite On
            Cull Back

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            TEXTURE2D(_BaseMap);
            SAMPLER(sampler_BaseMap);

            CBUFFER_START(UnityPerMaterial)
                float4 _BaseMap_ST;
                half4 _BaseColor;
                half4 _EmissionColor;
                half _UseVertexColor;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS : NORMAL;
                float2 uv : TEXCOORD0;
                half4 color : COLOR;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 normalWS : TEXCOORD0;
                float2 uv : TEXCOORD1;
                half4 color : TEXCOORD2;
            };

            Varyings vert(Attributes input)
            {
                Varyings output;
                output.positionCS = TransformObjectToHClip(input.positionOS.xyz);
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                output.uv = TRANSFORM_TEX(input.uv, _BaseMap);
                output.color = input.color;
                return output;
            }

            half4 frag(Varyings input) : SV_Target
            {
                half3 tex = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, input.uv).rgb;
                half3 albedo = tex * _BaseColor.rgb;
                if (_UseVertexColor > 0.5h)
                {
                    // Mesh vertex colours are stored as sRGB bytes but the project renders in Linear colour space
                    // (materials convert their Color properties, vertex data is not converted), so do it here.
                    half3 vc = pow(max(input.color.rgb, 0.0001h), 2.2h);
                    albedo = lerp(vc, tex * vc, input.color.a) * _BaseColor.rgb;
                }
                half3 n = normalize(input.normalWS);
                Light light = GetMainLight();
                half3 diffuse = light.color * saturate(dot(n, light.direction));
                half3 ambient = SampleSH(n);
                // The base map is a real aerial/satellite photo -- it already carries its own exposure and
                // shading. Re-lighting it with a full directional + ambient term (which can sum above 1) has
                // no tonemapping downstream (bare runtime camera, no post-processing volume), so bright pixels
                // hard-clip to white in the backbuffer: this is what reads as "washed out" colour. Clamping
                // the light term to [0, 1] keeps the terrain's own imagery colours intact while still shading
                // relief (slopes facing away from the sun read darker).
                half3 lightTerm = saturate(diffuse + ambient);
                return half4(albedo * lightTerm + _EmissionColor.rgb, 1);
            }
            ENDHLSL
        }
    }
}
