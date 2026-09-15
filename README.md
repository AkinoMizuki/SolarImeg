# SolarImeg

`SolarImeg` は、太陽画像および Earth Weather 用データを自動取得・加工し、GitHub Pages から配信するプロジェクトです。

## 更新周期

Earth Weather は毎時 20 分に更新チェックします。
Cloud / Specular は NOAA/NESDIS Global Mosaic of Geostationary Satellite Imagery (GMGSI) の最新 2 観測を使用し、`previous` / `current` として配信します。

既存の SOHO・名古屋市科学館・ルートの `clouds.jpg` / `specular.jpg` は 3 時間周期で更新します。

`metadata.json` には Cloud / Specular の previous/current 観測時刻、GMGSI のソースキー、GFS の run 時刻、forecast hour、valid 時刻、風速の最大エンコード値などを記録します。

---

## 本体のライセンス

このリポジトリ自体には、現時点で GitHub が認識する `LICENSE` が設定されていません。

- リポジトリ本体のライセンス: **未設定**
- MIT / Apache-2.0 / GPL 等: **現時点では未適用**
- GitHub 上で公開されていること自体は、ソースコードを自由に再利用・再配布できるオープンソースライセンスの付与を意味しません。
- 外部から取得している画像・データには、それぞれ提供元のライセンス・利用条件・クレジット条件が別途適用されます。

外部データの条件は、以下の各セクションにある「権利形態 / ライセンス」「クレジット要否」「主な条件」を参照してください。

### 全体クレジット表

| 対象 | データ元 | 権利形態 / ライセンス | クレジット要否 | 表示用クレジット例 |
| --- | --- | --- | --- | --- |
| SOHO 太陽画像 | SOHO / ESA & NASA | SOHO / ESA / NASA の画像利用条件 | **要表示扱い** | `Solar imagery: SOHO (ESA & NASA)` |
| 名古屋市科学館 太陽像 | 名古屋市科学館 | CC BY 2.1 JP | **必須** | `Solar imagery: 名古屋市科学館` |
| 3時間更新 Cloud / Specular | `live-cloud-maps` / Matt Eason | CC0 1.0 Universal | 作者クレジットは任意 | `Cloud / specular imagery: live-cloud-maps by Matt Eason.` |
| 3時間更新 Cloud / Specular 元データ | EUMETSAT | EUMETSAT Data Policy / Licensing | **必須** | `Contains modified EUMETSAT data` |
| Earth Weather Cloud | NOAA / NESDIS GMGSI via NOAA Open Data Dissemination (NODD) | NOAA 公開データ | **推奨**（NOAAは出典表示を要請） | `Cloud imagery: derived from NOAA/NESDIS GMGSI (modified).` |
| Earth Weather Specular Base | `live-cloud-maps` / Matt Eason の static monthly `specular-base` | CC0 1.0 Universal | 作者クレジットは任意 | `Specular base: live-cloud-maps by Matt Eason.` |
| Earth Weather Wind | NOAA / NWS / NCEP GFS via NOMADS | 米国政府情報 / Public Domain | 法的 attribution 義務としては通常不要。**Earth Weather では出典明示のため表示推奨** | `Wind data: NOAA/NWS/NCEP Global Forecast System (GFS), accessed via NOMADS.` |

Earth Weather をまとめて表示する場合の例:

> Earth Weather — Cloud imagery: derived from NOAA/NESDIS Global Mosaic of Geostationary Satellite Imagery (GMGSI), modified. Specular base: live-cloud-maps by Matt Eason. Wind data: NOAA/NWS/NCEP Global Forecast System (GFS), accessed via NOMADS.

---

# SOHO

https://akinomizuki.github.io/SolarImeg/latest.jpg

https://akinomizuki.github.io/SolarImeg/latest2.jpg

https://akinomizuki.github.io/SolarImeg/EIT171.jpg

https://akinomizuki.github.io/SolarImeg/LASCO_C2.jpg

## データ元・クレジット: SOHO

SOHO のリアルタイム太陽画像を次の公式配信元から取得しています。

- https://soho.nascom.nasa.gov/data/realtime/
- SOHO Copyright Notice: https://soho.nascom.nasa.gov/data/summary/copyright.html

SOHO は ESA と NASA の国際協力プロジェクトです。

### クレジット表

| 対象 | データ元 | 権利形態 / ライセンス | クレジット要否 | 表示用クレジット例 |
| --- | --- | --- | --- | --- |
| SOHO リアルタイム太陽画像 | SOHO / ESA & NASA | SOHO / ESA / NASA の画像利用条件 | **要表示扱い** | `Solar imagery: SOHO (ESA & NASA)` |

