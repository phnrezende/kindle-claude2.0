--[[--
Desenho do painel e do overlay em Blitbuffer (o motor grafico do KOReader).

O painel e desenhado deitado, em 800x600 "unidades de design" vezes uma escala
`k`, com as mesmas posicoes, fontes e espacamentos do render() do kindle-claude
(guithepc, MIT), que por sua vez copiou o design feito no Paper.

Este modulo nao conhece a tela nem o KOReader: recebe o Blitbuffer, o
RenderText e uma funcao que devolve fontes. Assim da para testar fora do Kindle.
]]

local L = require("claudinho/textos")

local D = {}
D.__index = D

D.W, D.H = 800, 600
D.REGIAO_MASCOTE = { x = 40, y = 120, w = 224, h = 152 }   -- area que muda na animacao
D.POS_SPRITE = { x = 42, y = 127 }
D.CELULA = 6

local CORES = { preto = 0x00, c444 = 0x44, c888 = 0x88, cAAA = 0xAA, cD0 = 0xD0, branco = 0xFF }

local floor, sqrt, atan2, abs = math.floor, math.sqrt, math.atan2, math.abs
local function arred(v) return floor(v + 0.5) end

local function n_chars(txt)
    local _, n = txt:gsub("[^\128-\191]", "")
    return n
end

local function sem_ultimo_char(txt)
    return (txt:gsub("[%z\1-\127\194-\244][\128-\191]*$", ""))
end

--[[--
@param BB modulo ffi/blitbuffer
@param RT modulo ui/rendertext
@param fonte function(nome, px) -> face (nomes: inter800, inter900, mono400, mono700)
@param sprites tabela de sprites.lua
@param k escala (1 = 800x600)
]]
function D.novo(BB, RT, fonte, sprites, k)
    local self = setmetatable({ BB = BB, RT = RT, fonte = fonte, sprites = sprites, k = k or 1,
        aneis = {}, faces = {} }, D)
    self.cor = {}
    for nome, v in pairs(CORES) do self.cor[nome] = BB.Color8(v) end
    return self
end

function D:px(v) return arred(v * self.k) end

function D:face(nome, tamanho)
    local chave = nome .. ":" .. tamanho
    local f = self.faces[chave]
    if not f then
        f = self.fonte(nome, tamanho * self.k)
        self.faces[chave] = f
    end
    return f
end

-- ------------------------------------------------------------------ texto

local function metricas(face)
    local m = face.ftsize.metrics
    return tonumber(m.ascender) / 64, -tonumber(m.descender) / 64
end

--- Largura em pixels reais (com letter-spacing `ls` em unidades de design).
function D:largura_px(txt, face, ls)
    if not txt or txt == "" then return 0 end
    local w = self.RT:sizeUtf8Text(0, nil, face, txt, true, false).x
    return w + (ls or 0) * self.k * n_chars(txt)
end

function D:largura(txt, nome, tamanho, ls)
    return self:largura_px(txt, self:face(nome, tamanho), ls) / self.k
end

--- Corta o texto com "…" para caber em `max_w` (unidades de design).
function D:caber(txt, nome, tamanho, max_w, ls)
    if self:largura(txt, nome, tamanho, ls) <= max_w then return txt end
    while txt ~= "" and self:largura(txt .. "…", nome, tamanho, ls) > max_w do
        txt = sem_ultimo_char(txt)
    end
    return (txt:gsub("%s+$", "")) .. "…"
end

--[[--
Desenha como o CSS do Paper: caixa de linha `alt_linha`, letter-spacing `ls`.
x, topo, alt_linha e ls em unidades de design. Devolve a largura (design).
]]
function D:texto(bb, x, topo, txt, nome, tamanho, cor, alt_linha, ls, alinhar)
    if not txt or txt == "" then return 0 end
    ls = ls or 0
    local face = self:face(nome, tamanho)
    local asc, desc = metricas(face)
    local k = self.k
    local w = self:largura_px(txt, face, ls)
    local X = x * k
    if alinhar == "direita" then
        X = X - w
    elseif alinhar == "centro" then
        X = X - w / 2
    end
    local baseline = topo * k + (alt_linha * k - (asc + desc)) / 2 + asc
    local pads
    if ls ~= 0 then
        pads = {}
        for i = 1, n_chars(txt) do
            pads[i] = arred(ls * k * i) - arred(ls * k * (i - 1))
        end
    end
    self.RT:renderUtf8Text(bb, arred(X), arred(baseline), face, txt, true, false, cor, nil, pads)
    return w / k
