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
local json = require("claudinho/json")
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
    ativos = 1, antes = { "Edit", "Read" }, sessao = { pct = 11, zera = "zera às 15:00" }, semana = {},
    tokens = { hoje = 2480000, hora = 420000 }, rev = "abc" }
local info = { recebido_em = agora, idade = 0, desvio = E.desvio(d, agora, 0), falhas = 0 }
local v = E.interpretar(d, agora, info)
igual(v.titulo, "Te chamando!", "titulo")
igual(v.linha, "esperando você há 40s", "linha")
igual(v.grupo, "aprovacao", "grupo do overlay")
igual(v.antes, "Edit · Read", "antes")
igual(v.sessao.txt, "11%", "sessao")
igual(v.semana.txt, "--", "semana sem dado")
igual(v.tokens_media, "média --/dia", "media sem dado")

print("relogio do Kindle errado")
local kindle = agora + 3600         -- Kindle adiantado 1 hora
local info2 = { recebido_em = kindle, idade = 0, desvio = E.desvio(d, kindle, 0), falhas = 0 }
v = E.interpretar(d, kindle + 20, info2)
igual(v.modo, "chamando", "nao vira 'sem sinal' por causa do relogio")
igual(v.linha, "esperando você há 1 min", "conta o tempo pelo relogio do PC")

print("sem sinal")
v = E.interpretar(d, agora + 700, { recebido_em = agora, idade = 0, desvio = 0, falhas = 0 })
igual(v.modo, "sem_sinal", "estado parado ha mais de 10 min")
igual(v.linha, "última notícia há 11 min", "conta desde a ultima noticia")
v = E.interpretar(d, agora + 5, { recebido_em = agora, idade = 0, desvio = 0, falhas = 3 })
igual(v.descricao, "sem conexão", "3 falhas seguidas")
local off = { modo = "cozinhando", pc_offline = true, agora = agora, desde = agora }
igual(E.interpretar(off, agora, { recebido_em = agora }).descricao, "PC desligado?", "PC avisou que saiu")
igual(E.interpretar(nil, agora, {}).modo, "sem_sinal", "nunca recebeu nada")

print("varios agentes")
local d3 = { modo = "cozinhando", desde = agora - 7, agora = agora, ferramenta = "Edit", descricao = "x.java",
    ativos = 3, projeto = "camaleao" }
v = E.interpretar(d3, agora, { recebido_em = agora })
igual(v.linha, "última ação há 7s · 3 no fogo", "conta os agentes")
igual(v.descricao, "x.java · camaleao", "diz o projeto")

print("animacao")
local seq = E.sequencia("cozinhando", function(n) return n end)
igual(#seq, 20, "10 blocos de 2 quadros")
local repetiu = false
for i = 3, #seq, 2 do if seq[i] == seq[i - 2] then repetiu = true end end
igual(repetiu, false, "nunca repete o mesmo bloco seguido")
igual(E.sequencia("descansando")[2], "descansando_2", "descansando")
igual(E.quadro_parado("prato"), "prato_1", "quadro parado")

print("busca: empacotar e desempacotar")
local r = Busca._desempacotar(Busca._empacotar({ codigo = 200, idade = 12, etag = '"abc"', corpo = 'linha1\nlinha2' }))
igual(r.codigo, 200, "codigo")
igual(r.idade, 12, "idade")
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