### 権利形態 / ライセンス

SOHO のリアルタイム画像は MIT や CC0 といったソフトウェア / オープンデータライセンスではなく、**SOHO / ESA / NASA の画像利用条件**に従います。

SOHO の Copyright Notice では、公共教育および非商用利用について明示的な事前許可は不要とされ、出典表示が求められています。
また ESA の画像利用条件では ESA が権利を持つ画像についてクレジット表示が必要で、商用利用には別途許諾が必要となる場合があります。

### クレジット要否

**要表示扱い**とします。

SOHO 公式はクレジットを「requested」としており、次の表記を案内しています。

> Courtesy of SOHO/[instrument] consortium. SOHO is a project of international cooperation between ESA and NASA.

短縮表記として次も公式に認められています。

> SOHO (ESA & NASA)

表示用クレジット例:

> Solar imagery: SOHO (ESA & NASA)

### 主な条件

- 公共教育・非商用利用は、SOHO Copyright Notice 上、明示的な事前許可なしで利用可能。
- SOHO / ESA / NASA の出典を表示する。
- ESA / NASA が製品・サービス等を支持していると誤認させる表示をしない。
- ESA が権利を持つ画像の商用利用は、用途によって別途許諾が必要。
- NASA / ESA の名称・ロゴ等は画像利用とは別の商標・識別標章の条件が適用される。

---

# 名古屋市科学館からの太陽像

https://akinomizuki.github.io/SolarImeg/now_wh.jpg

https://akinomizuki.github.io/SolarImeg/now_ha.jpg

## データ元・クレジット: 名古屋市科学館 太陽観測

`now_wh.jpg` / `now_ha.jpg` は名古屋市科学館の太陽観測ページを取得元としています。

- 太陽観測ページ: http://www.ncsm.city.nagoya.jp/astro/sun/
- 利用条件: https://www.ncsm.city.nagoya.jp/study/astro/data/open_data.html
- CC BY 2.1 JP: https://creativecommons.org/licenses/by/2.1/jp/

太陽観測ページには CC BY の表示があり、名古屋市科学館の天文情報オープンデータ方針では、再利用可能なデータ等を CC BY として公開し、表示名を「名古屋市科学館」とするよう案内しています。

### クレジット表

| 対象 | データ元 | 権利形態 / ライセンス | クレジット要否 | 表示用クレジット例 |
| --- | --- | --- | --- | --- |
| `now_wh.jpg` / `now_ha.jpg` | 名古屋市科学館 | CC BY 2.1 JP | **必須** | `Solar imagery: 名古屋市科学館` |

### 権利形態 / ライセンス

**Creative Commons Attribution 2.1 Japan（CC BY 2.1 JP / 表示 2.1 日本）**

CC BY 2.1 JP の条件を守る限り、複製・再配布・改変が可能で、営利目的の利用もライセンス上は許可されています。

### クレジット要否

**必須です。**

クレジット表示名:

> 名古屋市科学館

表示用クレジット例:

> Solar imagery: 名古屋市科学館

### 主な条件

- 適切なクレジット表示が必要。
- ライセンスへのリンクを提示する。
- 改変した場合は、その旨を示す。
- 名古屋市科学館の利用方針では、Web 掲載時は Creative Commons 表記に従う。
- マスコミ・出版等での利用は、科学館学芸課天文係への連絡を求めている。
- 営利目的の利用については、名古屋市科学館へ相談するよう案内されている。

---

# 3時間更新の地球の雲

https://akinomizuki.github.io/SolarImeg/clouds.jpg

https://akinomizuki.github.io/SolarImeg/specular.jpg

## データ元・クレジット: live-cloud-maps / EUMETSAT

地球の雲画像と海面スペキュラ画像は Matt Eason 氏の `live-cloud-maps` を利用しています。

- Project: https://github.com/matteason/live-cloud-maps
- Cloud source: https://clouds.matteason.co.uk/images/8192x4096/clouds-alpha.png
- Specular source: https://clouds.matteason.co.uk/images/8192x4096/specular.jpg
- EUMETSAT Data Licensing: https://www.eumetsat.int/eumetsat-data-licensing

### クレジット表

