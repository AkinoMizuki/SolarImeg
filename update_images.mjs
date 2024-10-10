import fs from 'node:fs/promises';
import yaml from 'js-yaml';
import sharp from 'sharp';
import path from 'node:path';

const PAGES_DIRECTORY_PATH = './_site/';

const pagesDirectory = new URL(PAGES_DIRECTORY_PATH, import.meta.url);
await fs.mkdir(pagesDirectory, { recursive: true });
for (const data of yaml.load(await fs.readFile(new URL('sources.yaml', import.meta.url), { encoding: 'utf-8' }))) {
    const resp = await fetch(data.url);

    const image = sharp(await resp.arrayBuffer());
    const metadata = await image.metadata();
    if (metadata.width > 2048 || metadata.height > 2048)
    {
        image.resize(2048, 2048);
    }
    fs.writeFile(new URL(data.fileName, pagesDirectory), await image.toBuffer());
}
