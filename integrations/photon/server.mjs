import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { Spectrum } from 'spectrum-ts';
import { imessage } from 'spectrum-ts/providers/imessage';

const secret = process.env.PHOTON_BRIDGE_TOKEN;
if (!secret || !process.env.SPECTRUM_PROJECT_ID || !process.env.SPECTRUM_PROJECT_SECRET) {
  throw new Error('Photon project credentials and PHOTON_BRIDGE_TOKEN are required');
}
const app = await Spectrum({
  projectId: process.env.SPECTRUM_PROJECT_ID,
  projectSecret: process.env.SPECTRUM_PROJECT_SECRET,
  providers: [imessage.config()],
});
const im = imessage(app);

function authorized(value = '') {
  const actual = Buffer.from(value);
  const expected = Buffer.from(`Bearer ${secret}`);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

const server = createServer(async (req, res) => {
  const reply = (status, data) => {
    res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify(data));
  };
  if (req.url !== '/send' || req.method !== 'POST') return reply(404, { error: 'Not found' });
  if (!authorized(req.headers.authorization)) return reply(401, { error: 'Unauthorized' });
  if (process.env.SEND_NOTIFICATIONS !== 'true') {
    return reply(503, { error: 'Live notifications are disabled' });
  }
  try {
    let body = '';
    for await (const chunk of req) {
      body += chunk;
      if (Buffer.byteLength(body) > 16384) return reply(413, { error: 'Request too large' });
    }
    const data = JSON.parse(body);
    if (process.env.MODE === 'demo' && (!process.env.DEMO_RECIPIENT_PHONE || data.recipient !== process.env.DEMO_RECIPIENT_PHONE || !data.body.startsWith('[LIFTLINE DEMO'))) {
      return reply(403, { error: 'Demo messages must be labeled and addressed to the configured test recipient' });
    }
    if (!/^\+[1-9]\d{7,14}$/.test(data.recipient) || typeof data.body !== 'string' || !data.body || data.body.length > 8000) {
      return reply(400, { error: 'Valid recipient and message required' });
    }
    const user = await im.user(data.recipient);
    const space = await im.space.create(user);
    const message = await space.send(data.body);
    return reply(200, { id: message?.id ?? 'provider-accepted', status: 'accepted' });
  } catch (error) {
    let detail = String(error?.message ?? 'Unknown provider error');
    for (const [key, value] of Object.entries(process.env)) {
      if (/SECRET|TOKEN|PASSWORD|API_KEY/.test(key) && value) detail = detail.split(value).join('[redacted]');
    }
    detail = detail.replace(/\+\d{8,15}/g, '[phone]').slice(0, 400);
    console.error('Photon send error:', error?.name, detail);
    return reply(502, { error: 'Photon send failed', detail });
  }
});
server.requestTimeout = 25000;
server.listen(8081, '127.0.0.1', () => console.log('Photon notification bridge listening on 127.0.0.1:8081'));
process.on('SIGTERM', async () => { server.close(); await app.stop(); process.exit(0); });
process.on('SIGINT', async () => { server.close(); await app.stop(); process.exit(0); });
