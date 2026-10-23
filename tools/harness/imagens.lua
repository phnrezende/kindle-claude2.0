--[[--
Gera as imagens do README com o codigo de desenho do proprio plugin.

    KO=... KOBASE=... luajit tools/harness/imagens.lua pasta_saida
]]
local H = dofile((debug.getinfo(1, "S").source:sub(2):match("(.*/)") or "./") .. "boot.lua")
local D = require("claudinho/desenho")
local E = require("claudinho/estado")
local sprites = require("claudinho/sprites")
local BB = H.BB
local SAIDA = ... or "."

local agora = os.time()
local base = {
    agora = agora, ativos = 1, projeto = "camaleao", antes = { "mcp:notion", "Bash", "Grep", "Read" },
    sessao = { pct = 11, zera = "zera às 15:00" }, semana = { pct = 19, zera = "zera dom 21:00" },
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
    pronto = com{ modo = "esperando", desde = agora - 125, ferramenta = "", descricao = "nada no fogo" },
    descansando = com{ modo = "descansando", desde = agora - 2700, ferramenta = "", descricao = "nada no fogo" },
}

local d = D.novo(BB, H.RT, H.fonte, sprites, 1)
for nome, dados in pairs(telas) do
    local v = E.interpretar(dados, agora, { recebido_em = agora, desvio = 0 })
    local bb = BB.new(800, 600, BB.TYPE_BB8)
    d:painel(bb, v, "qui 22/10", "13:12", E.quadro_parado(v.modo))
    H.salvar_pgm(bb, SAIDA .. "/painel-" .. nome .. ".pgm")
end

-- pagina de livro com o overlay no canto
local TEXTO = {
    "Capítulo 3",
    "",
    "Era uma vez um pequeno chef que morava dentro",
    "de um computador. Toda vez que alguém pedia",
    "alguma coisa, ele colocava o chapéu, acendia o",
    "fogão e começava a cozinhar: um pouco de Read,",
    "uma pitada de Grep, uma panela inteira de Edit.",
    "",
    "Do outro lado da sala, num Kindle antigo, um",
    "Claudinho menor ainda acompanhava tudo do canto",
    "da página, sem atrapalhar a leitura. Quando o",
    "chef precisava de uma resposta, o cantinho",
    "ficava preto e tocava o sino.",
    "",
    "A leitora levantava os olhos do livro, dava uma",
    "espiada no computador e voltava para a história.",
}
local function pagina(quadro, estilo, arquivo)
    local bb = BB.new(600, 800, BB.TYPE_BB8)
    bb:fill(BB.COLOR_WHITE)
    local face = H.fonte("mono400", 17)
    for i, linha in ipairs(TEXTO) do
        H.RT:renderUtf8Text(bb, 48, 120 + (i - 1) * 34, face, linha, true, false, BB.COLOR_BLACK)
    end
    local rodape = H.fonte("mono400", 13)
    H.RT:renderUtf8Text(bb, 48, 780, rodape, "Página 42 de 310", true, false, BB.Color8(0x55))
    local w = D.tamanho_overlay(sprites, 2)
    d:overlay(bb, 600 - w - 8, 8, quadro, 2, estilo)
    H.salvar_pgm(bb, SAIDA .. "/" .. arquivo)
end
pagina("sopa_1", "normal", "leitura-trabalhando.pgm")
pagina("esperando_1", "alerta", "leitura-aprovacao.pgm")
pagina("descansando_1", "normal", "leitura-descansando.pgm")

-- folha com os estilos do overlay
local w, h = D.tamanho_overlay(sprites, 3)
local casos = { { "sopa_1", "normal" }, { "esperando_1", "alerta" }, { "prato_1", "normal" },
    { "descansando_1", "normal" }, { "descansando_1", "apagado" } }
local bb = BB.new((w + 16) * #casos + 16, h + 32, BB.TYPE_BB8)
bb:fill(BB.COLOR_WHITE)
for i, c in ipairs(casos) do d:overlay(bb, 16 + (i - 1) * (w + 16), 16, c[1], 3, c[2]) end
H.salvar_pgm(bb, SAIDA .. "/overlay-estados.pgm")
