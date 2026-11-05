const path = require('node:path');
const frontend = path.resolve(__dirname, '../frontend');
require(path.join(frontend, 'node_modules/@next/env')).loadEnvConfig(frontend, false, { info() {}, error() {} });
process.stdout.write(JSON.stringify({ apiUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000' }));
