import fs from 'node:fs/promises';
import yaml from 'js-yaml';
import sharp from 'sharp';
import path from 'node:path';

const PAGES_DIRECTORY_PATH = './_site/';

const pagesDirectory = new URL(PAGES_DIRECTORY_PATH, import.meta.url);
await fs.mkdir(pagesDirectory, { recursive: true });

try {
  const yamlData = yaml.load(
    await fs.readFile(new URL('sources.yaml', import.meta.url), { encoding: 'utf-8' })
  );

  for (const data of yamlData) {
    try {
      const resp = await fetch(data.url);

      // HTTPエラーの場合の処理
      if (!resp.ok) {
        console.error(`Failed to fetch image from ${data.url}: ${resp.statusText}`);
        continue;
      }

      const imageBuffer = Buffer.from(await resp.arrayBuffer());
      const image = sharp(imageBuffer);
      const metadata = await image.metadata();

      // 画像サイズを確認しリサイズ
      let processedImage = image;
      if (metadata.width > 2048 || metadata.height > 2048) {
        processedImage = image.resize({
          width: 2048,
          height: 2048,
          fit: 'inside', // 縦横比を維持
        });
      }

      // ファイル書き込み
      await fs.writeFile(
        new URL(data.fileName, pagesDirectory),
        await processedImage.toBuffer()
      );
      console.log(`Successfully processed and saved ${data.fileName}`);
    } catch (error) {
      console.error(`Error processing ${data.url}:`, error.message);
    }
  }
} catch (error) {
  console.error('Error reading YAML file or processing images:', error.message);
}
