--[[--
O painel em tela cheia, igual ao do kindle-claude, dentro do KOReader.

Toque em qualquer lugar (ou o botao Voltar) fecha e volta para os livros.
O painel e desenhado deitado e girado para a tela em pe, como no original.
Atualizacoes:
  - estado novo do PC: redesenha tudo (refresh completo quando o modo muda
    e a cada 10 trocas, para limpar fantasmas do e-ink)
  - a cada minuto: so a coluna da esquerda (relogio e "ha X min")
  - animacao: so o retangulo do mascote
]]

local Blitbuffer = require("ffi/blitbuffer")
local Device = require("device")
local Geom = require("ui/geometry")
local GestureRange = require("ui/gesturerange")
local InputContainer = require("ui/widget/container/inputcontainer")
local RenderText = require("ui/rendertext")
local UIManager = require("ui/uimanager")
local Screen = Device.screen

local D = require("claudinho/desenho")
local E = require("claudinho/estado")
local sprites = require("claudinho/sprites")

local TROCAS_ATE_LIMPAR = 10

local Painel = InputContainer:extend{
    name = "claudinho_painel",
    covers_fullscreen = true,
    -- passados por quem abre:
    fonte = nil,          -- function(nome, px) -> face
    ler_estado = nil,     -- function() -> view (estado.interpretar)
    rotacao = 90,         -- 90: logo "kindle" a esquerda; 270: a direita
    animar = true,
    ao_fechar = nil,
}

function Painel:init()
    local sw, sh = Screen:getWidth(), Screen:getHeight()
    self.dimen = Geom:new{ x = 0, y = 0, w = sw, h = sh }
    self.rot = (sw >= sh) and 0 or self.rotacao
    local larg, alt = sw, sh
    if self.rot ~= 0 then larg, alt = sh, sw end         -- espaco disponivel na orientacao deitada
    local k = math.min(larg / D.W, alt / D.H)
    self.desenho = D.novo(Blitbuffer, RenderText, self.fonte, sprites, k)
    self.cw, self.ch = self.desenho:px(D.W), self.desenho:px(D.H)
    self.canvas = Blitbuffer.new(self.cw, self.ch, Blitbuffer.TYPE_BB8)
    local tw, th = self.cw, self.ch
    if self.rot ~= 0 then tw, th = self.ch, self.cw end
    self.ox, self.oy = math.floor((sw - tw) / 2), math.floor((sh - th) / 2)
    self.trocas = 0

    if Device:isTouchDevice() then
        self.ges_events.Tap = { GestureRange:new{ ges = "tap", range = self.dimen } }
    end
    if Device:hasKeys() then
        self.key_events.Fechar = { { Device.input.group.Back } }
    end

    self.tarefa_quadro = function() self:proximo_quadro() end
    self.tarefa_minuto = function() self:minuto() end
    self:redesenhar()
end

-- ------------------------------------------------------------------ canvas -> tela

--- Converte um retangulo do canvas (deitado) para a tela.
function Painel:mapear(r)
    local x, y, w, h
    if self.rot == 90 then
        x, y, w, h = r.y, self.cw - r.x - r.w, r.h, r.w
    elseif self.rot == 270 then
        x, y, w, h = self.ch - r.y - r.h, r.x, r.h, r.w
    else
        x, y, w, h = r.x, r.y, r.w, r.h
    end
    return Geom:new{ x = x + self.ox, y = y + self.oy, w = w, h = h }
end

--- Copia um pedaco do canvas para a imagem da tela (ja girada).
function Painel:copiar(r)
    if not self.tela then return end
    local vista = self.canvas:viewport(r.x, r.y, r.w, r.h)
    local girada = self.rot ~= 0 and vista:rotatedCopy(self.rot) or vista
    local dest = self:mapear(r)
    self.tela:blitFrom(girada, dest.x - self.ox, dest.y - self.oy, 0, 0, dest.w, dest.h)
    if girada ~= vista then girada:free() end
    return dest
end

function Painel:paintTo(bb, x, y)
    if self.ox > 0 or self.oy > 0 then
        bb:paintRect(x, y, self.dimen.w, self.dimen.h, Blitbuffer.COLOR_WHITE)
    end
    if self.tela then
        bb:blitFrom(self.tela, x + self.ox, y + self.oy, 0, 0, self.tela:getWidth(), self.tela:getHeight())
    end
