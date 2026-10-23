--[[--
Renderiza o painel e o overlay do plugin para imagens, fora do Kindle.

    luajit tools/harness/render.lua estado.json saida.pgm [escala] [hora]
    luajit tools/harness/render.lua --overlay saida.pgm [celula]

Usado para conferir o desenho contra o original e gerar as imagens do README.
]]
local H = dofile((debug.getinfo(1, "S").source:sub(2):match("(.*/)") or "./") .. "boot.lua")
local D = require("claudinho/desenho")
local E = require("claudinho/estado")
local json = require("claudinho/json")
local sprites = require("claudinho/sprites")

local args = { ... }

if args[1] == "--overlay" then
    local cel = tonumber(args[3]) or 2
    local d = D.novo(H.BB, H.RT, H.fonte, sprites, 1)
    local w, h = D.tamanho_overlay(sprites, cel)
    local casos = { { "sopa_1", "normal" }, { "esperando_1", "alerta" }, { "esperando_1", "normal" },
        { "prato_1", "normal" }, { "descansando_1", "normal" }, { "descansando_1", "apagado" } }
    local bb = H.BB.new((w + 12) * #casos + 12, h + 24, H.BB.TYPE_BB8)
    bb:fill(H.BB.Color8(0xF4))
    for i, c in ipairs(casos) do
        d:overlay(bb, 12 + (i - 1) * (w + 12), 12, c[1], cel, c[2])
    end
    H.salvar_pgm(bb, args[2])
    return
end

local f = assert(io.open(args[1]))
local dados = assert(json.decode(f:read("*a")))
f:close()
local k = tonumber(args[3]) or 1
local agora = tonumber(dados.agora) or os.time()
local v = E.interpretar(dados, agora, { recebido_em = agora, idade = 0, desvio = E.desvio(dados, agora, 0) })
local data, hora = E.data_hora(agora)
if args[4] then hora = args[4] end
if args[5] then data = args[5] end

local d = D.novo(H.BB, H.RT, H.fonte, sprites, k)
local bb = H.BB.new(d:px(D.W), d:px(D.H), H.BB.TYPE_BB8)
local t0 = os.clock()
d:painel(bb, v, data, hora, E.quadro_parado(v.modo))
io.stderr:write(string.format("painel %dx%d em %.0f ms (k=%.2f)\n", bb:getWidth(), bb:getHeight(),
    (os.clock() - t0) * 1000, k))
H.salvar_pgm(bb, args[2])
