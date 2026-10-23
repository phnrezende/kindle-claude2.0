--[[--
Teste de fumaca do plugin inteiro, fora do Kindle.

Carrega o main.lua e o painel.lua de verdade com um KOReader simulado (UIManager,
menu, tela, configuracoes), faz a busca real em subprocesso contra o agente do
PC (via curl, ja que o LuaJIT puro nao tem sockets) e salva as telas:

    KO=... KOBASE=... luajit tools/harness/fumaca.lua URL TOKEN pasta_saida

Confere: a linha do topo aparece centralizada, inverte pedindo permissao e reserva
so o espaco dela na margem de cima; o painel abre em pe (girado), anima so o
mascote e fecha com um toque.
]]
local H = dofile((debug.getinfo(1, "S").source:sub(2):match("(.*/)") or "./") .. "boot.lua")
local BB = H.BB
io.stdout:setvbuf("no")   -- o fork dos subprocessos duplicaria o buffer
local URL, TOKEN, SAIDA = ...
assert(URL and SAIDA, "uso: fumaca.lua URL TOKEN pasta")

local falhas = 0
local function confere(cond, msg)
    io.write(cond and "  ok   " or "  FALHOU ", msg, "\n")
    if not cond then falhas = falhas + 1 end
end

-- ------------------------------------------------------------------ KOReader simulado

package.preload["dbg"] = function()
    return setmetatable({}, { __index = function() return function() end end })
end
local Geom = require("ui/geometry")
local TELA_W, TELA_H = 600, 800
local tela = BB.new(TELA_W, TELA_H, BB.TYPE_BB8)

local Screen = {
    getWidth = function() return TELA_W end,
    getHeight = function() return TELA_H end,
    scaleBySize = function(_, px) return math.ceil(px * math.min(TELA_W, TELA_H) / 600) end,
    bb = tela,
}
local Device = {
    screen = Screen,
    isKindle = function() return false end,
    isTouchDevice = function() return true end,
    hasKeys = function() return false end,
    input = { group = { Back = {} } },
}
package.preload["device"] = function() return Device end

