--[[--
Renderiza o painel e a linha do topo do plugin para imagens, fora do Kindle.

    luajit tools/harness/render.lua estado.json saida.pgm [escala] [hora] [data] [pt|en]
    luajit tools/harness/render.lua --linha estado.json saida.pgm [escala]

Usado para conferir o desenho contra o original e gerar as imagens do README.
]]
local H = dofile((debug.getinfo(1, "S").source:sub(2):match("(.*/)") or "./") .. "boot.lua")
local D = require("claudinho/desenho")
local E = require("claudinho/estado")
local json = require("claudinho/json")
local L = require("claudinho/textos")
local sprites = require("claudinho/sprites")

local args = { ... }
local linha = args[1] == "--linha"
if linha then table.remove(args, 1) end
L.escolher(args[6] or "pt")

local f = assert(io.open(args[1]))
local dados = assert(json.decode(f:read("*a")))
f:close()

if linha then
    local agora = tonumber(dados.agora) or os.time()
    local v = E.interpretar(dados, agora, { recebido_em = agora, desvio = E.desvio(dados, agora) })
    local img = D.novo(H.BB, H.RT, H.fonte, sprites, 1):linha_topo(E.linha_topo(v), tonumber(args[3]) or 1)
    H.salvar_pgm(img, args[2])
    return
end
local k = tonumber(args[3]) or 1
local agora = tonumber(dados.agora) or os.time()
local v = E.interpretar(dados, agora, { recebido_em = agora, desvio = E.desvio(dados, agora) })
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
