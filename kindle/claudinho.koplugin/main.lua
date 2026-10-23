--[[--
Claudinho: o Claude Code no Kindle, dentro do KOReader.

- Painel em tela cheia (o do kindle-claude), com toque para voltar aos livros.
- Overlay: um Claudinho pequeno num canto da pagina enquanto voce le, mostrando
  se o Claude esta trabalhando, esperando sua aprovacao ou descansando. Ou, se
  preferir, uma palavra na barra de status do KOReader, que nunca cobre o texto.
- Le o estado do agente no PC, na mesma rede Wi-Fi: uma URL que devolve um JSON.

@module koplugin.claudinho
]]

local Blitbuffer = require("ffi/blitbuffer")
local DataStorage = require("datastorage")
local Device = require("device")
local Dispatcher = require("dispatcher")
local Event = require("ui/event")
local Font = require("ui/font")
local Geom = require("ui/geometry")
local InfoMessage = require("ui/widget/infomessage")
local InputDialog = require("ui/widget/inputdialog")
local LuaSettings = require("luasettings")
local Notification = require("ui/widget/notification")
local PluginShare = require("pluginshare")
local RenderText = require("ui/rendertext")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local logger = require("logger")
local Screen = Device.screen

local Busca = require("claudinho/busca")
local D = require("claudinho/desenho")
local E = require("claudinho/estado")
local json = require("claudinho/json")
local L = require("claudinho/textos")
local sprites = require("claudinho/sprites")

local VERSAO = "1.3"

local PADRAO = {
    overlay = true,
    overlay_onde = "canto",        -- "canto" (o Claudinho na pagina) ou "barra" (texto na barra de status)
    overlay_canto = "superior_direito",
    overlay_tamanho = 2,           -- 1 mini, 2 pequeno, 3 medio
    overlay_so_ativo = false,      -- esconde quando o Claude esta parado
    overlay_animar = false,        -- alterna o quadro a cada busca (mais refresh)
    intervalo_leitura = 60,        -- segundos entre buscas enquanto le
    intervalo_painel = 30,         -- segundos entre buscas com o painel aberto
    painel_rotacao = 90,           -- 90: logo "kindle" a esquerda; 270: a direita
    painel_animar = true,
    painel_acordado = true,        -- nao deixa o Kindle dormir com o painel aberto
}

local CANTOS = { "superior_direito", "superior_esquerdo", "inferior_direito", "inferior_esquerdo" }

-- Estado compartilhado entre as instancias do plugin (o KOReader cria uma
-- nova ao trocar entre a biblioteca e um livro): assim nada some na troca.
local C = {
    dados = nil,        -- ultimo JSON do PC
    recebido_em = nil,  -- os.time() do Kindle na ultima leitura que deu certo
    desvio = 0,         -- relogio do Kindle menos o do PC
    etag = nil,
    falhas = 0,
    erro = nil,
    dica_mostrada = false,
    esperando = {},     -- quem quer saber quando a busca em andamento terminar
    dormiu = 0,         -- segundos dormindo desde a ultima leitura que deu certo
    dormiu_em = nil,    -- os.time() quando o Kindle foi dormir
    tela_conferida = false,
}

local Claudinho = WidgetContainer:extend{
    name = "claudinho",
    is_doc_only = false,
}

-- ------------------------------------------------------------------ config

local function ler_config(dir)
    local ok, cfg = pcall(dofile, dir .. "/config.lua")
    if ok and type(cfg) == "table" then return cfg end
    return {}
end