local relogio = os.time()
local tarefas, pilha, sujos, refreshes = {}, {}, {}, {}
local UIManager = {}
function UIManager:scheduleIn(s, f) tarefas[#tarefas + 1] = { t = relogio + s, f = f } end
function UIManager:nextTick(f) self:scheduleIn(0, f) end
function UIManager:unschedule(f)
    for i = #tarefas, 1, -1 do if tarefas[i].f == f then table.remove(tarefas, i) end end
end
function UIManager:show(w)
    if w.mensagem then return end          -- InfoMessage: fica registrada em `mensagens`
    pilha[#pilha + 1] = w
    if w.onShow then w:onShow() end
end
local eventos = {}
function UIManager:broadcastEvent(ev) eventos[#eventos + 1] = ev end
function UIManager:close(w)
    for i = #pilha, 1, -1 do
        if pilha[i] == w then table.remove(pilha, i) end
    end
    if w.onCloseWidget then w:onCloseWidget() end
    sujos[#sujos + 1] = "all"
end
function UIManager:setDirty(w, tipo, regiao)
    if type(tipo) == "function" then tipo, regiao = tipo() end
    sujos[#sujos + 1] = w or "nil"
    refreshes[#refreshes + 1] = { tipo = tipo, regiao = regiao, w = w }
end
function UIManager:forceRePaint() end
package.preload["ui/uimanager"] = function() return UIManager end

-- avanca o tempo simulado rodando as tarefas; espera de verdade pelo subprocesso
local function rodar(segundos)
    local fim = relogio + segundos
    while true do
        table.sort(tarefas, function(a, b) return a.t < b.t end)
        local prox = tarefas[1]
        if not prox or prox.t > fim then break end
        table.remove(tarefas, 1)
        if prox.t > relogio then relogio = prox.t end
        os.execute("sleep 0.05")
        prox.f()
    end
    relogio = fim
end

local Widget = {}
function Widget:extend(o) o = o or {}; setmetatable(o, self); self.__index = self; return o end
function Widget:new(o) o = self:extend(o); if o._init then o:_init() end; if o.init then o:init() end; return o end
local InputContainer = Widget:extend{}
function InputContainer:_init() self.ges_events, self.key_events = {}, {} end
package.preload["ui/widget/container/inputcontainer"] = function() return InputContainer end
package.preload["ui/widget/container/widgetcontainer"] = function() return Widget:extend{} end
package.preload["ui/gesturerange"] = function() return { new = function(_, o) return o end } end
local mensagens = {}
package.preload["ui/widget/infomessage"] = function()
    return { new = function(_, o)
        mensagens[#mensagens + 1] = o.text
        print("  [mensagem] " .. o.text:gsub("\n", " | "))
        return { mensagem = true }
    end }
end
package.preload["ui/event"] = function()
    return { new = function(_, nome, ...) return { name = nome, args = { ... } } end }
end
package.preload["ui/widget/notification"] = function()
    return { SOURCE_ALWAYS_SHOW = 0x8000, notify = function(_, t) print("  [aviso] " .. t) end }
end
package.preload["ui/widget/inputdialog"] = function() return { new = function() return {} end } end
-- como no KOReader: guarda a tabela do primeiro registro e ignora os seguintes
local acoes = {}
package.preload["dispatcher"] = function()
    return { registerAction = function(_, nome, valor) if acoes[nome] == nil then acoes[nome] = valor end end }
end
package.preload["pluginshare"] = function() return {} end
package.preload["datastorage"] = function() return { getSettingsDir = function() return "/tmp" end } end
package.preload["luasettings"] = function()
    -- como no KOReader, o mesmo arquivo aberto de novo traz o que foi gravado
    local S, arquivos = {}, {}
    function S:open(caminho)
        arquivos[caminho] = arquivos[caminho] or {}
        return setmetatable({ d = arquivos[caminho] }, { __index = S })
    end
    function S:readSetting(k) return self.d[k] end
    function S:saveSetting(k, v) self.d[k] = v end
    function S:delSetting(k) self.d[k] = nil end
    function S:flush() end
    return S
end
-- o boot.lua ja carregou um ui/font minimo (para o RenderText); completa ele
require("ui/font").getFace = function(_, caminho, tam)
    local px = Screen:scaleBySize(tam)
    return { ftsize = require("ffi/freetype").newFaceSize(caminho, px), hash = caminho .. px, orig_size = tam, size = px }
end

-- LuaSocket simulado com curl, para rodar dentro do subprocesso
package.preload["socketutil"] = function()
    return { set_timeout = function() end, reset_timeout = function() end }
end
package.preload["ltn12"] = function()
    return { sink = { table = function(t) return function(chunk) if chunk then t[#t + 1] = chunk end return 1 end end } }
end
package.preload["socket"] = function() return { skip = function(n, ...) return select(n + 1, ...) end } end
package.preload["socket.http"] = function()
    return { request = function(req)
        local cab = ""
        for k, v in pairs(req.headers or {}) do cab = cab .. string.format(" -H '%s: %s'", k, v) end
        local p = io.popen("curl -s -m 5 -D /tmp/fumaca_cab.txt" .. cab .. " '" .. req.url .. "'")
        local corpo = p:read("*a")
        p:close()
        local hdrs, codigo = {}, nil
        for linha in io.lines("/tmp/fumaca_cab.txt") do
            codigo = codigo or tonumber(linha:match("^HTTP/%S+ (%d+)"))
            local k, v = linha:match("^([^:]+):%s*(.-)%s*$")
            if k then hdrs[k:lower()] = v end
        end
        if not codigo then return nil, "conexao recusada" end
        req.sink(corpo)
        return 1, codigo, hdrs, "HTTP " .. codigo
    end }
end

-- ------------------------------------------------------------------ cenario

package.path = H.PLUGIN .. "?.lua;" .. package.path
local Claudinho = dofile(H.PLUGIN .. "main.lua")
Claudinho.path = H.PLUGIN:gsub("/$", "")

local menu_registrado
local leitor = {
    menu = { registerToMainMenu = function(_, p) menu_registrado = p end },
    view = {
        footer_visible = true,
        footer = {
            getHeight = function() return 30 end,
            -- o "conteudo externo" do rodape do KOReader (ReaderFooter)
            conteudo = {},
            addAdditionalFooterContent = function(self, f) table.insert(self.conteudo, f) end,
            removeAdditionalFooterContent = function(self, f)
                for i, v in ipairs(self.conteudo) do
                    if v == f then table.remove(self.conteudo, i) return end
                end
            end,
        },
        registerViewModule = function(self, nome, w) self.modulo = w end,
    },
    document = {},
}
UIManager:show(leitor)

local function pagina()
    -- uma "pagina de livro" falsa e o overlay por cima, como o ReaderView faz
    tela:fill(BB.COLOR_WHITE)
    for y = 60, 740, 28 do tela:paintRect(40, y, 520 - (y * 7 % 120), 10, BB.Color8(0x55)) end
    leitor.view.modulo:paintTo(tela, 0, 0)
end

print("1. plugin no leitor")
local p = Claudinho:new{ ui = leitor }
confere(menu_registrado == p, "registrou o menu")
local fonte = p:arquivo_fonte("InterTight-ExtraBold.ttf")
local arq = io.open(fonte, "rb")
if arq then arq:close() end
confere(arq ~= nil and fonte:match("^%.%./") ~= nil,
    "caminho da fonte sobe ate a raiz (o getFace do KOReader 2026.07 poe ./fonts/ na frente) e abre")
local itens = {}
p:addToMainMenu(itens)
confere(itens.claudinho and #itens.claudinho.sub_item_table == 7, "menu com 7 itens")
local function item(t, n) return t.sub_item_table[n] end
local idioma = item(itens.claudinho, 6)
require("claudinho/textos").escolher("pt")
confere(item(itens.claudinho, 1).text_func() == "Abrir o painel", "menu em portugues")
item(idioma, 3).callback()          -- English
confere(item(itens.claudinho, 1).text_func() == "Open the panel" and p.settings:readSetting("idioma") == "en",
    "trocar para ingles muda o menu na hora e fica salvo")
confere(idioma.text_func() == "Language: English", "item do idioma: " .. idioma.text_func())
confere(acoes.claudinho_painel.title == "Claudinho: open the panel", "nome do gesto tambem muda")
item(idioma, 2).callback()          -- Portugues
confere(item(itens.claudinho, 1).text_func() == "Abrir o painel", "volta para portugues")
p.settings:saveSetting("url", URL)
p.settings:saveSetting("token", TOKEN)
p:onReaderReady()
confere(leitor.view.modulo ~= nil, "linha registrada no ReaderView")
rodar(5)
confere(p:vista().modo ~= "sem_sinal", "leu o estado do PC: " .. p:vista().titulo)
local ultimo = refreshes[#refreshes]
confere(ultimo and ultimo.w == leitor and ultimo.tipo == "ui" and ultimo.regiao and ultimo.regiao.h == 20,
    "pediu refresh 'ui' so da faixa da linha")
pagina()
local info = p:linha_alvo()
local r = p:linha_retangulo(p.linha_img:getWidth())
confere(math.abs(r.x + r.w / 2 - TELA_W / 2) <= 1 and r.y == 4 and r.h == 20, "linha centralizada no topo")
confere(info.estado == 3 and info.alerta, "demo 'chamando': terceira bolinha, em alerta")
confere(tela:getPixel(r.x + 2, r.y + r.h / 2):getColor8().a < 0x40, "pedindo permissao: pilula preta")
H.salvar_pgm(tela, SAIDA .. "/leitura.pgm")

print("1b. testar a conexao com outra busca em andamento")
local avisado = false
p:buscar()
p:buscar(function() avisado = true end)
confere(not avisado, "espera a busca que ja estava rodando")
rodar(3)
confere(avisado, "avisa quando ela termina")

print("2. sem mudanca: nao repinta")
local n = #refreshes
rodar(61)
confere(#refreshes == n, "nenhum refresh quando a linha nao muda")

print("3. desligar e ligar a linha")
p:mudar("overlay", false)
local ult = refreshes[#refreshes].regiao
confere(ult and ult.x == 0 and ult.w == TELA_W and ult.y == 4, "desligada: refresca a faixa toda do topo")
pagina()
local limpo = true
for x = 0, TELA_W - 1, 2 do
    if tela:getPixel(x, 14):getColor8().a < 0xF0 then limpo = false end
end
confere(limpo, "desligada: nada desenhado no topo")
p:mudar("overlay", true)
pagina()
confere(p.linha_pintada ~= nil, "ligada de novo: volta")
n = #refreshes

print("4. painel")
p:abrir_painel()
local painel = pilha[#pilha]
confere(painel and painel.name == "claudinho_painel" and painel.covers_fullscreen, "painel aberto por cima")
confere(painel.rot == 90 and painel.tela:getWidth() == 600 and painel.tela:getHeight() == 800, "painel girado para a tela em pe")
rodar(4)
local animou = false
for i = n + 1, #refreshes do
    local f = refreshes[i]
    if f.w == painel and f.regiao and f.regiao.w < 300 then animou = true end
end
confere(animou, "animacao atualiza so a regiao do mascote")
tela:fill(BB.COLOR_WHITE)
painel:paintTo(tela, 0, 0)
H.salvar_pgm(tela, SAIDA .. "/painel.pgm")

print("4b. painel parado: limpa os fantasmas mesmo sem estado novo")
painel.trocas = 0
local antes_min = #refreshes
for _ = 1, 10 do painel:minuto() end
local completos = 0
for i = antes_min + 1, #refreshes do
    local f = refreshes[i]
    if f.w == painel and f.tipo == "full" then completos = completos + 1 end
end
confere(completos == 1, "10 minutos sem estado novo: 1 refresh completo (" .. completos .. ")")
painel:onTap()
confere(pilha[#pilha] == leitor and p.painel == nil, "um toque fecha e volta para o livro")

print("4c. espaco para a linha: so a margem de cima sobe")
leitor.rolling, leitor.view.view_mode = {}, "page"
leitor.document.getHeaderHeight = function() return 0 end
local suas = { h_page_margins = { 10, 10 }, t_page_margin = 15, b_page_margin = 15 }   -- o que o livro grava
leitor.document.configurable = suas
leitor.typeset = { unscaled_margins = { 10, 15, 10, 15 } }
local aplicadas = 0
leitor.handleEvent = function(_, ev)
    if ev.name ~= "SetPageMargins" then return end
    aplicadas = aplicadas + 1
    p:onSetPageMargins(ev.args[1])      -- como no KOReader, o evento chega tambem ao plugin
end
local function margens() return table.concat(leitor.typeset.unscaled_margins, ",") end
-- voce muda a margem de cima no menu de baixo: o KOReader grava e aplica
local function voce_poe(t)
    suas.t_page_margin = t
    leitor.typeset.unscaled_margins = { 10, t, 10, suas.b_page_margin }
    leitor:handleEvent({ name = "SetPageMargins", args = { leitor.typeset.unscaled_margins } })
    rodar(0)
end
local pede = p:margem_necessaria({ 10, 15, 10, 15 })
confere(pede == 28, "margem de cima 15 (a padrao): a linha pede 28 (" .. tostring(pede) .. ")")
confere(p:margem_necessaria({ 10, 40, 10, 15 }) == nil, "margem de cima 40: ja cabe")
p:onPreRenderDocument()
confere(margens() == "10,28,10,15", "antes de paginar: so a de cima sobe, para 28 (" .. margens() .. ")")
confere(suas.t_page_margin == 15, "a margem gravada no livro continua a sua")
rodar(0)
confere(p:margem_necessaria() == nil, "a linha nao cobre mais o texto")
confere(aplicadas == 1, "sem laco: o evento que volta nao muda nada (" .. aplicadas .. ")")
voce_poe(20)
confere(margens() == "10,28,10,15" and suas.t_page_margin == 20, "voce poe 20: a pagina fica com 28, o livro guarda 20")
voce_poe(80)
confere(margens() == "10,80,10,15", "voce poe 80 (mais que o preciso): fica 80")
voce_poe(15)
p:mudar("overlay", false)
confere(margens() == "10,15,10,15", "linha desligada: a sua margem volta")
p:mudar("overlay", true)
confere(margens() == "10,28,10,15", "ligada de novo: reserva de novo")
leitor.document.getHeaderHeight = function() return 25 end      -- cabecalho do livro ligado
confere(p:linha_retangulo().y == 29 and p:margem_necessaria({ 10, 15, 10, 15 }) == 28,
    "com o cabecalho do livro, a linha vai abaixo dele e pede a mesma margem")
leitor.document.getHeaderHeight = function() return 0 end
leitor.rolling = nil                    -- PDF: pagina fixa
local ok_pdf = pcall(function() p:mudar("overlay", false); rodar(0); p:mudar("overlay", true); rodar(0) end)
confere(ok_pdf and margens() == "10,28,10,15", "PDF: nao mexe em nada, sem erro")
leitor.rolling, leitor.typeset, leitor.document.configurable, leitor.handleEvent = nil, nil, nil, nil
leitor.view.view_mode, leitor.document.getHeaderHeight = nil, nil

print("5. PC some")
p.settings:saveSetting("url", "http://127.0.0.1:1/estado.json")
for _ = 1, 3 do p:buscar(); rodar(2) end
confere(p:vista().modo == "sem_sinal", "depois de 3 falhas mostra 'sem sinal'")
local info5 = p:linha_alvo()
confere(info5.estado == nil and info5.pct == "--", "linha: nenhuma bolinha cheia e '--'")
pagina()
H.salvar_pgm(tela, SAIDA .. "/leitura_sem_sinal.pgm")

print("6. um erro no plugin nao quebra a pagina")
local E = require("claudinho/estado")
local original = E.interpretar
E.interpretar = function() error("erro de teste") end
p:atualizar_linha(true)
local ok_pagina = pcall(pagina)
local ok_busca = pcall(function() p:buscar(); rodar(2) end)
local ok_painel = pcall(function() p:abrir_painel(); rodar(2); pilha[#pilha]:onTap() end)
E.interpretar = original
confere(ok_painel and p.painel == nil, "o painel abre (com o minimo) e fecha")
confere(ok_pagina, "o livro continua sendo desenhado")
confere(ok_busca, "a busca e a atualizacao seguem sem erro")
p.linha_pintada = nil
pagina()
confere(p.linha_pintada ~= nil, "com o erro corrigido, a linha volta")

print("7. Kindle: o protetor de tela volta mesmo se o KOReader fechar com o painel aberto")
local executar = os.execute
local lipc = {}
os.execute = function(c)
    if tostring(c):find("lipc") then lipc[#lipc + 1] = c return 0 end
    return executar(c)
end
Device.isKindle = function() return true end
p:abrir_painel()
confere(lipc[#lipc] and lipc[#lipc]:find("preventScreenSaver 1") and p.settings:readSetting("tela_acordada") == true,
    "painel aberto: Kindle acordado, e a marca gravada")
pilha[#pilha]:onTap()
confere(lipc[#lipc]:find("preventScreenSaver 0") and p.settings:readSetting("tela_acordada") == nil,
    "painel fechado: protetor de tela de volta, marca apagada")
p.settings:saveSetting("tela_acordada", true)       -- como se o KOReader travasse com o painel aberto
local antes_lipc = #lipc
local Claudinho2 = dofile(H.PLUGIN .. "main.lua")   -- o KOReader abre de novo
Claudinho2.path = H.PLUGIN:gsub("/$", "")
local p2 = Claudinho2:new{ ui = leitor }
confere(#lipc == antes_lipc + 1 and lipc[#lipc]:find("preventScreenSaver 0") ~= nil
    and p2.settings:readSetting("tela_acordada") == nil, "no inicio seguinte, devolve o protetor de tela")
os.execute = executar
Device.isKindle = function() return false end
p2:onCloseWidget()

p:onCloseWidget()
local agendada = false
for _, t in ipairs(tarefas) do if t.f == p.tarefa then agendada = true end end
confere(p.fechado and not agendada, "fechou: nenhuma busca agendada")
print(falhas == 0 and "TUDO CERTO" or (falhas .. " FALHA(S)"))
os.exit(falhas == 0 and 0 or 1)
