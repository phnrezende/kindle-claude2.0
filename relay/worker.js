// Relay do Claudinho: o PC grava o estado aqui e o Kindle le, de qualquer rede.
//
//   PUT /estado   (Authorization: Bearer TOKEN_PC)      grava o JSON do estado
//   GET /estado   (Authorization: Bearer TOKEN_KINDLE)  devolve o ultimo estado
//
// O estado fica num Durable Object (SQLite), que no plano gratuito da Cloudflare
// aguenta 100 mil gravacoes por dia. O GET responde 304 quando nada mudou
// (If-None-Match), e sempre manda X-Claudinho-Idade (segundos desde o ultimo envio
// do PC), para o Kindle saber se o PC ainda esta vivo.

const TAMANHO_MAX = 16 * 1024;

function resposta(status, corpo, extra = {}) {
  const headers = { "Cache-Control": "no-store", ...extra };
  if (corpo !== null && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json; charset=utf-8";
  }
  return new Response(corpo, { status, headers });
}

function erro(status, msg) {
  return resposta(status, JSON.stringify({ erro: msg }));
}

// comparacao que nao vaza o tamanho do acerto pelo tempo
function iguais(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || !a || !b) return false;
  let dif = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    dif |= (a.charCodeAt(i % a.length) || 0) ^ (b.charCodeAt(i % b.length) || 0);
  }
  return dif === 0;
}

function tokenDe(request) {
  const auth = request.headers.get("Authorization") || "";
  if (/^bearer\s+/i.test(auth)) return auth.replace(/^bearer\s+/i, "").trim();
  return new URL(request.url).searchParams.get("token") || "";
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/saude") {
      return resposta(200, "Claudinho relay no ar.\n", { "Content-Type": "text/plain; charset=utf-8" });
    }
    if (url.pathname !== "/estado") return erro(404, "nao encontrado");
    if (!env.TOKEN_PC || !env.TOKEN_KINDLE) {
      return erro(500, "faltam os segredos TOKEN_PC e TOKEN_KINDLE (wrangler secret put)");
    }

    const token = tokenDe(request);
    const caixa = env.CAIXA.get(env.CAIXA.idFromName("principal"));

    if (request.method === "PUT" || request.method === "POST") {
      if (!iguais(token, env.TOKEN_PC)) return erro(401, "token invalido");
      const corpo = await request.text();
      if (corpo.length > TAMANHO_MAX) return erro(413, "estado grande demais");
      let rev;
      try {
        const estado = JSON.parse(corpo);
        if (typeof estado !== "object" || estado === null || Array.isArray(estado)) throw new Error();
        rev = String(estado.rev || "");
      } catch (e) {
        return erro(400, "JSON invalido");
      }
      return caixa.fetch("https://caixa/salvar", {
        method: "PUT",
        body: corpo,
        headers: { "X-Rev": rev },
      });
    }

    if (request.method === "GET" || request.method === "HEAD") {
      if (!iguais(token, env.TOKEN_KINDLE) && !iguais(token, env.TOKEN_PC)) {
        return erro(401, "token invalido");
      }
      return caixa.fetch("https://caixa/ler", {
        headers: { "If-None-Match": request.headers.get("If-None-Match") || "" },
      });
    }

    return erro(405, "metodo nao suportado");
  },
};

// Guarda o ultimo estado. Fica em memoria enquanto o objeto esta acordado e
// no armazenamento (SQLite) para sobreviver quando ele dorme.
export class Caixa {
  constructor(state, env) {
    this.state = state;
    this.ultimo = null; // { corpo, rev, quando }
  }

  async carregar() {
    if (!this.ultimo) this.ultimo = (await this.state.storage.get("estado")) || null;
    return this.ultimo;
  }

  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === "/salvar") {
      const corpo = await request.text();
      const ultimo = { corpo, rev: request.headers.get("X-Rev") || "", quando: Math.floor(Date.now() / 1000) };
      await this.state.storage.put("estado", ultimo);
      this.ultimo = ultimo;
      return resposta(204, null);
    }

    const ultimo = await this.carregar();
    if (!ultimo) return erro(404, "o PC ainda nao enviou nada");
    const agora = Math.floor(Date.now() / 1000);
    const extra = {
      ETag: `"${ultimo.rev}"`,
      // idade medida pelo relogio do relay: o Kindle nao depende do proprio relogio
      "X-Claudinho-Idade": String(Math.max(0, agora - ultimo.quando)),
      "X-Claudinho-Atualizado": String(ultimo.quando),
    };
    if (ultimo.rev && request.headers.get("If-None-Match") === extra.ETag) {
      return resposta(304, null, extra);
    }
    return resposta(200, ultimo.corpo, extra);
  }
}
