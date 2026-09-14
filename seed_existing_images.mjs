import fs from 'node:fs/promises';
import * as yaml from 'js-yaml';

const PAGES_DIRECTORY_PATH = './_site/';
const PUBLISHED_BASE_URL = 'https://akinomizuki.github.io/SolarImeg/';

const pagesDirectory = new URL(PAGES_DIRECTORY_PATH, import.meta.url);
await fs.mkdir(pagesDirectory, { recursive: true });

const yamlData = yaml.load(
  await fs.readFile(new URL('sources.yaml', import.meta.url), { encoding: 'utf-8' })
);

for (const data of yamlData) {
  const publishedUrl = new URL(data.fileName, PUBLISHED_BASE_URL);
  publishedUrl.searchParams.set('t', Date.now().toString());

  const response = await fetch(publishedUrl, {
    headers: {
      'Cache-Control': 'no-cache',
      'User-Agent': 'AkinoMizuki-SolarImeg/ExistingImageSeeder',
    },
  });

  if (!response.ok) {
    throw new Error(
      `Failed to restore published image ${data.fileName}: ${response.status} ${response.statusText}`
    );
  }

  const buffer = Buffer.from(await response.arrayBuffer());
  if (buffer.length === 0) {
    throw new Error(`Published image ${data.fileName} was empty`);
  }

  await fs.writeFile(new URL(data.fileName, pagesDirectory), buffer);
  console.log(`Restored published image without refreshing source: ${data.fileName}`);
}