end

-- ------------------------------------------------------------------ formas

function D:retangulo(bb, x, y, w, h, cor)
    local x0, y0 = self:px(x), self:px(y)
    bb:paintRect(x0, y0, self:px(x + w) - x0, self:px(y + h) - y0, cor)
end

local function misturar(fundo, frente, cobertura)
    return arred(fundo + (frente - fundo) * cobertura)
end

--- Anel de 24 segmentos, 170x170, como o do Paper. Fica em cache por % e escala.
function D:anel(bb, x, y, pct)
    local cheios = 0
    if pct then
        cheios = math.max(pct > 0 and 1 or 0, math.min(24, arred(pct * 24 / 100)))
    end
    local lado = self:px(170)
    local img = self.aneis[cheios]
    if not img then
        img = self.BB.new(lado, lado, self.BB.TYPE_BB8)
        img:fill(self.cor.branco)
        local k, AMOSTRAS = self.k, 3
        local R, r = 85, 67
        local passo = 1 / AMOSTRAS
        for py = 0, lado - 1 do
            for px = 0, lado - 1 do
                local cy0, cx0 = (py + 0.5) / k - 85, (px + 0.5) / k - 85
                local d0 = sqrt(cx0 * cx0 + cy0 * cy0)
                if d0 > r - 2 and d0 < R + 2 then
                    local cheio, vazio = 0, 0
                    for sy = 0, AMOSTRAS - 1 do
                        local dy = (py + (sy + 0.5) * passo) / k - 85
                        for sx = 0, AMOSTRAS - 1 do
                            local dx = (px + (sx + 0.5) * passo) / k - 85
                            local dist = sqrt(dx * dx + dy * dy)
                            if dist <= R and dist >= r then
                                local ang = (atan2(dy, dx) * 180 / math.pi + 90 - 2.04) % 360
                                local seg = floor(ang / 15)
                                if ang - seg * 15 < 10.92 then
                                    if seg < cheios then cheio = cheio + 1 else vazio = vazio + 1 end
                                end
                            end
                        end
                    end
                    if cheio + vazio > 0 then
                        local total = AMOSTRAS * AMOSTRAS
                        local branco = total - cheio - vazio
                        local v = (cheio * CORES.preto + vazio * CORES.cD0 + branco * 0xFF) / total
                        img:setPixel(px, py, self.BB.Color8(arred(v)))
                    end
                end
            end
        end
        self.aneis[cheios] = img
    end
    bb:blitFrom(img, self:px(x), self:px(y), 0, 0, lado, lado)
end

local function dist_segmento(px, py, x0, y0, x1, y1)
    local vx, vy = x1 - x0, y1 - y0
    local t = ((px - x0) * vx + (py - y0) * vy) / (vx * vx + vy * vy)
    t = math.max(0, math.min(1, t))
    local dx, dy = px - (x0 + t * vx), py - (y0 + t * vy)
    return sqrt(dx * dx + dy * dy)
end

--- O ✳ do status (as fontes nao tem esse simbolo): 4 tracos de 2 px.
function D:asterisco(bb, cx, cy, raio, cor_v, fundo_v)
    local k = self.k
    local q = raio * 0.7071
    local tracos = {
        { cx - raio, cy, cx + raio, cy }, { cx, cy - raio, cx, cy + raio },
        { cx - q, cy - q, cx + q, cy + q }, { cx - q, cy + q, cx + q, cy - q },
    }
    local x0, x1 = floor((cx - raio - 2) * k), floor((cx + raio + 2) * k)
    local y0, y1 = floor((cy - raio - 2) * k), floor((cy + raio + 2) * k)
    for py = y0, y1 do
        for px = x0, x1 do
            local hits = 0
            for sy = 0, 2 do
                for sx = 0, 2 do
                    local ux, uy = (px + (sx + 0.5) / 3) / k, (py + (sy + 0.5) / 3) / k
                    for _, t in ipairs(tracos) do
                        if dist_segmento(ux, uy, t[1], t[2], t[3], t[4]) <= 1 then
                            hits = hits + 1
                            break
                        end
                    end
                end
            end
            if hits > 0 then
                bb:setPixel(px, py, self.BB.Color8(misturar(fundo_v, cor_v, hits / 9)))
            end
        end
    end