function Claudinho:init()
    self.dir = self.path or (debug.getinfo(1, "S").source:sub(2):match("(.*)/") or ".")
    -- o KOReader passa "plugins/claudinho.koplugin" (relativo); o Font:getFace so
    -- aceita caminho de arquivo se comecar com "/" ou "./"
    if not self.dir:match("^/") and not self.dir:match("^%./") then
        self.dir = "./" .. self.dir
    end
    self.cfg = ler_config(self.dir)
    self.settings = LuaSettings:open(DataStorage:getSettingsDir() .. "/claudinho.lua")
    -- um config.lua novo (rodou o setup no PC e copiou de novo) vale mais que o menu
    if self.cfg.gerado_em and self.settings:readSetting("config_gerado_em") ~= self.cfg.gerado_em then
        self.settings:delSetting("url")
        self.settings:delSetting("token")
        self.settings:saveSetting("config_gerado_em", self.cfg.gerado_em)
        self.settings:flush()
    end
    L.escolher(self.settings:readSetting("idioma"))   -- nil: segue o idioma do KOReader
    self:conferir_tela_acordada()

    self.tarefa = function() self:ciclo() end
    self:onDispatcherRegisterActions()
    self.ui.menu:registerToMainMenu(self)
end

function Claudinho:opt(chave)
    local v = self.settings:readSetting(chave)
    if v == nil then return PADRAO[chave] end
    return v
end

function Claudinho:salvar(chave, valor)
    self.settings:saveSetting(chave, valor)
    self.settings:flush()
end

function Claudinho:url() return self.settings:readSetting("url") or self.cfg.url or "" end
function Claudinho:token() return self.settings:readSetting("token") or self.cfg.token or "" end

-- ------------------------------------------------------------------ fontes

function Claudinho:fonte()
    if self._fonte then return self._fonte end
    local arquivos = {
        inter800 = self.dir .. "/fonts/InterTight-ExtraBold.ttf",
        inter900 = self.dir .. "/fonts/InterTight-Black.ttf",
        mono400 = self.dir .. "/fonts/JetBrainsMono-Regular.ttf",
        mono700 = self.dir .. "/fonts/JetBrainsMono-Bold.ttf",
    }
    -- o Font:getFace escala o tamanho pela tela; aqui queremos o pixel exato
    local s = Screen:scaleBySize(1000) / 1000
    self._fonte = function(nome, px)
        local alvo = math.max(1, math.floor(px + 0.5))
        local tam = (alvo - 0.5) / s
        return Font:getFace(arquivos[nome], tam) or Font:getFace("cfont", tam)
    end
    return self._fonte
end

-- ------------------------------------------------------------------ busca

--- Registra um erro do plugin uma vez so (o desenho roda a cada pagina).
local avisados = {}
local function avisar(onde, err)
    if avisados[onde] then return end
    avisados[onde] = true
    logger.warn("Claudinho: erro em", onde, err)
end

-- o minimo para o painel e o overlay desenharem se ate o "sem sinal" falhar
local VISTA_MINIMA = {
    modo = "sem_sinal", grupo = "sem_sinal", titulo = "Claudinho", linha = "", agentes = "", ferramenta = "",
    descricao = "", antes = "", sessao = { txt = "--", zera = "" }, semana = { txt = "--", zera = "" },
    tokens_hoje = "--", tokens_hora = "", tokens_media = "", rev = "", idioma = "",
}

function Claudinho:vista()
    -- um estado inesperado nunca pode quebrar a pagina: na pior hipotese, "sem sinal"
    local ok, v = pcall(E.interpretar, C.dados, os.time(), C)
    if ok then return v end
    avisar("interpretar", v)
    ok, v = pcall(E.interpretar, nil, os.time(), {})
    return ok and v or VISTA_MINIMA
end

function Claudinho:precisa_buscar()
    if self.fechado or self.suspenso then return false end
    return self.painel ~= nil or (self.leitor and self:opt("overlay"))
end

function Claudinho:intervalo()
    return self.painel and self:opt("intervalo_painel") or self:opt("intervalo_leitura")
end

local function conectado()
    local ok, NetworkMgr = pcall(require, "ui/network/manager")
    if not ok then return true end
    local ok2, r = pcall(NetworkMgr.isConnected, NetworkMgr)
    return not ok2 or r ~= false
end

function Claudinho:ciclo()
    UIManager:unschedule(self.tarefa)
    if not self:precisa_buscar() then return end
    self:buscar()
    UIManager:scheduleIn(self:intervalo(), self.tarefa)
end