| 対象 | データ元 | 権利形態 / ライセンス | クレジット要否 | 表示用クレジット例 |
| --- | --- | --- | --- | --- |
| Cloud / Specular 配信画像 | `live-cloud-maps` / Matt Eason | CC0 1.0 Universal | 作者クレジットは任意 | `Cloud / specular imagery: live-cloud-maps by Matt Eason.` |
| 元の雲データ | EUMETSAT | EUMETSAT Data Policy / Licensing | **必須** | `Contains modified EUMETSAT data` |

### 権利形態 / ライセンス

`live-cloud-maps` のコードと同プロジェクトが公開する画像は **CC0 1.0 Universal** とされています。

CC0 は著作権等を可能な限り放棄してパブリックドメイン相当として利用できるようにする仕組みで、CC0 自体はクレジット表示を要求しません。

ただし、`live-cloud-maps` の雲画像の元データには **EUMETSAT データ**が含まれます。EUMETSAT のデータ利用条件は CC0 とは別に適用され、EUMETSAT データを元にした画像・派生物を表示・公開する場合には attribution が必要です。

### クレジット要否

- `live-cloud-maps` / Matt Eason 氏: **CC0 上は必須ではない**。データ生成サービスの提供元として任意でクレジットする。
- EUMETSAT: **必須**。

EUMETSAT 必須表記:

> Contains modified EUMETSAT data

表示用クレジット例:

> Cloud / specular imagery: live-cloud-maps by Matt Eason. Contains modified EUMETSAT data.

### 主な条件

- `live-cloud-maps` の CC0 部分は、許可申請・著作者表示なしでも利用・複製・改変・再配布可能。
- EUMETSAT データ由来部分は EUMETSAT の該当データライセンスに従う。
- EUMETSAT データを元にした画像・変換物を表示・公開する場合は EUMETSAT attribution を付ける。
- CC0 であることを理由に、元データである EUMETSAT の条件まで消えるわけではない。

---

# Earth Weather

Unity / VRChat の地球表示で利用するため、雲・海面スペキュラ・風向風速を毎時更新して GitHub Pages から配信します。

## Earth Weather のデータ元・クレジット

Earth Weather は Cloud / Specular / Wind をまとめて 1 つの地球気象システムとして扱います。

### クレジット表

| 対象 | データ元 | 権利形態 / ライセンス | クレジット要否 | 表示用クレジット例 |
| --- | --- | --- | --- | --- |
| Cloud | NOAA / NESDIS Global Mosaic of Geostationary Satellite Imagery (GMGSI), NOAA Open Data Dissemination (NODD) | NOAA 公開データ | **推奨**（NOAAは出典表示を要請） | `Cloud imagery: derived from NOAA/NESDIS GMGSI (modified).` |
| Specular Base | `live-cloud-maps` / Matt Eason の static monthly `specular-base` | CC0 1.0 Universal | 作者クレジットは任意 | `Specular base: live-cloud-maps by Matt Eason.` |
| Wind | NOAA / NWS / NCEP GFS via NOMADS | 米国政府情報 / Public Domain | 法的 attribution 義務としては通常不要。**Earth Weather では出典明示のため表示推奨** | `Wind data: NOAA/NWS/NCEP Global Forecast System (GFS), accessed via NOMADS.` |

### Cloud: NOAA / NESDIS GMGSI

Earth Weather の Cloud は NOAA/NESDIS の **Global Mosaic of Geostationary Satellite Imagery (GMGSI)** の Longwave Infrared (`GMGSI_LW`) を使用します。

- NOAA Open Data Registry: https://registry.opendata.aws/noaa-gmgsi/
- S3 bucket: `s3://noaa-gmgsi-pds/`
- Product: `GMGSI_LW`
- 更新周期: 約 1 時間
- 公称水平解像度: 約 8 km
- 入力衛星群: GOES-East / GOES-West、Meteosat、Himawari 等から構成される全球モザイク

NOAA Open Data Dissemination (NODD) で配布される GMGSI は公開利用できます。NOAA は未改変データの利用・配布時に attribution を要請しており、NOAA の支持・提携を示唆してはいけません。

`cloud_previous.png` / `cloud_current.png` は GMGSI の Longwave IR をそのまま転載した画像ではありません。正距円筒化、欠損補完、極域ミラー、絶対 IR と局所コントラストによる雲抽出、RGBA 化を行った **modified / derived product** です。

表示用クレジット例:

> Cloud imagery: derived from NOAA/NESDIS Global Mosaic of Geostationary Satellite Imagery (GMGSI), modified.

### Specular Base: live-cloud-maps

海面反射の陸海マスクには `live-cloud-maps` リポジトリの月別 static `specular-base` を利用します。

