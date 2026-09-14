# SolarImeg(SOHO)

https://akinomizuki.github.io/SolarImeg/latest.jpg

https://akinomizuki.github.io/SolarImeg/latest2.jpg

https://akinomizuki.github.io/SolarImeg/EIT171.jpg

https://akinomizuki.github.io/SolarImeg/LASCO_C2.jpg

# Earth Weather

Unity / VRChat の地球表示で利用するため、雲・海面スペキュラ・風向風速を定期更新して GitHub Pages から配信します。

## 配信ファイル

- https://akinomizuki.github.io/SolarImeg/weather/cloud_previous.png
- https://akinomizuki.github.io/SolarImeg/weather/cloud_current.png
- https://akinomizuki.github.io/SolarImeg/weather/specular_previous.jpg
- https://akinomizuki.github.io/SolarImeg/weather/specular_current.jpg
- https://akinomizuki.github.io/SolarImeg/weather/wind_surface.png
- https://akinomizuki.github.io/SolarImeg/weather/wind_850hpa.png
- https://akinomizuki.github.io/SolarImeg/weather/wind_700hpa.png
- https://akinomizuki.github.io/SolarImeg/weather/metadata.json

## 雲テクスチャと specular の関係

`weather/cloud_previous.png` / `weather/cloud_current.png` は `live-cloud-maps` の `clouds-alpha.png` をそのまま RGBA 雲テクスチャとして利用します。
`clouds-alpha.png` は既に雲専用に生成された透明 PNG で、RGB が雲の陰影・明るさ、A が雲の不透明度です。そのため SolarImeg 側で地表除去や雲マスクの再抽出は行いません。

Earth Weather では specular も履歴を持ちます。

- `specular_previous.jpg` : `cloud_previous.png` と同じ世代の海面スペキュラ
- `specular_current.jpg` : `cloud_current.png` と同じ世代の海面スペキュラ

`live-cloud-maps` の `specular.jpg` は海面用のベースマップへ反転した雲マップを Multiply 合成して生成されているため、雲がある場所では海面反射が抑えられます。
Cloud と Specular は必ずセットで世代交代し、同じ補間率で previous → current を補間する前提です。

```text
cloud_previous.png    <-> specular_previous.jpg
cloud_current.png     <-> specular_current.jpg
```

Unity 側では想定として以下のように使用します。

```text
EarthSphere
├─ 地表テクスチャ
└─ weather/specular_previous.jpg / specular_current.jpg
   └─ 海面反射。雲のある場所では反射を抑える

CloudSphere
└─ weather/cloud_previous.png / cloud_current.png
   └─ RGB = 雲の陰影
      A   = 雲の不透明度
```

Cloud と Specular は同じ `live-cloud-maps` の世代を使用するため、Shader 側では同じ `_CloudBlend` などの補間値で両方を補間できます。

## Unity / VRChat Shader の使い方

現在の Earth Weather 用 Shader は次の Shader 名を想定しています。

```text
AkinoMizuki/Planets/EarthCloudWeather
```

この Shader は Cloud、風向矢印、Specular の各 Pass を持ち、Material の Toggle で必要な表示だけを有効にします。

### CloudSphere の Material

CloudSphere では次のように割り当てます。

| Shader Property | Texture / 設定 |
| --- | --- |
| `Cloud Previous (RGBA)` | `weather/cloud_previous.png` |
| `Cloud Current (RGBA)` | `weather/cloud_current.png` |
| `Wind Surface (RGBA Data)` | `weather/wind_surface.png` |
| `Wind 850 hPa (RGBA Data)` | `weather/wind_850hpa.png` |
| `Wind 700 hPa (RGBA Data)` | `weather/wind_700hpa.png` |
| `Cloud Enabled` | ON |
| `Wind Arrow Enabled` | ON |
| `Specular Enabled` | OFF |

`Wind Surface` は表示用の風向・風速矢印、`Wind 850 hPa` / `Wind 700 hPa` は雲の短時間移流に使用します。

風向矢印は 1 セルに複数の短い流れ片を持たせ、風向方向へ連続的に移動させます。風速に応じて移動速度と表示色を変え、高緯度では経度方向の表示密度を減らして極付近への集中を抑えます。

動作確認時の初期値例です。

```text
Wind Arrow Density          = 20
Wind Streams Per Cell       = 3
Wind Stream Lateral Spacing = 0.18
Wind Stream Length Scale    = 0.65
Wind Arrow Travel           = 1.8
Wind Arrow Animation Speed  = 0.45
Polar Arrow Fade Start      = 75
Polar Arrow Fade End        = 88
```

### EarthSphere の Specular Material

地表の海面反射には同じ Shader を Specular 用 Material として使用できます。EarthSphere の追加 Material、または地表のすぐ外側に置いた Specular 専用 Sphere に使用します。

| Shader Property | Texture / 設定 |
| --- | --- |
| `Specular Previous` | `weather/specular_previous.jpg` |
| `Specular Current` | `weather/specular_current.jpg` |
| `Cloud Enabled` | OFF |
| `Wind Arrow Enabled` | OFF |
| `Specular Enabled` | ON |

初期値例です。

```text
Specular Strength = 1.5
Specular Power    = 128
Specular Height   = 0.0005
```

Specular は太陽方向 `_SunDir` と視線方向からハイライトを計算し、`specular_previous/current` をマスクとして海面のみ反射させます。雲のある場所は元の specular map 側で反射が抑制されています。

### Previous / Current の補間

