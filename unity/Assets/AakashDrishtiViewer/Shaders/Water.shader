// Flood water surface: translucent blue with slow travelling ripples and glints, drawn over the terrain
// (ZTest LEqual, no depth write) so ground above the waterline stays in front. Single variant.
Shader "AakashDrishti/Water"
{
    Properties
    {
        _DeepColor ("Deep", Color) = (0.06, 0.28, 0.55, 1)
        _ShallowColor ("Shallow", Color) = (0.22, 0.55, 0.85, 1)
        _Alpha ("Opacity", Range(0, 1)) = 0.62
        _Scale ("Ripple Scale", Float) = 0.06
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent" "RenderPipeline" = "UniversalPipeline" }
        Pass
        {
            Name "Water"
            Tags { "LightMode" = "UniversalForward" }
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            ZTest LEqual
            Cull Off

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                half4 _DeepColor;
                half4 _ShallowColor;
                half _Alpha;
                float _Scale;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 positionWS : TEXCOORD0;
            };

            Varyings vert(Attributes input)
            {
                Varyings output;
                output.positionWS = TransformObjectToWorld(input.positionOS.xyz);
                output.positionCS = TransformWorldToHClip(output.positionWS);
                return output;
            }

            half4 frag(Varyings input) : SV_Target
            {
                float2 p = input.positionWS.xz * _Scale;
                float t = _Time.y;
                float w = sin(p.x * 3.0 + t * 1.1) + sin(p.y * 4.0 - t * 1.4) + sin((p.x + p.y) * 5.0 + t * 1.9) + sin((p.x - p.y) * 7.0 - t * 2.3);
                w = w * 0.125 + 0.5;
                half3 col = lerp(_DeepColor.rgb, _ShallowColor.rgb, w);
                half glint = pow(saturate(w), 9.0) * 0.55;
                return half4(col + glint, saturate(_Alpha * (0.85 + 0.3 * w)));
            }
            ENDHLSL
        }
    }
}