- Project: https://github.com/matteason/live-cloud-maps
- Source path: `static_images/monthly/specular-base/{month}.jpg`
- Licence: CC0 1.0 Universal

この static base に、同時刻の GMGSI Cloud Alpha を反転した遮蔽を掛けて `specular_previous.jpg` / `specular_current.jpg` を生成します。

したがって Earth Weather の Specular の **雲遮蔽は GMGSI 由来**で、`live-cloud-maps` のリアルタイム `specular.jpg` は使用しません。

表示用クレジット例:

> Specular base: live-cloud-maps by Matt Eason.

### Wind: NOAA / NWS / NCEP GFS via NOMADS

風向・風速は NOAA / National Weather Service / National Centers for Environmental Prediction の Global Forecast System (GFS) を利用しています。

- NOMADS: https://nomads.ncep.noaa.gov/
- GFS products: https://www.nco.ncep.noaa.gov/pmb/products/gfs/
- Earth Weather が使用する GRIB filter: https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl
- Grid: GFS 0.25 degree
- Parameters: `UGRD`, `VGRD`
- Levels: 10 m above ground / 850 hPa / 700 hPa

NOAA / NWS の米国政府情報は、個別に別の表示があるものを除き、Public Domain として扱われます。Earth Weather ではデータ来歴を明確にするため出典を表示します。

Wind の表示用クレジット例:

> Wind data: NOAA/NWS/NCEP Global Forecast System (GFS), accessed via NOMADS.

主な条件:

- NOAA / NWS の情報を自分自身の著作物であると主張しない。
- NOAA / NWS が Earth Weather や製品・サービスを支持・提携しているように見せない。
- 改変した情報を NOAA / NWS の公式政府資料であるかのように表示しない。
- NWS の名称・ロゴ等は商標・識別標章として別途保護される。
- 米国政府資料を主体とする著作物では、17 U.S.C. §403 に基づく表示が必要になる場合がある。

Earth Weather は取得した U/V 風成分を RGBA データテクスチャへ変換しており、NOAA / NCEP の公式画像をそのまま転載しているものではありません。

### Earth Weather の表示用クレジット例

Earth Weather をシステムとしてまとめて表示する場合は、例えば次のように表記できます。

> Earth Weather — Cloud imagery: derived from NOAA/NESDIS Global Mosaic of Geostationary Satellite Imagery (GMGSI), modified. Specular base: live-cloud-maps by Matt Eason. Wind data: NOAA/NWS/NCEP Global Forecast System (GFS), accessed via NOMADS.

## 配信ファイル

### Cloud / Specular

- https://akinomizuki.github.io/SolarImeg/weather/cloud_previous.png
- https://akinomizuki.github.io/SolarImeg/weather/cloud_current.png
- https://akinomizuki.github.io/SolarImeg/weather/specular_previous.jpg
- https://akinomizuki.github.io/SolarImeg/weather/specular_current.jpg

### Wind

- https://akinomizuki.github.io/SolarImeg/weather/wind_surface.png
- https://akinomizuki.github.io/SolarImeg/weather/wind_850hpa.png
- https://akinomizuki.github.io/SolarImeg/weather/wind_700hpa.png

### Metadata

- https://akinomizuki.github.io/SolarImeg/weather/metadata.json

## Cloud / Specular

`weather/cloud_previous.png` / `weather/cloud_current.png` は、GMGSI `GMGSI_LW` の最新 2 観測から生成する 2048 x 1024 の RGBA 雲テクスチャです。

- RGB: 雲の明るさ・陰影
- A: 雲の不透明度
- 全球一律の IR しきい値だけでなく、局所コントラストも使って弱い雲を保持
- GMGSI の欠損領域のみ補間し、有効データは極力保持
- GMGSI が直接カバーしない極域はミラーして補います

Earth Weather の specular も同じ観測時刻で履歴を持ちます。

- `specular_previous.jpg`: `cloud_previous.png` と同じ世代
- `specular_current.jpg`: `cloud_current.png` と同じ世代

月別 `specular-base` に GMGSI Cloud Alpha の遮蔽を適用するため、雲がある場所では海面反射が抑えられます。

Cloud と Specular は必ずセットで世代交代し、同じ補間率で previous → current を補間する前提です。

```text
cloud_previous.png    <-> specular_previous.jpg
cloud_current.png     <-> specular_current.jpg
```

## Wind

GFS の UGRD / VGRD から、VRChat / Unity の Shader で直接利用できる RGBA データテクスチャを生成します。

