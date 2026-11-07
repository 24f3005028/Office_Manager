// Preserve the supplied vector logo and rasterise it for Android and React Native.
const sharp = require('../frontend/node_modules/sharp');
const path = require('node:path');
const root = path.join(__dirname, '../mobile/assets');
const source = path.join(root, 'hs-traders-logo.svg');
const icons = {
  home: '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
  statement: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 11h6M9 15h2m3 1 2 2 4-4"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  history: '<path d="M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7m2-4v5l3 2"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  back: '<path d="m14 5-7 7 7 7"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
  share: '<path d="M12 16V3m-5 5 5-5 5 5M6 12H4v9h16v-9h-2"/>',
  whatsapp: '<path d="M4.2 16.9a9 9 0 1 1 3 3L3 21z"/><path d="M8 7c-2 3 4 9 7 8l1-2-3-1-1 1-2-2 1-1-1-3z"/>',
  file: '<path d="M14 3H5v18h14V8zM14 3v6h5M8 13h8M8 17h5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
  settings: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18M7 15h3m4 0h3"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
};
async function main() {
  const logo = await sharp(source, { density: 160 }).trim({ background: '#ffffff', threshold: 20 }).png().toBuffer();
  const mark = await sharp(logo).resize({ width: 430, height: 620, fit: 'inside' }).toBuffer();
  const circle = Buffer.from('<svg width="1024" height="1024"><circle cx="512" cy="512" r="500" fill="white"/><circle cx="512" cy="512" r="498" fill="none" stroke="#dbe5ed" stroke-width="4"/></svg>');
  const badge = await sharp({ create: { width: 1024, height: 1024, channels: 4, background: '#00000000' } })
    .composite([{ input: circle }, { input: mark, gravity: 'centre' }]).png().toBuffer();
  await sharp(badge).resize(400, 400).toFile(path.join(root, 'logo.png'));
  await sharp(badge).toFile(path.join(root, 'icon.png'));
  await sharp(badge).resize(640, 640).extend({ top: 192, bottom: 192, left: 192, right: 192, background: '#00000000' })
    .toFile(path.join(root, 'adaptive-icon.png'));
  await sharp(badge).resize(288, 288).toFile(path.join(root, 'splash-icon.png'));
  for (const [name, paths] of Object.entries(icons)) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#0d2b4e" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
    await sharp(Buffer.from(svg)).resize(96, 96).png().toFile(path.join(root, `${name}.png`));
  }
  console.log('Created app icons, brand logo and interface icons.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
