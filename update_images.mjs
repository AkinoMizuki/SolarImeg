import fs from 'node:fs/promises';
import * as yaml from 'js-yaml';
import sharp from 'sharp';

const PAGES_DIRECTORY_PATH = './_site/';
const PUBLISHED_BASE_URL = 'https://akinomizuki.github.io/SolarImeg/';

const pagesDirectory = new URL(PAGES_DIRECTORY_PATH, import.meta.url);
await fs.mkdir(pagesDirectory, { recursive: true });

async function seedPublishedImage(fileName) {
  const destination = new URL(fileName, pagesDirectory);

  try {
    const publishedUrl = new URL(fileName, PUBLISHED_BASE_URL);
    publishedUrl.searchParams.set('t', Date.now().toString());

    const response = await fetch(publishedUrl, {
      headers: {
        'Cache-Control': 'no-cache',
        'User-Agent': 'AkinoMizuki-SolarImeg/ExistingImageFallback',
      },
    });

    if (!response.ok) {
      console.warn(
        `Published fallback unavailable for ${fileName}: ${response.status} ${response.statusText}`
      );
      return false;
    }

    const buffer = Buffer.from(await response.arrayBuffer());
    if (buffer.length === 0) {
      console.warn(`Published fallback for ${fileName} was empty`);
      return false;
    }

    await fs.writeFile(destination, buffer);
    console.log(`Seeded published fallback: ${fileName}`);
    return true;
  } catch (error) {
    console.warn(`Failed to seed published fallback ${fileName}: ${error.message}`);
    return false;
  }
}

try {
  const yamlData = yaml.load(
    await fs.readFile(new URL('sources.yaml', import.meta.url), { encoding: 'utf-8' })
  );

  for (const data of yamlData) {
    // _site is rebuilt on every Pages deployment. Seed the currently published
    // image first so a temporary source outage never removes a previously valid
    // file from the next deployment.
    const hadPublishedFallback = await seedPublishedImage(data.fileName);

    try {
      const resp = await fetch(data.url, {
        headers: {
          'Cache-Control': 'no-cache',
          'User-Agent': 'AkinoMizuki-SolarImeg/ImageUpdater',
        },
      });

      if (!resp.ok) {
        console.error(
          `Failed to fetch image from ${data.url}: ${resp.status} ${resp.statusText}`
        );
        if (hadPublishedFallback) {
          console.log(`Keeping previously published ${data.fileName}`);
        }
        continue;
      }

      const imageBuffer = Buffer.from(await resp.arrayBuffer());
      const image = sharp(imageBuffer);
      const metadata = await image.metadata();

      if (!metadata.format) {
        console.error(`Unsupported image format for ${data.url}`);
        if (hadPublishedFallback) {
          console.log(`Keeping previously published ${data.fileName}`);
        }
        continue;
      }

      let processedImage = image;
      if (metadata.width > 2048 || metadata.height > 2048) {
        processedImage = image.resize({
          width: 2048,
          height: 2048,
          fit: 'inside',
        });
      }

      await fs.writeFile(
        new URL(data.fileName, pagesDirectory),
        await processedImage.toBuffer()
      );
      console.log(`Successfully processed and saved ${data.fileName}`);
    } catch (error) {
      console.error(`Error processing ${data.url}:`, error.message);
      if (hadPublishedFallback) {
        console.log(`Keeping previously published ${data.fileName}`);
      } else {
        console.error(`No published fallback exists for ${data.fileName}`);
      }
    }
  }
} catch (error) {
  console.error('Error reading YAML file or processing images:', error.message);
  process.exitCode = 1;
}