end

--[[--
Pinta um quadro do mascote com celulas de `cel` pixels reais.
cores: { traco = Color8, cinza = Color8, fundo = Color8 ou nil }
]]
function D:sprite(bb, x_px, y_px, nome, cel, cores)
    local grade = self.sprites.quadros[nome] or self.sprites.quadros.descansando_1
    if cores.fundo then
        bb:paintRect(x_px, y_px, self.sprites.largura * cel, self.sprites.altura * cel, cores.fundo)
    end
    for y, linha in ipairs(grade) do
        for x = 1, #linha do
            local ch = linha:sub(x, x)
            if ch ~= "." then
                bb:paintRect(x_px + (x - 1) * cel, y_px + (y - 1) * cel, cel, cel,
                    ch == "#" and cores.traco or cores.cinza)
            end
        end
    end
end

function D:celula_painel()
    return math.max(1, floor(D.CELULA * self.k))
end

--- Desenha so o mascote do painel (para a animacao trocar quadros).
function D:mascote_painel(bb, nome)
    local c = self.cor
    local reg = D.REGIAO_MASCOTE
    self:retangulo(bb, reg.x, reg.y, reg.w, reg.h, c.preto)
    local cel = self:celula_painel()
    -- centraliza o desenho na area original de 216x144 quando a celula foi arredondada
    local w, h = self.sprites.largura * cel, self.sprites.altura * cel
    local x = self:px(D.POS_SPRITE.x) + floor((self:px(216) - w) / 2)
    local y = self:px(D.POS_SPRITE.y) + floor((self:px(144) - h) / 2)
    self:sprite(bb, x, y, nome, cel, { traco = c.branco, cinza = c.c888 })
end

--- Regiao do mascote em pixels reais do canvas.
function D:regiao_mascote_px()
    local r = D.REGIAO_MASCOTE
    local x, y = self:px(r.x), self:px(r.y)
    return { x = x, y = y, w = self:px(r.x + r.w) - x, h = self:px(r.y + r.h) - y }
end

-- ------------------------------------------------------------------ painel

