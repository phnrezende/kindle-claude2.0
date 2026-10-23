--[[--
Gera as imagens do README com o codigo de desenho do proprio plugin.

    KO=... KOBASE=... luajit tools/harness/imagens.lua pasta_saida [pt|en]
]]
local H = dofile((debug.getinfo(1, "S").source:sub(2):match("(.*/)") or "./") .. "boot.lua")
local D = require("claudinho/desenho")
local E = require("claudinho/estado")
local L = require("claudinho/textos")
local sprites = require("claudinho/sprites")
local BB = H.BB
local SAIDA, IDIOMA = ...
SAIDA = SAIDA or "."
L.escolher(IDIOMA or "pt")

local agora = os.time()
local base = {
    agora = agora, ativos = 1, projeto = "camaleao", antes = { "mcp:notion", "Bash", "Grep", "Read" },
    sessao = { pct = 11, hora = "15:00" }, semana = { pct = 19, hora = "21:00", dia = 7 },
    tokens = { hoje = 2480000, hora = 420000, media = 1830000 },
}
local function com(t)
    local r = {}
    for k, v in pairs(base) do r[k] = v end
    for k, v in pairs(t) do r[k] = v end
    return r
end
local telas = {
    trabalhando = com{ modo = "cozinhando", desde = agora - 7, ferramenta = "Edit", descricao = "DashboardController.java" },
    aprovacao = com{ modo = "chamando", desde = agora - 40, ferramenta = "Bash", descricao = "rm -rf build/" },
    pronto = com{ modo = "esperando", desde = agora - 125, ferramenta = "", descricao = "" },
    descansando = com{ modo = "descansando", desde = agora - 2700, ferramenta = "", descricao = "" },
}

local d = D.novo(BB, H.RT, H.fonte, sprites, 1)
for nome, dados in pairs(telas) do
    local v = E.interpretar(dados, agora, { recebido_em = agora, desvio = 0 })
    local bb = BB.new(800, 600, BB.TYPE_BB8)
    d:painel(bb, v, L.data(5, 22, 10), "13:12", E.quadro_parado(v.modo))   -- quinta, 22/10
    H.salvar_pgm(bb, SAIDA .. "/painel-" .. nome .. ".pgm")
end

-- pagina de livro com a linha do topo
local TEXTO = {
    "Capítulo 3",
    "",
    "Era uma vez um pequeno chef que morava dentro",
    "de um computador. Toda vez que alguém pedia",
    "alguma coisa, ele colocava o chapéu, acendia o",
    "fogão e começava a cozinhar: um pouco de Read,",
    "uma pitada de Grep, uma panela inteira de Edit.",
    "",
    "Do outro lado da sala, num Kindle antigo, uma",
    "linha pequena no topo da página acompanhava",
    "tudo sem atrapalhar a leitura. Quando o chef",
    "precisava de uma resposta, a linha ficava preta",
    "e a terceira bolinha acendia.",
    "",
    "A leitora levantava os olhos do livro, dava uma",
    "espiada no computador e voltava para a história.",
}
local function linha_de(dados)
    return E.linha_topo(E.interpretar(dados, agora, { recebido_em = agora, desvio = 0 }))
end
local function pagina(info, arquivo)
    local bb = BB.new(600, 800, BB.TYPE_BB8)
    bb:fill(BB.COLOR_WHITE)
    local face = H.fonte("mono400", 17)
    for i, linha in ipairs(TEXTO) do
        H.RT:renderUtf8Text(bb, 48, 54 + (i - 1) * 34, face, linha, true, false, BB.COLOR_BLACK)
    end
    local rodape = H.fonte("mono400", 13)
    H.RT:renderUtf8Text(bb, 48, 780, rodape, "Página 42 de 310", true, false, BB.Color8(0x55))
    local img = d:linha_topo(info, 1)            -- como o plugin: centralizada, 4 px abaixo do topo
    bb:blitFrom(img, math.floor((600 - img:getWidth()) / 2), 4, 0, 0, img:getWidth(), img:getHeight())
    img:free()
    H.salvar_pgm(bb, SAIDA .. "/" .. arquivo)
end
local uso = { sessao = { pct = 75, hora = "15:00" } }
pagina(linha_de(com{ modo = "cozinhando", desde = agora - 7, sessao = uso.sessao }), "leitura-trabalhando.pgm")
pagina(linha_de(com{ modo = "chamando", desde = agora - 40, sessao = uso.sessao }), "leitura-aprovacao.pgm")
pagina(linha_de(com{ modo = "descansando", desde = agora - 2700, sessao = uso.sessao }), "leitura-descansando.pgm")

-- folha com os estados da linha, em tamanho dobrado
local casos = {
    linha_de(com{ modo = "descansando", desde = agora - 2700, sessao = uso.sessao }),
    linha_de(com{ modo = "cozinhando", desde = agora - 7, sessao = uso.sessao }),
    linha_de(com{ modo = "chamando", desde = agora - 40, sessao = uso.sessao }),
    linha_de(com{ modo = "cozinhando", desde = agora - 7, ativos = 3, sessao = uso.sessao }),
    E.linha_topo(E.interpretar(nil, agora, {})),
}
local imgs, largura, altura = {}, 0, 16
for i, info in ipairs(casos) do
    imgs[i] = d:linha_topo(info, 2)
    largura = math.max(largura, imgs[i]:getWidth())
    altura = altura + imgs[i]:getHeight() + 16
end
local bb = BB.new(largura + 32, altura, BB.TYPE_BB8)
bb:fill(BB.COLOR_WHITE)
local y = 16
for _, img in ipairs(imgs) do
    bb:blitFrom(img, 16, y, 0, 0, img:getWidth(), img:getHeight())
    y = y + img:getHeight() + 16
    img:free()
end
H.salvar_pgm(bb, SAIDA .. "/linha-estados.pgm")
