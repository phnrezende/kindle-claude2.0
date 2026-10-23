--[[--
Testes da logica pura do plugin (sem KOReader):

    luajit tools/harness/testes.lua
]]
local AQUI = debug.getinfo(1, "S").source:sub(2):match("(.*/)") or "./"
package.path = AQUI .. "../../kindle/claudinho.koplugin/?.lua;" .. package.path
package.preload["ui/uimanager"] = function() return {} end
package.preload["ffi/util"] = function() return {} end
package.preload["logger"] = function() return {} end

local E = require("claudinho/estado")
local L = require("claudinho/textos")
local json = require("claudinho/json")
L.escolher("pt")
local Busca = require("claudinho/busca")

local falhas = 0
local function igual(a, b, msg)
    local ok = a == b
    io.write(ok and "  ok   " or "  FALHOU ", msg, ok and "" or (" (veio " .. tostring(a) .. ", esperava " .. tostring(b) .. ")"), "\n")
    if not ok then falhas = falhas + 1 end
end

print("formatos (iguais ao server.py original)")
igual(E.fmt_tokens(2480000), "2,5 mi", "2,5 mi")
igual(E.fmt_tokens(420000), "0,4 mi", "0,4 mi")
igual(E.fmt_tokens(31500), "32 mil", "32 mil")
igual(E.fmt_tokens(512), "512", "512")
igual(E.fmt_tokens(nil), "--", "sem media")
igual(E.fmt_ha(39), "39s", "39s")
igual(E.fmt_ha(125), "2 min", "2 min")
igual(E.fmt_ha(3600 + 300), "1 h 5 min", "1 h 5 min")
igual(E.fmt_ha(3 * 3600 + 300), "3 h", "3 h")

print("estado")
local agora = 1000000
local d = { modo = "chamando", desde = agora - 40, agora = agora, ferramenta = "Bash", descricao = "rm -rf build/",
    ativos = 1, antes = { "Edit", "Read" }, sessao = { pct = 11, hora = "15:00" }, semana = {},
    tokens = { hoje = 2480000, hora = 420000 }, rev = "abc" }
local info = { recebido_em = agora, desvio = E.desvio(d, agora), falhas = 0 }
local v = E.interpretar(d, agora, info)
igual(v.titulo, "Te chamando!", "titulo")
igual(v.linha, "esperando você há 40s", "linha")
igual(v.grupo, "aprovacao", "grupo (o que a linha do topo distingue)")
igual(v.antes, "Edit · Read", "antes")
igual(v.sessao.txt, "11%", "sessao")
igual(v.sessao.zera, "zera às 15:00", "quando zera a sessao")
igual(v.semana.txt, "--", "semana sem dado")
igual(v.tokens_media, "média --/dia", "media sem dado")

print("relogio do Kindle errado")
local kindle = agora + 3600         -- Kindle adiantado 1 hora
local info2 = { recebido_em = kindle, desvio = E.desvio(d, kindle), falhas = 0 }
v = E.interpretar(d, kindle + 20, info2)
igual(v.modo, "chamando", "nao vira 'sem sinal' por causa do relogio")
igual(v.linha, "esperando você há 1 min", "conta o tempo pelo relogio do PC")

print("sem sinal")
v = E.interpretar(d, agora + 700, { recebido_em = agora, desvio = 0, falhas = 0 })
igual(v.modo, "sem_sinal", "estado parado ha mais de 10 min")
igual(v.linha, "última notícia há 11 min", "conta desde a ultima noticia")
v = E.interpretar(d, agora + 5, { recebido_em = agora, desvio = 0, falhas = 3 })
igual(v.descricao, "sem conexão", "3 falhas seguidas")
local kindle_atrasado = { recebido_em = agora - 5000, desvio = -5000, falhas = 0 }
igual(E.interpretar(d, agora - 5000 + 30, kindle_atrasado).modo, "chamando", "Kindle atrasado nao vira 'sem sinal'")
igual(E.interpretar(nil, agora, {}).modo, "sem_sinal", "nunca recebeu nada")

print("varios agentes")
local d3 = { modo = "cozinhando", desde = agora - 7, agora = agora, ferramenta = "Edit", descricao = "x.java",
    ativos = 3, projeto = "camaleao" }
v = E.interpretar(d3, agora, { recebido_em = agora })
igual(v.linha, "última ação há 7s", "a linha fica so com o tempo")
igual(v.agentes, "3 AGENTES", "conta os agentes (no topo do painel)")
igual(v.descricao, "x.java · camaleao", "diz o projeto")

