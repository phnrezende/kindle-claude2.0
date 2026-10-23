--[[--
Teste de fumaca do plugin inteiro, fora do Kindle.

Carrega o main.lua e o painel.lua de verdade com um KOReader simulado (UIManager,
menu, tela, configuracoes), faz a busca real em subprocesso contra o agente do
PC (via curl, ja que o LuaJIT puro nao tem sockets) e salva as telas:

    KO=... KOBASE=... luajit tools/harness/fumaca.lua URL TOKEN pasta_saida

Confere: o overlay aparece no canto certo e muda de estilo, o painel abre em
pe (girado), anima so o mascote e fecha com um toque.
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
confere(leitor.view.modulo ~= nil, "overlay registrado no ReaderView")
rodar(5)
confere(p:vista().modo ~= "sem_sinal", "leu o estado do PC: " .. p:vista().titulo)
local ultimo = refreshes[#refreshes]
confere(ultimo and ultimo.w == leitor and ultimo.tipo == "ui", "pediu refresh 'ui' so do cantinho")
pagina()
local r = p:overlay_retangulo()
confere(r.x + r.w == TELA_W - 8 and r.y == 8, "overlay no canto superior direito com margem")
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
confere(#refreshes == n, "nenhum refresh quando o overlay nao muda")

print("3. canto inferior esquerdo respeita a barra de status")
p:mudar("overlay_canto", "inferior_esquerdo")
local r2 = p:overlay_retangulo()
confere(r2.x == 8 and r2.y + r2.h == TELA_H - 8 - 30, "acima do rodape do KOReader")
pagina()
H.salvar_pgm(tela, SAIDA .. "/leitura_inferior.pgm")
p:mudar("overlay_canto", "superior_direito")

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

print("4c. na barra de status")
local footer = leitor.view.footer
p:mudar("overlay_onde", "barra")
confere(#footer.conteudo == 1, "o texto do Claudinho entrou na barra de status")
confere(footer.conteudo[1]() == "Claude: TE CHAMANDO!", "texto da barra: " .. tostring(footer.conteudo[1]()))
confere(p:overlay_alvo() == false, "e o Claudinho some do canto")
local pediu = false
for _, ev in ipairs(eventos) do if ev.name == "RefreshAdditionalContent" then pediu = true end end
confere(pediu, "pede para o rodape redesenhar")
p:mudar("overlay_onde", "canto")
confere(#footer.conteudo == 0 and p:overlay_alvo() == true, "de volta ao canto, sai da barra")

print("4d. aviso quando o Claudinho cobre o texto")
leitor.rolling, leitor.view.view_mode = {}, "page"
leitor.document.getHeaderHeight = function() return 0 end
leitor.typeset = { unscaled_margins = { 10, 15, 10, 15 } }     -- as margens padrao do KOReader
local qual, valor = p:margem_necessaria()
confere(qual == "cima" and valor == 66, "margem de cima 15: cobre; pede 66 (" .. tostring(valor) .. ")")
local n_msg = #mensagens
p:avisar_margem()
confere(#mensagens == n_msg + 1 and mensagens[#mensagens]:find("66") ~= nil, "avisa, com a margem que resolve")
p:avisar_margem()
confere(#mensagens == n_msg + 1, "e nao repete o mesmo aviso")
leitor.typeset.unscaled_margins = { 10, 70, 10, 15 }
confere(p:margem_necessaria() == nil, "margem de cima 70: nao cobre")
p:mudar("overlay_canto", "inferior_esquerdo")
local qual2, valor2 = p:margem_necessaria()
confere(qual2 == "baixo" and valor2 == 66, "embaixo, margem de baixo 15: cobre (" .. tostring(valor2) .. ")")
p:mudar("overlay_canto", "superior_direito")
p:mudar("overlay_onde", "barra")
confere(p:margem_necessaria() == nil, "na barra de status nunca cobre")
p:mudar("overlay_onde", "canto")
leitor.rolling, leitor.typeset = nil, nil

print("5. PC some")
p.settings:saveSetting("url", "http://127.0.0.1:1/estado.json")
for _ = 1, 3 do p:buscar(); rodar(2) end
confere(p:vista().modo == "sem_sinal", "depois de 3 falhas mostra 'sem sinal'")
local _, quadro, estilo = p:overlay_alvo()
confere(estilo == "apagado", "overlay fica apagado (" .. tostring(quadro) .. ")")
p:mudar("overlay_so_ativo", true)
confere(p:overlay_alvo() == false, "com 'esconder quando parado', some")

print("6. um erro no plugin nao quebra a pagina")
local E = require("claudinho/estado")
local original = E.interpretar
E.interpretar = function() error("erro de teste") end
p:mudar("overlay_so_ativo", false)
local ok_pagina = pcall(pagina)
local ok_busca = pcall(function() p:buscar(); rodar(2) end)
local ok_painel = pcall(function() p:abrir_painel(); rodar(2); pilha[#pilha]:onTap() end)
E.interpretar = original
confere(ok_painel and p.painel == nil, "o painel abre (com o minimo) e fecha")
confere(ok_pagina, "o livro continua sendo desenhado")
confere(ok_busca, "a busca e a atualizacao seguem sem erro")
p.overlay_pintado = nil
pagina()
confere(p.overlay_pintado ~= nil, "com o erro corrigido, o overlay volta")

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
