// Roda o worker.js localmente no Node (sem Cloudflare), com um Durable Object
// simulado em memoria. Serve para testar o PC e o Kindle sem publicar nada.
//
//   TOKEN_PC=abc TOKEN_KINDLE=xyz node relay/servidor_teste.mjs [porta]
//
// Depois aponte o setup para http://IP:porta (o setup exige https, entao use
// --url com o claudinho.py direto, ou edite pc/config.json).
import http from "node:http";
import worker, { Caixa } from "./worker.js";

const porta = Number(process.argv[2] || 8790);
const memoria = new Map();
const storage = {
  async get(k) { return memoria.get(k); },
  async put(k, v) { memoria.set(k, structuredClone(v)); },
};
const objeto = new Caixa({ storage }, {});
const env = {
  TOKEN_PC: process.env.TOKEN_PC || "pc",
  TOKEN_KINDLE: process.env.TOKEN_KINDLE || "kindle",
  CAIXA: {
    idFromName: (nome) => nome,
    get: () => ({ fetch: (url, init) => objeto.fetch(new Request(url, init)) }),
  },
};

http.createServer(async (req, res) => {
  const partes = [];
  for await (const p of req) partes.push(p);
  const corpo = Buffer.concat(partes);
  const request = new Request(`http://${req.headers.host}${req.url}`, {
    method: req.method,
    headers: req.headers,
    body: ["GET", "HEAD"].includes(req.method) ? undefined : corpo,
  });
  const r = await worker.fetch(request, env);
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
}).listen(porta, () => console.log(`relay de teste em http://localhost:${porta}`));