print("animacao")
local seq = E.sequencia("cozinhando", function(n) return n end)
igual(#seq, 20, "10 blocos de 2 quadros")
local repetiu = false
for i = 3, #seq, 2 do if seq[i] == seq[i - 2] then repetiu = true end end
igual(repetiu, false, "nunca repete o mesmo bloco seguido")
igual(E.sequencia("descansando")[2], "descansando_2", "descansando")
igual(E.quadro_parado("prato"), "prato_1", "quadro parado")

print("sem ferramenta: o Kindle escreve a frase")
local base = { agora = agora, desde = agora - 5, ferramenta = "", descricao = "" }
local function com(t) local r = {} for k, x in pairs(base) do r[k] = x end for k, x in pairs(t) do r[k] = x end return r end
igual(E.interpretar(com{ modo = "cozinhando" }, agora, { recebido_em = agora }).descricao, "pensando…", "pensando")
igual(E.interpretar(com{ modo = "chamando" }, agora, { recebido_em = agora }).descricao, "esperando sua resposta", "esperando resposta")
igual(E.interpretar(com{ modo = "prato" }, agora, { recebido_em = agora }).descricao, "nada no fogo", "nada no fogo")
igual(E.interpretar(com{ modo = "cozinhando", descricao = "pensando…" }, agora, { recebido_em = agora }).descricao,
    "pensando…", "agente antigo (v1) com a frase pronta")
igual(E.interpretar(com{ modo = "cozinhando", sessao = { pct = 3, zera = "zera às 9:00" } }, agora,
    { recebido_em = agora }).sessao.zera, "zera às 9:00", "agente antigo (v1): zera ja escrito")
igual(E.interpretar(com{ modo = "cozinhando", semana = { pct = 3, hora = "21:00", dia = 7 } }, agora,
    { recebido_em = agora }).semana.zera, "zera dom 21:00", "semana: dia e hora")

print("ingles")
L.escolher("en")
local ve = E.interpretar(d, agora, info)
igual(ve.titulo, "Calling you!", "titulo")
igual(ve.linha, "waiting on you for 40s", "linha")
igual(ve.sessao.zera, "resets at 15:00", "quando zera")
igual(E.interpretar(com{ modo = "descansando", semana = { pct = 1, hora = "21:00", dia = 7 } }, agora,
    { recebido_em = agora }).semana.zera, "resets Sun 21:00", "semana")
igual(E.fmt_tokens(2480000), "2.5M", "milhoes")
igual(E.fmt_tokens(31500), "32K", "milhares")
igual(ve.tokens_hora, "0.4M in the last hour", "ultima hora")
igual(ve.tokens_media, "avg --/day", "media sem dado")
igual(E.interpretar(nil, agora, {}).titulo, "No PC signal", "sem sinal")
igual(E.interpretar(com{ modo = "cozinhando", ativos = 2 }, agora, { recebido_em = agora }).agentes, "2 AGENTS", "agentes")
igual(L.data(5, 22, 10), "Thu Oct 22", "data")
L.escolher("pt")
igual(L.data(5, 22, 10), "qui 22/10", "data em portugues")
L.escolher(nil)
igual(L.atual(), "en", "sem escolha e fora do KOReader: ingles")
_G.G_reader_settings = { readSetting = function(_, k) return k == "language" and "pt_BR" or nil end }
igual(L.atual(), "pt", "segue o KOReader em portugues")
_G.G_reader_settings = nil
L.escolher("pt")

print("dormir nao conta como 'sem sinal'")
local d4 = { modo = "cozinhando", desde = agora - 5, agora = agora }
igual(E.interpretar(d4, agora + 3600, { recebido_em = agora, dormiu = 3590 }).modo, "cozinhando",
    "acordou depois de 1 h dormindo: mostra o ultimo estado ate a proxima busca")
igual(E.interpretar(d4, agora + 3600, { recebido_em = agora, dormiu = 0 }).modo, "sem_sinal",
    "1 h acordado sem noticia: sem sinal")
igual(E.interpretar(d4, agora + 3600, { recebido_em = agora, dormiu = 3590, falhas = 3 }).modo, "sem_sinal",
    "3 falhas depois de acordar: sem sinal")

print("linha do topo")
local function linha(t) return E.linha_topo(E.interpretar(com(t), agora, { recebido_em = agora })) end
local lt = linha{ modo = "descansando", sessao = { pct = 75 } }
igual(lt.estado, 1, "parado: primeira bolinha")
igual(lt.pct, "75%", "o % da sessao de 5 h")
igual(lt.alerta, false, "parado: sem alerta")
igual(linha{ modo = "prato" }.estado, 1, "prato pronto: primeira bolinha")
igual(linha{ modo = "esperando" }.estado, 1, "terminou ha um tempo: primeira bolinha")
igual(linha{ modo = "cozinhando" }.estado, 2, "trabalhando: segunda")
lt = linha{ modo = "chamando", sessao = { pct = 40 } }
igual(lt.estado, 3, "pedindo permissao: terceira")
igual(lt.alerta, true, "pedindo permissao: inverte a linha")
igual(linha{ modo = "cozinhando" }.pct, "0%", "sem o % (plano sem limite ou janela nova): 0%")
igual(linha{ modo = "cozinhando", sessao = { pct = 74.6 } }.pct, "75%", "arredonda")
igual(linha{ modo = "cozinhando", sessao = { pct = 130 } }.pct, "100%", "passou do limite: 100%")
igual(linha{ modo = "cozinhando", sessao = { pct = -3 } }.pct, "0%", "negativo: 0%")
igual(linha{ modo = "cozinhando", ativos = 3 }.agentes, 3, "3 agentes trabalhando")
local ls = E.linha_topo(E.interpretar(nil, agora, {}))
igual(ls.estado, nil, "sem sinal: nenhuma bolinha cheia")
igual(ls.pct, "--", "sem sinal: -- (o Kindle nao sabe)")
igual(E.linha_topo(E.interpretar(com{ modo = "cozinhando", ativos = 3, sessao = { pct = 50 } }, agora + 3600,
    { recebido_em = agora })).agentes, 0, "sem sinal: nao conta agentes")
igual(E.linha_topo(nil).pct, "--", "vista estranha nao quebra")

print("dados estranhos nunca dao erro (a linha do topo roda a cada pagina)")
local estranhos = { {}, { 1 }, true, 5, "x", -1, 1e300 }
local campos = { "modo", "desde", "ferramenta", "descricao", "ativos", "projeto", "antes", "sessao", "semana",
    "tokens", "rev", "agora" }
local falhou_estranho = nil
for _, c in ipairs(campos) do
    for _, valor in ipairs(estranhos) do
        local dd = { modo = "cozinhando", ativos = 2, ferramenta = "Edit", projeto = "p" }
        dd[c] = valor
        local ok, err = pcall(function() return E.linha_topo(E.interpretar(dd, agora, { recebido_em = agora })) end)
        if not ok then falhou_estranho = c .. ": " .. tostring(err) end
    end
end
igual(falhou_estranho, nil, "nenhum campo estranho quebra o interpretar nem a linha")
local vt = E.interpretar({ modo = "cozinhando", ativos = 2, ferramenta = "Edit", projeto = {}, descricao = true,
    antes = { "Read", {}, 3 } }, agora, { recebido_em = agora })
igual(vt.descricao, "", "descricao que nao e texto vira vazia")
igual(vt.antes, "Read · 3", "'antes' ignora o que nao e texto")

print("os dois idiomas tem os mesmos textos")
local faltando = {}
for a, b in pairs({ pt = "en", en = "pt" }) do
    for k in pairs(L._TEXTOS[a]) do
        if L._TEXTOS[b][k] == nil and k ~= "meses" then faltando[#faltando + 1] = b .. "." .. k end
    end
end
igual(table.concat(faltando, ", "), "", "nenhuma chave faltando")

print("busca: empacotar e desempacotar")
local r = Busca._desempacotar(Busca._empacotar({ codigo = 200, etag = '"abc"', corpo = 'linha1\nlinha2' }))
igual(r.codigo, 200, "codigo")
igual(r.etag, '"abc"', "etag")
igual(r.corpo, "linha1\nlinha2", "corpo com quebras de linha")
r = Busca._desempacotar(Busca._empacotar({ erro = "tempo\nesgotado" }))
igual(r.erro, "tempo esgotado", "erro")
igual(r.codigo, nil, "sem codigo")

print("json")
local t = json.decode('{"a":"\\u00e9","b":[1,2],"c":null,"d":false}')
igual(t.a, "é", "unicode")
igual(#t.b, 2, "lista")
igual(t.c, nil, "null")
igual(t.d, false, "false")
igual(json.decode("{"), nil, "rejeita JSON quebrado")

print(falhas == 0 and "TUDO CERTO" or (falhas .. " FALHA(S)"))
os.exit(falhas == 0 and 0 or 1)