--[[--
Desenha o painel inteiro (deitado) em `bb`, que deve ter 800k x 600k.
@param v o que estado.interpretar() devolveu
@param data "qui 22/10"
@param hora "13:12"
@param quadro nome do quadro do mascote
]]
function D:painel(bb, v, data, hora, quadro)
    local c = self.cor
    bb:fill(c.branco)

    -- painel do mascote (preto)
    self:retangulo(bb, 0, 0, 300, D.H, c.preto)
    self:texto(bb, 30, 30, "CLAUDE CODE", "mono700", 13, c.branco, 16, 13 * 0.14)
    self:texto(bb, 270, 30, data, "mono400", 13, c.cAAA, 16, 0, "direita")
    self:mascote_painel(bb, quadro)

    self:asterisco(bb, 40.5, 368, 10, CORES.branco, CORES.preto)
    self:texto(bb, 59, 351, self:caber(v.titulo, "inter800", 28, 240, -0.56), "inter800", 28, c.branco, 32, -0.56)
    self:texto(bb, 30, 389, self:caber(v.linha, "mono400", 13, 240), "mono400", 13, c.cAAA, 16)
    self:relogio(bb, hora)

    -- painel de dados (branco)
    self:texto(bb, 330, 30, L.t("painel_no_fogo"), "mono700", 12, c.c444, 16, 12 * 0.16)
    if (v.agentes or "") ~= "" then
        self:texto(bb, 770, 30, v.agentes, "mono700", 12, c.c444, 16, 12 * 0.16, "direita")
    end
    self:retangulo(bb, 330, 54, 440, 36, c.preto)
    self:texto(bb, 342, 63, "▶", "mono700", 15, c.branco, 18)
    local x = 364
    if v.ferramenta ~= "" then
        x = x + self:texto(bb, x, 63, self:caber(v.ferramenta, "mono700", 15, 200), "mono700", 15, c.branco, 18) + 10
    end
    self:texto(bb, x, 63, self:caber(v.descricao, "mono400", 15, 758 - x), "mono400", 15, c.branco, 18)

    -- a lista comeca onde o rotulo termina ("antes:" no original, "before:" em ingles)
    local xa = math.max(399, 342 + self:texto(bb, 342, 98, L.t("painel_antes"), "mono400", 13, c.c888, 16) + 8)
    self:texto(bb, xa, 98, self:caber(v.antes, "mono400", 13, 770 - xa), "mono400", 13, c.c888, 16)

    for _, item in ipairs({ { 434, v.sessao, L.t("painel_sessao") }, { 666, v.semana, L.t("painel_semana") } }) do
        local cx, lim, rotulo = item[1], item[2], item[3]
        self:anel(bb, cx - 85, 200, lim.pct)
        self:texto(bb, cx, 252, lim.txt, "inter900", 52, c.preto, 50, -2.08, "centro")
        self:texto(bb, cx, 304, rotulo, "mono700", 11, c.c444, 14, 11 * 0.16, "centro")
        self:texto(bb, cx, 380, self:caber(lim.zera, "mono400", 13, 220), "mono400", 13, c.c444, 16, 0, "centro")
    end

    self:retangulo(bb, 330, 483, 440, 3, c.preto)
    self:texto(bb, 330, 504, L.t("painel_tokens_hoje"), "mono700", 12, c.c444, 16, 12 * 0.16)
    self:texto(bb, 330, 524, v.tokens_hoje, "inter900", 48, c.preto, 46, -1.92)
    local w = self:texto(bb, 770, 534, v.tokens_hora, "mono400", 13, c.c444, 16, 0, "direita")
    self:texto(bb, 770 - w - 6, 534, "▲", "mono400", 13, c.c444, 16, 0, "direita")
    self:texto(bb, 770, 554, v.tokens_media, "mono400", 13, c.c444, 16, 0, "direita")
end

D.REGIAO_RELOGIO = { x = 0, y = 470, w = 300, h = 120 }

--- Redesenha so o relogio (troca a cada minuto sem mexer no resto).
function D:relogio(bb, hora)
    local r = D.REGIAO_RELOGIO
    self:retangulo(bb, r.x, r.y, r.w, r.h, self.cor.preto)
    self:texto(bb, 30, 486, hora, "inter900", 92, self.cor.branco, 84, -4.6)
end

function D:regiao_relogio_px()
    local r = D.REGIAO_RELOGIO
    local x, y = self:px(r.x), self:px(r.y)
    return { x = x, y = y, w = self:px(r.x + r.w) - x, h = self:px(r.y + r.h) - y }
end

-- ------------------------------------------------------------------ overlay

D.ESTILOS = {
    normal = { fundo = 0xFF, borda = 0x00, traco = 0x00, cinza = 0x88 },
    alerta = { fundo = 0x00, borda = 0x00, traco = 0xFF, cinza = 0xAA },   -- pedindo aprovacao
    apagado = { fundo = 0xFF, borda = 0xAA, traco = 0xAA, cinza = 0xD0 }, -- sem sinal do PC
}

--- Tamanho da caixa do overlay em pixels para uma celula de `cel` px.
function D.tamanho_overlay(sprites, cel)
    local pad = cel * 2
    return sprites.largura * cel + 2 * pad, sprites.altura * cel + 2 * pad
end

--- Caixinha do mascote para o canto da pagina. Desenha direto na tela.
function D:overlay(bb, x, y, nome, cel, estilo)
    local e = D.ESTILOS[estilo] or D.ESTILOS.normal
    local C8 = self.BB.Color8
    local w, h = D.tamanho_overlay(self.sprites, cel)
    local borda = math.max(1, floor(cel / 1.5))
    bb:paintRect(x, y, w, h, C8(e.fundo))
    bb:paintBorder(x, y, w, h, borda, C8(e.borda), 0)
    local pad = cel * 2
    self:sprite(bb, x + pad, y + pad, nome, cel, { traco = C8(e.traco), cinza = C8(e.cinza) })
end

return D
