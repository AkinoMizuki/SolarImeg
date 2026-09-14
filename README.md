# SolarImeg(SOHO)

https://akinomizuki.github.io/SolarImeg/latest.jpg

https://akinomizuki.github.io/SolarImeg/latest2.jpg

https://akinomizuki.github.io/SolarImeg/EIT171.jpg

https://akinomizuki.github.io/SolarImeg/LASCO_C2.jpg

# Earth Weather

https://akinomizuki.github.io/SolarImeg/weather/cloud_previous.png

https://akinomizuki.github.io/SolarImeg/weather/cloud_current.png

https://akinomizuki.github.io/SolarImeg/weather/wind_surface.png

https://akinomizuki.github.io/SolarImeg/weather/wind_850hpa.png

https://akinomizuki.github.io/SolarImeg/weather/wind_700hpa.png

https://akinomizuki.github.io/SolarImeg/weather/metadata.json

## 風向・風速テクスチャの用途

GFS の UGRD / VGRD から、VRChat / Unity の Shader で直接利用できる RGBA データテクスチャを生成します。

- `wind_surface.png` : 地上 10 m 風。風向・風速の矢印表示用
- `wind_850hpa.png` : 850 hPa 風。低層雲の移流用候補
- `wind_700hpa.png` : 700 hPa 風。中層雲の移流用候補

各テクスチャは 1440 x 720 の正距円筒図法です。
経度は左端が -180°、中央が 0°（Greenwich）、右端が +180°になるように並べています。
画像上では上端が北極、下端が南極です。

## RGBA のデータ形式

風向は角度ではなく正規化ベクトルで格納しています。
これにより 359° と 1° の境界でもテクスチャ補間で方向が破綻しにくくなります。

| Channel | 内容 |
| --- | --- |
| R | 東西方向の正規化ベクトル X。-1 ～ +1 を 0 ～ 255 に変換 |
| G | 南北方向の正規化ベクトル Y。-1 ～ +1 を 0 ～ 255 に変換 |
| B | 風速。0 ～ 128 m/s を 0 ～ 255 に変換 |
| A | 有効データ。255 = 有効、0 = 欠損 |

元の GFS データでは、U が東西風、V が南北風です。
生成時に以下のように正規化しています。

```text
speed = sqrt(U * U + V * V)
dirX = U / speed
dirY = V / speed
```

## Shader での復元例

```hlsl
float4 windSample = tex2D(_WindTex, uv);

float2 windDir = windSample.rg * 2.0 - 1.0;
float windSpeed = windSample.b * 128.0;
float valid = windSample.a;

if (dot(windDir, windDir) > 0.000001)
{
    windDir = normalize(windDir);
}
```

`windDir.x` は東西方向、`windDir.y` は南北方向です。

矢印の回転角へ変換する場合の基本形は以下です。

```hlsl
float angle = atan2(windDir.y, windDir.x);
```

実際の矢印画像が最初に右・上など、どちらを向いて作られているかによって `angle` に 90° / 180° などのオフセットを加えてください。

## 風速による色分け

`windSpeed` を使って Shader 側で色を変更できます。
想定している表現は弱風から強風に向けて、例えば以下です。

```text
青 → シアン → 緑 → 黄 → オレンジ → 赤 → 紫
```

色分けは画像側へ焼き込まず、Shader 側で行います。
そのため風速レンジや色境界は Unity の Material から自由に調整できます。

## 雲の移流に使う場合

雲には `wind_850hpa.png` または `wind_700hpa.png` を使用します。

```hlsl
float4 windSample = tex2D(_WindTex, uv);
float2 windDir = normalize(windSample.rg * 2.0 - 1.0);
float windSpeed = windSample.b * 128.0;

float phase = frac(_Time.y * _CloudFlowSpeed);
float2 cloudUV = uv - windDir * windSpeed * phase * _CloudMoveScale;
```

これは観測画像そのものを長時間移動させ続けるためではなく、次の雲画像更新までの短時間補間用です。
`cloud_previous.png` と `cloud_current.png` の時間補間と組み合わせて使用します。

Sphere の UV 配置によって南北方向が逆に見える場合は、Shader 側で `windDir.y` または UV の V を反転して合わせてください。

## 更新周期

Earth Weather は毎時 20 分に更新します。
既存の SOHO・名古屋市科学館・`clouds.jpg`・`specular.jpg` は従来どおり 3 時間周期で更新します。

`metadata.json` には GFS の run 時刻、forecast hour、valid 時刻、風速の最大エンコード値などを記録します。

# SolarImeg(名古屋市科学館からの太陽像)
https://akinomizuki.github.io/SolarImeg/now_wh.jpg

https://akinomizuki.github.io/SolarImeg/now_ha.jpg

# 名古屋市科学館からの太陽像
http://www.ncsm.city.nagoya.jp/astro/sun/

# 3時間更新の地球の雲
https://akinomizuki.github.io/SolarImeg/clouds.jpg

https://akinomizuki.github.io/SolarImeg/specular.jpg

# live-cloud-maps
https://github.com/matteason/live-cloud-maps?tab=readme-ov-file
