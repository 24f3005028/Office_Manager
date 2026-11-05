// Used only by the Windows launcher. Match dotenv/config's runtime precedence.
const path = require('node:path');
const bridge = path.resolve(__dirname, '../whatsapp-bridge');
require(path.join(bridge, 'node_modules/dotenv')).config({ path: path.join(bridge, '.env'), quiet: true });
process.stdout.write(JSON.stringify({
  port: Number(process.env.WHATSAPP_BRIDGE_PORT ?? 3001),
  host: process.env.WHATSAPP_BRIDGE_HOST ?? '127.0.0.1',
  apiKey: process.env.WHATSAPP_BRIDGE_API_KEY?.trim() || null,
}));
