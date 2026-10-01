// The real sync Worker on http://127.0.0.1:<port>, with an in-memory bucket and SQLite in place of D1, for
// testing the Python client end to end: node local_server.mjs <port> [admin account id].
// Prints "listening <port>" when ready.
import http from "node:http";

import worker from "../src/index.js";
import { fakeEnv } from "./fakes.mjs";

const env = fakeEnv({ ADMIN_ACCOUNT: process.argv[3] || "" });
const server = http.createServer(async (req, res) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = Buffer.concat(chunks);
  const request = new Request(`http://${req.headers.host}${req.url}`, {
    method: req.method, headers: req.headers, body: ["GET", "HEAD"].includes(req.method) ? undefined : body,
  });
  const response = await worker.fetch(request, env);
  res.writeHead(response.status, Object.fromEntries(response.headers));
  res.end(Buffer.from(await response.arrayBuffer()));
});
server.listen(Number(process.argv[2] || 0), "127.0.0.1", () => console.log(`listening ${server.address().port}`));