Cloud と Specular は同じ世代で更新されるため、両 Material で同じ `_CloudBlend` を使用してください。

```text
0.0 = previous
1.0 = current
```

例えば更新時刻の中間なら `0.5` とし、Cloud と Specular を同じ値で補間します。

雲の風移流は観測画像を長時間移動させ続ける用途ではなく、previous/current の間を自然につなぐ短時間補間用です。長時間にわたり局所風で UV を変形させ続けると画像が歪むため、移流時間には上限を持たせます。

### `_SunDir`

`_SunDir` は地球から見た太陽方向を World Space の方向ベクトルとして設定します。

```hlsl
material.SetVector("_SunDir", sunDirection.normalized);
```

Cloud の昼夜の明るさと EarthSphere の Specular の両方で同じ太陽方向を利用します。

### Texture Import Settings

#### Cloud

`cloud_previous.png` / `cloud_current.png` は表示画像なので通常の Color Texture として使用します。

```text
sRGB (Color Texture) = ON
Alpha                 = 入力画像の Alpha を使用
Filter Mode           = Bilinear
```

#### Wind Data

`wind_surface.png` / `wind_850hpa.png` / `wind_700hpa.png` は画像ではなく数値データとして扱います。

```text
sRGB (Color Texture) = OFF
Compression          = None 推奨
Filter Mode          = Bilinear
Wrap U               = Repeat
Wrap V               = Clamp
```

Wind Texture を sRGB のまま使用する必要がある場合は、Material の `Wind Texture Is sRGB` を ON にして Shader 側で補正します。

#### Specular

`specular_previous.jpg` / `specular_current.jpg` は反射マスクなので Linear Data として扱うことを推奨します。

```text
sRGB (Color Texture) = OFF
Compression          = None 推奨
Filter Mode          = Bilinear
```

sRGB として読み込む場合は `Specular Texture Is sRGB` を ON にしてください。

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

Earth Weather は毎時 20 分に更新チェックします。
`live-cloud-maps` 側の雲・specular が変わっていない場合は、previous/current とその時刻を変更しません。
既存の SOHO・名古屋市科学館・`clouds.jpg`・ルートの `specular.jpg` は従来どおり 3 時間周期で更新します。

`metadata.json` には Cloud/Specular の previous/current 時刻、GFS の run 時刻、forecast hour、valid 時刻、風速の最大エンコード値などを記録します。

## データ元・クレジット

SolarImeg は複数の外部データを取得・加工して配信しています。各元データの権利・利用条件はそれぞれの提供元に従います。

### Cloud / Specular: live-cloud-maps / EUMETSAT

Earth Weather の Cloud / Specular は Matt Eason 氏の `live-cloud-maps` を利用しています。

- Project: https://github.com/matteason/live-cloud-maps
- Cloud source: https://clouds.matteason.co.uk/images/2048x1024/clouds-alpha.png
- Specular source: https://clouds.matteason.co.uk/images/2048x1024/specular.jpg
- Upstream licence: CC0 1.0 Universal（`live-cloud-maps` のコード・画像）

`live-cloud-maps` の雲データの元データは EUMETSAT です。EUMETSAT のデータ利用条件に従い、Cloud / Specular を利用・再配布する場合は次の attribution を表示してください。

> Contains modified EUMETSAT data

EUMETSAT Data Policy / Licensing:

https://www.eumetsat.int/eumetsat-data-licensing

`live-cloud-maps` 作者 Matt Eason 氏への attribution は upstream の CC0 ライセンス上必須ではありませんが、SolarImeg ではデータ生成サービスの提供元としてクレジットします。

### Wind: NOAA / NWS / NCEP GFS via NOMADS

風向・風速は NOAA / National Weather Service / National Centers for Environmental Prediction の Global Forecast System (GFS) を利用しています。

- NOMADS: https://nomads.ncep.noaa.gov/
- GFS products: https://www.nco.ncep.noaa.gov/pmb/products/gfs/
- SolarImeg が使用する GRIB filter: https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl
- Grid: GFS 0.25 degree
- Parameters: `UGRD`, `VGRD`
- Levels: 10 m above ground / 850 hPa / 700 hPa

表示用クレジット例:

> Wind data: NOAA/NWS/NCEP Global Forecast System (GFS), accessed via NOMADS.

SolarImeg は取得した U/V 風成分を RGBA データテクスチャへ変換しており、NOAA/NCEP の公式画像をそのまま転載しているものではありません。

### SOHO

SOHO のリアルタイム太陽画像を次の公式配信元から取得しています。

- https://soho.nascom.nasa.gov/data/realtime/

SOHO は ESA と NASA の国際協力プロジェクトです。

表示用クレジット例:

> Solar imagery: SOHO (ESA & NASA)

### 名古屋市科学館 太陽観測

`now_wh.jpg` / `now_ha.jpg` は名古屋市科学館の太陽観測ページを取得元としています。

- http://www.ncsm.city.nagoya.jp/astro/sun/

利用・転載時は名古屋市科学館側の利用条件を確認してください。

### クレジット表示例

Earth Weather と太陽像を一緒に利用する場合は、最低限次のようにまとめて表示できます。

```text
Cloud imagery: Contains modified EUMETSAT data.
Cloud/specular source service: live-cloud-maps by Matt Eason.
Wind data: NOAA/NWS/NCEP Global Forecast System (GFS), accessed via NOMADS.
Solar imagery: SOHO (ESA & NASA).
```

名古屋市科学館の画像を利用する場合は、これに名古屋市科学館の出典も追加してください。

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