- `wind_surface.png`: 地上 10 m 風。風向・風速の表示用
- `wind_850hpa.png`: 850 hPa 風。低層雲の移流用候補
- `wind_700hpa.png`: 700 hPa 風。中層雲の移流用候補

各テクスチャは 1440 x 720 の正距円筒図法です。
経度は左端が -180°、中央が 0°（Greenwich）、右端が +180°です。
画像上では上端が北極、下端が南極です。

### Wind RGBA データ形式

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

Shader での復元例:

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

矢印の回転角へ変換する場合の基本形:

```hlsl
float angle = atan2(windDir.y, windDir.x);
```

### 風速による色分け

`windSpeed` を使って Shader 側で色を変更できます。

```text
青 → シアン → 緑 → 黄 → オレンジ → 赤 → 紫
```

色分けは画像側へ焼き込まず、Shader 側で行うため、風速レンジや色境界は Unity の Material から調整できます。

### 雲の移流に使う場合

雲には `wind_850hpa.png` または `wind_700hpa.png` を使用します。

風データによる UV 変位は、観測画像そのものを長時間移動させ続ける用途ではなく、次の雲画像更新までの短時間補間用です。
`cloud_previous.png` と `cloud_current.png` の時間補間と組み合わせて使用します。

Sphere の UV 配置によって南北方向が逆に見える場合は、Shader 側で UV の V または風向 Y を調整してください。

## Unity / VRChat Shader の使い方

現在の Earth Weather 用 Shader 名:

```text
AkinoMizuki/Planets/EarthCloudWeather
```

Cloud / Specular / Wind は **1 つの EarthCloudWeather Material** にまとめて割り当てます。
`specular_previous/current` は別 Material ではなく、Cloud と同じ Material 内で使用する海面反射マスクです。

### 構成

```text
CloudSphere
└─ EarthCloudWeather Material
   ├─ weather/cloud_previous.png
   ├─ weather/cloud_current.png
   ├─ weather/specular_previous.jpg
   ├─ weather/specular_current.jpg
   ├─ weather/wind_surface.png
   ├─ weather/wind_850hpa.png
   └─ weather/wind_700hpa.png
```

### EarthCloudWeather Material

| Shader Property | Texture / 設定 |
| --- | --- |
| `Cloud Previous (RGBA)` | `weather/cloud_previous.png` |
| `Cloud Current (RGBA)` | `weather/cloud_current.png` |
| `Specular Previous` | `weather/specular_previous.jpg` |
| `Specular Current` | `weather/specular_current.jpg` |
| `Wind Surface (RGBA Data)` | `weather/wind_surface.png` |
| `Wind 850 hPa (RGBA Data)` | `weather/wind_850hpa.png` |
| `Wind 700 hPa (RGBA Data)` | `weather/wind_700hpa.png` |
| `Cloud Enabled` | ON |
| `Wind Arrow Enabled` | 必要に応じて ON/OFF |

`Wind Surface` は表示用の風向・風速、`Wind 850 hPa` / `Wind 700 hPa` は雲の短時間移流に使用します。

風向表示は 1 セルに複数の短い流れ片を持たせ、風向方向へ連続的に移動させます。風速に応じて移動速度と表示色を変え、高緯度では経度方向の表示密度を減らして極付近への集中を抑えます。

### Previous / Current の補間

Cloud と Specular は同じ GMGSI 観測世代で更新されるため、同じ補間率を使用します。

```text
0.0 = previous
1.0 = current
```

例えば更新時刻の中間なら `0.5` とし、Cloud と Specular を同じ値で補間します。

### `_SunDir`

`_SunDir` は地球から見た太陽方向を World Space の方向ベクトルとして設定します。

```hlsl
material.SetVector("_SunDir", sunDirection.normalized);
```

Cloud の昼夜の明るさと Specular の両方で同じ太陽方向を利用します。

### Texture Import Settings

#### Cloud

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
Filter Mode           = Bilinear
Wrap U               = Repeat
Wrap V               = Clamp
```

Wind Texture を sRGB のまま使用する必要がある場合は、Material の `Wind Texture Is sRGB` を ON にして Shader 側で補正します。

#### Specular

`specular_previous.jpg` / `specular_current.jpg` は反射マスクなので Linear Data として扱うことを推奨します。

```text
sRGB (Color Texture) = OFF
Compression          = None 推奨
Filter Mode           = Bilinear
```

sRGB として読み込む場合は `Specular Texture Is sRGB` を ON にしてください。