--- Recomeca o ciclo agora (ou daqui a `atraso` segundos).
function Claudinho:reiniciar(atraso)
    UIManager:unschedule(self.tarefa)
    if self:precisa_buscar() then
        UIManager:scheduleIn(atraso or 0, self.tarefa)
    end
end

function Claudinho:falhou(motivo)
    C.falhas = C.falhas + 1
    C.erro = motivo
end

--- Busca o estado. `depois`, se vier, roda quando a resposta chegar, mesmo que
--- ja houvesse outra busca em andamento (ai espera por ela).
function Claudinho:buscar(depois)
    local url = self:url()
    local motivo = (url == "" and L.t("erro_sem_url")) or (not conectado() and L.t("erro_wifi")) or nil
    if motivo then
        self:falhou(motivo)
        self:atualizar_vistas()
        if depois then depois() end
        return
    end
    if depois then C.esperando[#C.esperando + 1] = depois end
    -- se ja havia uma busca, o Busca.get devolve false e o fim dela avisa todo mundo
    Busca.get(url, self:token(), C.etag, function(r)
        self:receber(r)
        local lista = C.esperando
        C.esperando = {}
        for _, f in ipairs(lista) do f() end
    end)
end

function Claudinho:receber(r)
    if r.codigo == 200 then
        local dados, err = json.decode(r.corpo)
        if type(dados) == "table" then
            C.dados, C.etag, C.falhas, C.erro = dados, r.etag, 0, nil
            C.recebido_em, C.dormiu = os.time(), 0
            C.desvio = E.desvio(dados, C.recebido_em)
        else
            self:falhou(L.t("erro_resposta", tostring(err)))
        end
    elseif r.codigo == 304 then
        -- nada mudou; o desvio do relogio continua o da ultima resposta completa
        C.recebido_em, C.dormiu = os.time(), 0
        C.falhas, C.erro = 0, nil
    elseif r.codigo == 401 then
        self:falhou(L.t("erro_token"))
    elseif r.codigo then
        self:falhou(L.t("erro_http", r.codigo))
    else
        self:falhou(r.erro or L.t("erro_sem_resposta"))
    end
    if C.erro then logger.dbg("Claudinho:", C.erro) end
    if not self.fechado then self:atualizar_vistas() end
end

function Claudinho:atualizar_vistas()
    if self.painel then
        local ok, err = pcall(self.painel.novo_estado, self.painel)
        if not ok then avisar("painel", err) end
    end
    self:atualizar_overlay()
end

-- ------------------------------------------------------------------ overlay

function Claudinho:celula_overlay()
    local fator = math.max(1, math.floor(math.min(Screen:getWidth(), Screen:getHeight()) / 600 + 0.5))
    return self:opt("overlay_tamanho") * fator
end

--- O que o overlay deveria mostrar agora: (visivel, quadro, estilo).
function Claudinho:overlay_alvo()
    if not self:opt("overlay") or self:opt("overlay_onde") == "barra" then return false end
    local v = self:vista()
    local g = v.grupo
    if self:opt("overlay_so_ativo") and (g == "descansando" or g == "sem_sinal") then
        return false
    end
    local estilo = (g == "aprovacao" and "alerta") or (g == "sem_sinal" and "apagado") or "normal"
    local quadro = E.quadro_parado(v.modo)
    if self:opt("overlay_animar") and (self.fase or 0) % 2 == 1 then
        quadro = quadro:gsub("_1$", "_2")
    end
    return true, quadro, estilo
end

function Claudinho:overlay_retangulo()
    local cel = self:celula_overlay()
    local w, h = D.tamanho_overlay(sprites, cel)
    local sw, sh = Screen:getWidth(), Screen:getHeight()
    local m = Screen:scaleBySize(8)
    local baixo = m
    local view = self.ui and self.ui.view
    if view and view.footer_visible and view.footer then
        local ok, fh = pcall(view.footer.getHeight, view.footer)
        if ok and fh then baixo = m + fh end
    end
    local canto = self:opt("overlay_canto")
    local x = canto:find("esquerdo") and m or (sw - w - m)
    local y = canto:find("superior") and m or (sh - h - baixo)
    return Geom:new{ x = x, y = y, w = w, h = h }, cel
end

--- Chamado pelo ReaderView a cada pagina: um erro aqui quebraria a leitura.
function Claudinho:pintar_overlay(bb, x, y)
    local ok, err = pcall(self.desenhar_overlay, self, bb, x, y)
    if not ok then
        self.overlay_pintado = nil
        avisar("desenho do overlay", err)
    end
end

function Claudinho:desenhar_overlay(bb, x, y)
    local visivel, quadro, estilo = self:overlay_alvo()
    self.overlay_pintado = visivel and (quadro .. estilo) or nil
    if not visivel then return end
    local r, cel = self:overlay_retangulo()
    self.overlay_rect = r
    if not self.desenho_overlay then
        self.desenho_overlay = D.novo(Blitbuffer, RenderText, self:fonte(), sprites, 1)
    end
    self.desenho_overlay:overlay(bb, x + r.x, y + r.y, quadro, cel, estilo)
end

--- Pede para repintar so o cantinho, e so se algo mudou. Chamado depois de cada
--- busca e de cada opcao do menu; um erro aqui nao pode subir para o KOReader.
function Claudinho:atualizar_overlay(forcar)
    local ok, err = pcall(self.pedir_overlay, self, forcar)
    if not ok then avisar("overlay", err) end
end

function Claudinho:pedir_overlay(forcar)
    if not self.leitor or self.painel or self.fechado then return end
    self:atualizar_barra(forcar)
    if self:opt("overlay_animar") then self.fase = (self.fase or 0) + 1 end
    local visivel, quadro, estilo = self:overlay_alvo()
    local chave = visivel and (quadro .. estilo) or nil
    if not forcar and chave == self.overlay_pintado then return end
    local antes = self.overlay_rect
    local agora = self:overlay_retangulo()
    local area = antes and antes:combine(agora) or agora
    UIManager:setDirty(self.ui, function() return "ui", area end)
end

-- ------------------------------------------------------------------ barra de status

--- O que vai na barra de status do KOReader no modo "na barra" (nil: nada).
function Claudinho:texto_barra()
    if not self:opt("overlay") or self:opt("overlay_onde") ~= "barra" then return nil end
    return E.texto_barra(self:vista(), self:opt("overlay_so_ativo"))
end

--- Poe (ou tira) o texto do Claudinho na barra de status, pelo "conteudo externo"
--- do rodape do KOReader (o mesmo que o plugin do timer de leitura usa).
function Claudinho:ligar_barra(ligar)
    local footer = self.ui and self.ui.view and self.ui.view.footer
    if not (footer and footer.addAdditionalFooterContent) then return end
    if ligar and not self.barra_func then
        self.barra_func = function()
            local ok, t = pcall(self.texto_barra, self)
            if not ok then avisar("barra de status", t) end
            return ok and t or nil
        end
        footer:addAdditionalFooterContent(self.barra_func)
        self.barra_texto = nil
        self:atualizar_barra(true)
    elseif not ligar and self.barra_func then
        footer:removeAdditionalFooterContent(self.barra_func)
        self.barra_func, self.barra_texto = nil, nil
        UIManager:broadcastEvent(Event:new("UpdateFooter", true))
    end
end

--- Pede ao rodape para redesenhar so se o texto mudou.
function Claudinho:atualizar_barra(forcar)
    if not self.barra_func then return end
    local t = self:texto_barra() or ""
    if not forcar and t == self.barra_texto then return end
    self.barra_texto = t
    UIManager:broadcastEvent(Event:new("RefreshAdditionalContent"))
end

-- ------------------------------------------------------------------ o overlay cobre o texto?

--- Se o Claudinho no canto cobre o texto do livro, devolve qual margem resolveria
--- ("cima" ou "baixo") e o valor minimo dela, na unidade do menu de margens.
--- So para livros de texto (EPUB, FB2...): nos de pagina fixa (PDF) nao da para saber.
function Claudinho:margem_necessaria()
    local ui = self.ui
    local typeset = ui and ui.rolling and ui.typeset
    local m = typeset and typeset.unscaled_margins
    if type(m) ~= "table" or not self:opt("overlay") or self:opt("overlay_onde") == "barra" then return nil end
    local r = self:overlay_retangulo()
    local sw, sh = Screen:getWidth(), Screen:getHeight()
    local esq, dir = Screen:scaleBySize(tonumber(m[1]) or 0), Screen:scaleBySize(tonumber(m[3]) or 0)
    if r.x >= sw - dir or r.x + r.w <= esq then return nil end      -- fica so na margem do lado
    local escala = Screen:scaleBySize(1000) / 1000
    if self:opt("overlay_canto"):find("superior") then
        local cabecalho = 0
        if ui.view and ui.view.view_mode == "page" and ui.document and ui.document.getHeaderHeight then
            local ok, h = pcall(ui.document.getHeaderHeight, ui.document)
            if ok and tonumber(h) then cabecalho = tonumber(h) end
        end
        local topo = cabecalho + Screen:scaleBySize(tonumber(m[2]) or 0)
        if r.y + r.h <= topo then return nil end
        return "cima", math.ceil((r.y + r.h + 2 - cabecalho) / escala)
    end
    local rodape = 0
    local view = ui.view
    if view and view.footer_visible and view.footer and not view.footer.reclaim_height then
        local ok, fh = pcall(view.footer.getHeight, view.footer)
        if ok and tonumber(fh) then rodape = tonumber(fh) end
    end
    local fundo = sh - rodape - Screen:scaleBySize(tonumber(m[4]) or 0)
    if r.y >= fundo then return nil end
    return "baixo", math.ceil((sh - rodape - r.y + 2) / escala)
end

--- Avisa uma vez (por canto e tamanho) quando o Claudinho cobre o texto.
function Claudinho:avisar_margem()
    local ok, qual, valor = pcall(self.margem_necessaria, self)
    if not ok then return avisar("margem", qual) end
    if not qual then return end
    local chave = self:opt("overlay_canto") .. ":" .. tostring(self:opt("overlay_tamanho"))
    if self.settings:readSetting("aviso_margem") == chave then return end
    self:salvar("aviso_margem", chave)
    UIManager:show(InfoMessage:new{
        text = L.t("aviso_cobre", L.t(qual == "cima" and "margem_cima" or "margem_baixo"), valor),
        timeout = 12,
    })
end

-- ------------------------------------------------------------------ painel

function Claudinho:manter_acordado(ligar)
    if ligar then
        if not self:opt("painel_acordado") then return end
        self.acordado = { keepalive = PluginShare.keepalive, pausa = PluginShare.pause_auto_suspend }
        PluginShare.pause_auto_suspend = true
        if Device:isKindle() and not PluginShare.keepalive then
            -- a marca gravada antes: se o KOReader fechar ou travar com o painel aberto,
            -- o proximo inicio devolve o protetor de tela (ver conferir_tela_acordada)
            self:salvar("tela_acordada", true)
            os.execute("lipc-set-prop com.lab126.powerd preventScreenSaver 1")
            PluginShare.keepalive = true
        end
    elseif self.acordado then
        PluginShare.pause_auto_suspend = self.acordado.pausa
        if Device:isKindle() and not self.acordado.keepalive then
            os.execute("lipc-set-prop com.lab126.powerd preventScreenSaver 0")
            PluginShare.keepalive = self.acordado.keepalive
            self.settings:delSetting("tela_acordada")
            self.settings:flush()
        end
        self.acordado = nil
    end
end

--- Uma vez por inicio do KOReader: se ele fechou (ou travou) com o painel aberto,
--- o Kindle ficou sem protetor de tela e nao dormiria mais. Devolve como era.
function Claudinho:conferir_tela_acordada()
    if C.tela_conferida then return end
    C.tela_conferida = true
    if not self.settings:readSetting("tela_acordada") then return end
    if Device:isKindle() and not PluginShare.keepalive then
        os.execute("lipc-set-prop com.lab126.powerd preventScreenSaver 0")
    end
    self.settings:delSetting("tela_acordada")
    self.settings:flush()
end

function Claudinho:abrir_painel()
    if self.painel then return end
    local Painel = require("claudinho/painel")
    self:manter_acordado(true)
    local ok, painel = pcall(Painel.new, Painel, {
        fonte = self:fonte(),
        ler_estado = function() return self:vista() end,
        rotacao = self:opt("painel_rotacao"),
        animar = self:opt("painel_animar"),
        ao_fechar = function()
            self.painel = nil
            self:manter_acordado(false)
            self:reiniciar(self:opt("intervalo_leitura"))
        end,
    })
    if not ok then
        avisar("abrir o painel", painel)
        self:manter_acordado(false)
        return
    end
    self.painel = painel
    UIManager:show(self.painel)
    if not C.dica_mostrada then
        C.dica_mostrada = true
        Notification:notify(L.t("dica_voltar"), Notification.SOURCE_ALWAYS_SHOW)
    end
    self:reiniciar(0)
end

-- ------------------------------------------------------------------ eventos

function Claudinho:onReaderReady()
    if not (self.ui.view and self.ui.view.registerViewModule) then return end
    self.leitor = true
    self.overlay_modulo = { paintTo = function(_, bb, x, y) self:pintar_overlay(bb, x, y) end }
    self.ui.view:registerViewModule("claudinho", self.overlay_modulo)
    if self:opt("overlay") and self:opt("overlay_onde") == "barra" then
        self:ligar_barra(true)
    end
    UIManager:nextTick(function() if not self.fechado then self:avisar_margem() end end)
    self:reiniciar(2)
end

--- Margens mudaram no menu de baixo: confere de novo se o Claudinho cobre o texto.
function Claudinho:onSetPageMargins()
    if self.leitor and not self.fechado then
        UIManager:nextTick(function() if not self.fechado then self:avisar_margem() end end)
    end
end

function Claudinho:onSuspend()
    self.suspenso = true
    C.dormiu_em = C.dormiu_em or os.time()
    UIManager:unschedule(self.tarefa)
end

function Claudinho:onResume()
    self.suspenso = false
    if C.dormiu_em then
        -- o tempo dormindo nao conta para o "sem sinal" (ver E.interpretar)
        C.dormiu = (C.dormiu or 0) + math.max(0, os.time() - C.dormiu_em)
        C.dormiu_em = nil
    end
    self:reiniciar(3)        -- da tempo do Wi-Fi voltar
end

function Claudinho:onNetworkConnected()
    self:reiniciar(1)
end

function Claudinho:onCloseDocument()
    UIManager:unschedule(self.tarefa)
end

function Claudinho:onCloseWidget()
    self.fechado = true
    UIManager:unschedule(self.tarefa)
    if self.painel then UIManager:close(self.painel) end
end

-- O Dispatcher guarda estas tabelas como vieram (e ignora um segundo registro com o
-- mesmo nome); trocar o title nelas e o que atualiza o nome do gesto ao mudar o idioma.
local ACOES = {
    { "claudinho_painel", { category = "none", event = "ClaudinhoPainel", general = true }, "gesto_painel" },
    { "claudinho_overlay", { category = "none", event = "ClaudinhoOverlay", general = true, separator = true },
        "gesto_overlay" },
}

function Claudinho:onDispatcherRegisterActions()
    for _, a in ipairs(ACOES) do
        a[2].title = L.t(a[3])
        Dispatcher:registerAction(a[1], a[2])
    end
end

function Claudinho:onClaudinhoPainel()
    self:abrir_painel()
    return true
end

function Claudinho:onClaudinhoOverlay()
    self:alternar_overlay()
    return true
end

function Claudinho:alternar_overlay()
    local ligado = not self:opt("overlay")
    self:salvar("overlay", ligado)
    Notification:notify(L.t(ligado and "overlay_ligado" or "overlay_desligado"), Notification.SOURCE_ALWAYS_SHOW)
    self:lugar_mudou()
    self:atualizar_overlay(true)
    self:reiniciar(0)
end

-- ------------------------------------------------------------------ menu

-- opcoes que mudam onde e de que tamanho o Claudinho aparece na leitura
local MUDA_LUGAR = { overlay = true, overlay_onde = true, overlay_canto = true, overlay_tamanho = true }

--- Depois de mudar onde o Claudinho aparece: liga/desliga a barra de status e
--- confere se o canto escolhido cobre o texto.
function Claudinho:lugar_mudou()
    if not self.leitor or self.fechado then return end
    self:ligar_barra(self:opt("overlay") and self:opt("overlay_onde") == "barra")
    self:avisar_margem()
end

function Claudinho:mudar(chave, valor, menu)
    self:salvar(chave, valor)
    if MUDA_LUGAR[chave] then self:lugar_mudou() end
    self:atualizar_overlay(true)
    if menu then menu:updateItems() end
end

--- Texto de um item: chave de claudinho/textos.lua ou uma funcao que devolve o texto.
local function texto_de(texto)
    if type(texto) == "function" then return texto end
    return function() return L.t(texto) end
end

--- Itens do menu usam text_func: assim o texto acompanha a troca de idioma
--- sem reiniciar o KOReader. `texto` e uma chave de claudinho/textos.lua.
function Claudinho:item_radio(texto, chave, valor, depois)
    return {
        text_func = texto_de(texto),
        radio = true,
        checked_func = function() return self:opt(chave) == valor end,
        keep_menu_open = true,
        callback = function(menu)
            self:mudar(chave, valor, menu)
            if depois then depois() end
        end,
    }
end

function Claudinho:item_liga(texto, chave, depois)
    return {
        text_func = texto_de(texto),
        checked_func = function() return self:opt(chave) end,
        keep_menu_open = true,
        callback = function(menu)
            self:mudar(chave, not self:opt(chave), menu)
            if depois then depois() end
        end,
    }
end

function Claudinho:editar(titulo, chave, atual, ajuda)
    local dialogo
    dialogo = InputDialog:new{
        title = titulo,
        input = atual,
        description = ajuda,
        buttons = { {
            { text = L.t("cancelar"), id = "close", callback = function() UIManager:close(dialogo) end },
            { text = L.t("salvar"), is_enter_default = true, callback = function()
                local valor = (dialogo:getInputText() or ""):gsub("^%s+", ""):gsub("%s+$", "")
                UIManager:close(dialogo)
                self:salvar(chave, valor)
                C.etag, C.falhas = nil, 0
                self:reiniciar(0)
            end },
        } },
    }
    UIManager:show(dialogo)
    dialogo:onShowKeyboard()
end

function Claudinho:testar_conexao()
    UIManager:show(InfoMessage:new{ text = L.t("buscando"), timeout = 1 })
    C.etag = nil
    self:buscar(function()
        local texto
        if C.falhas == 0 and C.dados then
            local v = self:vista()
            texto = L.t("conectado", v.titulo, v.linha)
        else
            texto = L.t("nao_conectou", C.erro or L.t("erro_desconhecido"), self:url())
        end
        UIManager:show(InfoMessage:new{ text = texto })
    end)
end

function Claudinho:item_idioma(idioma)
    return {
        text_func = function() return idioma and L.NOMES[idioma] or L.t("idioma_auto") end,
        radio = true,
        checked_func = function() return self.settings:readSetting("idioma") == idioma end,
        keep_menu_open = true,
        callback = function(menu)
            if idioma then
                self:salvar("idioma", idioma)
            else
                self.settings:delSetting("idioma")
                self.settings:flush()
            end
            L.escolher(idioma)
            self:onDispatcherRegisterActions()     -- nomes dos gestos no idioma novo
            if menu then menu:updateItems() end
        end,
    }
end

function Claudinho:addToMainMenu(menu_items)
    local cantos = {}
    for _, c in ipairs(CANTOS) do
        cantos[#cantos + 1] = self:item_radio("canto_" .. c, "overlay_canto", c)
    end
    local function intervalos(chave, opcoes)
        local t = {}
        for _, s in ipairs(opcoes) do
            t[#t + 1] = self:item_radio(function()
                return s < 60 and L.t("segundos", s) or L.t("minutos", s / 60)
            end, chave, s, function() self:reiniciar(1) end)
        end
        return t
    end
    local function submenu(chave, itens, extra)
        local m = { text_func = texto_de(chave), sub_item_table = itens }
        for k, v in pairs(extra or {}) do m[k] = v end
        return m
    end

    menu_items.claudinho = {
        text = "Claudinho (Claude Code)",
        sorting_hint = "tools",
        sub_item_table = {
            {
                text_func = texto_de("menu_abrir"),
                callback = function()
                    -- o menu fecha logo depois deste callback; abre o painel em seguida
                    UIManager:nextTick(function() self:abrir_painel() end)
                end,
                separator = true,
            },
            submenu("menu_overlay", {
                self:item_liga("menu_mostrar", "overlay", function() self:reiniciar(0) end),
                submenu("menu_onde", {
                    self:item_radio("onde_canto", "overlay_onde", "canto"),
                    self:item_radio("onde_barra", "overlay_onde", "barra"),
                }),
                submenu("menu_canto", cantos),
                submenu("menu_tamanho", {
                    self:item_radio("tamanho_1", "overlay_tamanho", 1),
                    self:item_radio("tamanho_2", "overlay_tamanho", 2),
                    self:item_radio("tamanho_3", "overlay_tamanho", 3),
                }),
                self:item_liga("menu_esconder", "overlay_so_ativo"),
                self:item_liga("menu_animar_overlay", "overlay_animar"),
            }),
            submenu("menu_painel", {
                self:item_radio("menu_logo_esquerda", "painel_rotacao", 90),
                self:item_radio("menu_logo_direita", "painel_rotacao", 270),
                self:item_liga("menu_animar_mascote", "painel_animar"),
                self:item_liga("menu_acordado", "painel_acordado"),
            }),
            submenu("menu_atualizar", {
                submenu("menu_lendo", intervalos("intervalo_leitura", { 30, 60, 120, 300 })),
                submenu("menu_com_painel", intervalos("intervalo_painel", { 15, 30, 60 })),
            }),
            submenu("menu_conexao", {
                {
                    text_func = function() return L.t("menu_endereco", self:url() ~= "" and self:url() or L.t("vazio")) end,
                    keep_menu_open = true,
                    callback = function()
                        self:editar(L.t("endereco_titulo"), "url", self:url(), L.t("endereco_ajuda"))
                    end,
                },
                {
                    text_func = texto_de("menu_token"),
                    keep_menu_open = true,
                    callback = function()
                        self:editar(L.t("menu_token"), "token", self:token(), L.t("token_ajuda"))
                    end,
                },
                {
                    text_func = texto_de("menu_testar"),
                    keep_menu_open = true,
                    callback = function() self:testar_conexao() end,
                },
                {
                    text_func = texto_de("menu_voltar_config"),
                    enabled_func = function() return self.cfg.url ~= nil end,
                    keep_menu_open = true,
                    callback = function(menu)
                        self.settings:delSetting("url")
                        self.settings:delSetting("token")
                        self.settings:flush()
                        C.etag, C.falhas = nil, 0
                        self:reiniciar(0)
                        if menu then menu:updateItems() end
                    end,
                },
            }, { separator = true }),
            submenu(function() return L.t("menu_idioma", L.NOMES[L.atual()]) end, {
                self:item_idioma(nil),
                self:item_idioma("pt"),
                self:item_idioma("en"),
            }),
            {
                text_func = texto_de("menu_sobre"),
                keep_menu_open = true,
                callback = function()
                    UIManager:show(InfoMessage:new{ text = L.t("sobre", VERSAO) })
                end,
            },
        },
    }
end

return Claudinho