end

-- ------------------------------------------------------------------ atualizacoes

function Painel:redesenhar()
    self.v = self.ler_estado()
    local data, hora = E.data_hora(os.time())
    if not self.seq or self.v.modo ~= self.modo then
        self.seq, self.i = E.sequencia(self.v.modo), 1
    end
    self.modo = self.v.modo
    self.desenho:painel(self.canvas, self.v, data, hora, self.seq[self.i])
    if self.tela then self.tela:free() end
    self.tela = self.rot ~= 0 and self.canvas:rotatedCopy(self.rot) or self.canvas:copy()
end

--- Chamado pelo plugin quando chega estado novo do PC.
function Painel:novo_estado()
    local antes_modo, antes_rev = self.modo, self.v and self.v.rev
    local v = self.ler_estado()
    if v.rev == antes_rev and v.modo == antes_modo then return end
    self:redesenhar()
    self.trocas = self.trocas + 1
    local tipo = "ui"
    if v.modo ~= antes_modo or self.trocas >= TROCAS_ATE_LIMPAR then
        tipo, self.trocas = "full", 0
    end
    UIManager:setDirty(self, function() return tipo, self.dimen end)
end

function Painel:minuto()
    local data, hora = E.data_hora(os.time())
    self.v = self.ler_estado()
    local d, c = self.desenho, self.canvas
    -- coluna da esquerda: relogio e linha "ha X min"
    d:relogio(c, hora)
    d:retangulo(c, 0, 386, 300, 22, d.cor.preto)
    d:texto(c, 30, 389, d:caber(self.v.linha, "mono400", 13, 240), "mono400", 13, d.cor.cAAA, 16)
    d:retangulo(c, 160, 28, 120, 20, d.cor.preto)
    d:texto(c, 270, 30, data, "mono400", 13, d.cor.cAAA, 16, 0, "direita")
    local px = function(v) return d:px(v) end
    local r = { x = 0, y = 0, w = px(300), h = self.ch }
    local dest = self:copiar(r)
    self.trocas = self.trocas + 1
    UIManager:setDirty(self, function() return "ui", dest end)
    self:agendar_minuto()
end

function Painel:agendar_minuto()
    UIManager:unschedule(self.tarefa_minuto)
    local s = 60 - (os.time() % 60) + 1
    UIManager:scheduleIn(s, self.tarefa_minuto)
end

function Painel:proximo_quadro()
    if not self.animar or not self.seq then return end
    self.i = self.i + 1
    if self.i > #self.seq then
        -- acabou a sequencia: sorteia outra (no modo cozinhando)
        self.seq, self.i = E.sequencia(self.modo), 1
    end
    self.desenho:mascote_painel(self.canvas, self.seq[self.i])
    local dest = self:copiar(self.desenho:regiao_mascote_px())
    UIManager:setDirty(self, function() return "ui", dest end)
    UIManager:scheduleIn(E.ATRASO[self.modo] or 1.5, self.tarefa_quadro)
end

function Painel:iniciar_tarefas()
    self:parar_tarefas()
    self:agendar_minuto()
    if self.animar then
        UIManager:scheduleIn(E.ATRASO[self.modo] or 1.5, self.tarefa_quadro)
    end
end

function Painel:parar_tarefas()
    UIManager:unschedule(self.tarefa_quadro)
    UIManager:unschedule(self.tarefa_minuto)
end

-- ------------------------------------------------------------------ eventos

function Painel:onShow()
    self:iniciar_tarefas()
    UIManager:setDirty(self, function() return "full", self.dimen end)
    return true
end

function Painel:onTap()
    UIManager:close(self)
    return true
end
Painel.onFechar = Painel.onTap

function Painel:onSuspend()
    self:parar_tarefas()
end

function Painel:onResume()
    self:redesenhar()
    self:iniciar_tarefas()
    UIManager:setDirty(self, function() return "full", self.dimen end)
end

function Painel:onCloseWidget()
    self:parar_tarefas()
    if self.tela then self.tela:free(); self.tela = nil end
    if self.canvas then self.canvas:free(); self.canvas = nil end
    -- volta para os livros com um refresh completo (limpa o fantasma do painel)
    UIManager:setDirty(nil, "full")
    if self.ao_fechar then self.ao_fechar() end
end

return Painel
