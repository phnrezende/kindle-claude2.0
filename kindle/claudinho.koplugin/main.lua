--[[--
Claudinho: o Claude Code no Kindle, dentro do KOReader.

- Painel em tela cheia (o do kindle-claude), com toque para voltar aos livros.
- Linha no topo da pagina enquanto voce le ("Claude ●○○ 75%"): se o Claude esta
  parado, trabalhando ou pedindo permissao, e o % usado da sessao de 5 h. A margem
  de cima sobe so o bastante para ela nao cobrir o texto.
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

local VERSAO = "1.6"

local PADRAO = {
    overlay = true,                -- a linha "Claude ●○○ 75%" no topo da pagina
    aviso_chamando = true,         -- aviso na pagina quando o Claude pede sua permissao
    pausado = false,               -- pausa tudo: nenhuma busca, sem linha, sem aviso, sem painel
    intervalo_leitura = "adaptativo", -- enquanto le: "adaptativo" (ver Claudinho:intervalo) ou segundos fixos
    intervalo_painel = 30,         -- segundos entre buscas com o painel aberto
    painel_rotacao = 90,           -- 90: logo "kindle" a esquerda; 270: a direita
    painel_animar = true,
    painel_acordado = true,        -- nao deixa o Kindle dormir com o painel aberto
}

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
    avisado = nil,      -- o "desde" do ultimo pedido de permissao ja avisado
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
    -- o KOReader passa "plugins/claudinho.koplugin" (relativo) ou um caminho absoluto
    self.dir = self.path or (debug.getinfo(1, "S").source:sub(2):match("(.*)/") or ".")
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

--- A pasta do plugin como caminho absoluto.
local function absoluto(dir)
    if dir:match("^/") then return dir end
    local ok, lfs = pcall(require, "libs/libkoreader-lfs")
    local atual = ok and type(lfs) == "table" and lfs.currentdir and lfs.currentdir() or os.getenv("PWD")
    if not atual then return dir end
    return atual .. "/" .. dir:gsub("^%./", "")
end

--- Caminho de uma fonte do plugin para o Font:getFace. Ate o KOReader 2026.07 ele
--- poe a pasta de fontes na frente de qualquer nome, ate de um caminho absoluto
--- ("./fonts//mnt/us/..."), e a fonte nao abre. Subindo ate a raiz a partir da
--- pasta de fontes, o mesmo caminho funciona nas versoes antigas e nas novas.
function Claudinho:arquivo_fonte(nome)
    return string.rep("../", 32) .. absoluto(self.dir):gsub("^/+", "") .. "/fonts/" .. nome
end

function Claudinho:fonte()
    if self._fonte then return self._fonte end
    local arquivos = {
        inter800 = self:arquivo_fonte("InterTight-ExtraBold.ttf"),
        inter900 = self:arquivo_fonte("InterTight-Black.ttf"),
        mono400 = self:arquivo_fonte("JetBrainsMono-Regular.ttf"),
        mono700 = self:arquivo_fonte("JetBrainsMono-Bold.ttf"),
    }
    -- o Font:getFace escala o tamanho pela tela; aqui queremos o pixel exato. A escala
    -- e lida a cada fonte: a tela pode ter mudado de tamanho desde a ultima (janela
    -- redimensionada no computador), e uma escala velha deixaria o texto do tamanho errado
    self._fonte = function(nome, px)
        local s = Screen:scaleBySize(1000) / 1000
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

-- o minimo para o painel e a linha do topo desenharem se ate o "sem sinal" falhar
local VISTA_MINIMA = {
    modo = "sem_sinal", grupo = "sem_sinal", titulo = "Claudinho", linha = "", agentes = "", ativos = 0, ferramenta = "",
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
    if self.fechado or self.suspenso or self:opt("pausado") then return false end
    return self.painel ~= nil or (self.leitor and (self:opt("overlay") or self:opt("aviso_chamando")))
end

-- busca adaptativa (segundos): a base, o minimo trabalhando, e os tetos parado e sem
-- sinal. O teto parado fica abaixo dos 10 min que viram "sem sinal" (E.SEM_SINAL_APOS).
local BUSCA_BASE, BUSCA_MIN, BUSCA_PARADO, BUSCA_SEM_SINAL = 60, 30, 300, 600

--- Segundos ate a proxima busca. Com o painel aberto, o intervalo dele. Lendo, o
--- tempo fixo escolhido em "Lendo", ou, no adaptativo, um que segue o que o Claude
--- esta fazendo: trabalhando ou pedindo permissao, 30 s (o aviso chega antes);
--- terminou ha pouco, 1 min; parado, 3 min; sem sinal do PC, dobra a cada falha.
function Claudinho:intervalo()
    if self.painel then return self:opt("intervalo_painel") end
    local fixo = tonumber(self:opt("intervalo_leitura"))
    if fixo then return fixo end
    local base = BUSCA_BASE
    local g = self:vista().grupo
    if g == "trabalhando" or g == "aprovacao" then
        return math.max(BUSCA_MIN, math.min(base, math.floor(base / 2)))
    elseif g == "descansando" then
        return math.max(base, math.min(BUSCA_PARADO, base * 3))
    elseif g == "sem_sinal" then
        local vezes = 2 ^ math.max(1, (C.falhas or 0) - 2)
        return math.max(base, math.min(BUSCA_SEM_SINAL, base * vezes))
    end
    return base
end

local function conectado()
    local ok, NetworkMgr = pcall(require, "ui/network/manager")
    if not ok then return true end
    local ok2, r = pcall(NetworkMgr.isConnected, NetworkMgr)
    return not ok2 or r ~= false
end

--- Busca agora e agenda a proxima. O intervalo depende do estado novo, entao e
--- recalculado quando a resposta chega; o agendado antes fica de reserva, caso ela
--- nunca chegue.
function Claudinho:ciclo()
    UIManager:unschedule(self.tarefa)
    if not self:precisa_buscar() then return end
    UIManager:scheduleIn(self:intervalo(), self.tarefa)
    self:buscar(function()
        if not self:precisa_buscar() then return end
        UIManager:unschedule(self.tarefa)
        UIManager:scheduleIn(self:intervalo(), self.tarefa)
    end)
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
    self:atualizar_linha()
    local ok, err = pcall(self.avisar_chamando, self)
    if not ok then avisar("aviso de permissao", err) end
end

--- Pedindo permissao enquanto voce le: um aviso na pagina, uma vez por pedido (o
--- "desde" muda a cada pedido novo). Com o painel aberto nao avisa, porque ele ja
--- mostra "Te chamando!", e esse pedido conta como visto.
function Claudinho:avisar_chamando()
    if not self.leitor or self.fechado or self:opt("pausado") then return end
    local v = self:vista()
    if v.grupo ~= "aprovacao" then return end
    local pedido = tostring(type(C.dados) == "table" and C.dados.desde or nil)
    if pedido == C.avisado then return end
    if self.painel or not self:opt("aviso_chamando") then
        C.avisado = pedido
        return
    end
    C.avisado = pedido
    local oque = v.ferramenta ~= "" and (v.ferramenta .. " · " .. v.descricao) or v.descricao
    UIManager:show(InfoMessage:new{ text = L.t("aviso_chamando", oque), timeout = 10 })
end

-- ------------------------------------------------------------------ linha do topo

-- distancias em pixels do Kindle de 600x800: do topo da pagina (ou do cabecalho
-- do livro) ate a linha, da linha ate o texto, e a folga em volta dela para o dedo
local LINHA_TOPO, LINHA_RESPIRO, LINHA_FOLGA = 4, 4, 10

--- Pixels reais por pixel do Kindle de 600x800, como o KOReader escala a interface.
local function escala() return Screen:scaleBySize(1000) / 1000 end

--- Altura do cabecalho do livro (titulo, pagina... no topo), se estiver ligado.
function Claudinho:cabecalho()
    local ui = self.ui
    if not (ui and ui.view and ui.view.view_mode == "page" and ui.document and ui.document.getHeaderHeight) then
        return 0
    end
    local ok, h = pcall(ui.document.getHeaderHeight, ui.document)
    return ok and tonumber(h) or 0
end

--- O que a linha mostra agora (nil se desligada) e uma chave que muda junto com ela.
function Claudinho:linha_alvo()
    if not self:opt("overlay") or self:opt("pausado") then return nil end
    local info = E.linha_topo(self:vista())
    return info, string.format("%s|%s|%d", tostring(info.estado), info.pct, info.agentes)
end

--- A faixa da linha: centralizada no topo, logo abaixo do cabecalho do livro.
--- `w` e a largura da imagem (sem ela, valem so a altura e a posicao).
function Claudinho:linha_retangulo(w)
    local s = escala()
    w = w or 0
    return Geom:new{
        x = math.floor((Screen:getWidth() - w) / 2),
        y = self:cabecalho() + math.floor(LINHA_TOPO * s + 0.5),
        w = w,
        h = math.floor(D.LINHA.altura * s + 0.5),
    }
end

--- A imagem da linha, refeita so quando o que ela mostra muda: o desenho roda a
--- cada pagina virada.
function Claudinho:imagem_linha(info, chave)
    if self.linha_img and self.linha_chave == chave then return self.linha_img end
    if not self.desenho_linha then
        self.desenho_linha = D.novo(Blitbuffer, RenderText, self:fonte(), sprites, 1)
    end
    if self.linha_img then self.linha_img:free() end
    self.linha_img, self.linha_chave = nil, nil
    self.linha_img = self.desenho_linha:linha_topo(info, escala())
    self.linha_chave = chave
    return self.linha_img
end

--- Chamado pelo ReaderView a cada pagina: um erro aqui quebraria a leitura.
function Claudinho:pintar_linha(bb, x, y)
    local ok, err = pcall(self.desenhar_linha, self, bb, x, y)
    if not ok then
        self.linha_pintada = nil
        avisar("desenho da linha", err)
    end
end

function Claudinho:desenhar_linha(bb, x, y)
    local info, chave = self:linha_alvo()
    self.linha_pintada = chave
    if not info then return end
    local img = self:imagem_linha(info, chave)
    local r = self:linha_retangulo(img:getWidth())
    bb:blitFrom(img, x + r.x, y + r.y, 0, 0, r.w, r.h)
end

--- Pede para repintar so a faixa da linha, e so se ela mudou. Chamado depois de
--- cada busca e de cada opcao do menu; um erro aqui nao pode subir para o KOReader.
function Claudinho:atualizar_linha(forcar)
    local ok, err = pcall(self.pedir_linha, self, forcar)
    if not ok then avisar("linha do topo", err) end
end

--- O toque `ges` caiu na linha do topo (com a folga para o dedo)?
function Claudinho:toque_na_linha(ges)
    if self.painel or self.fechado or not self.linha_img or not self:linha_alvo() then return false end
    local pos = ges and ges.pos
    if not pos then return false end
    local r = self:linha_retangulo(self.linha_img:getWidth())
    local folga = Screen:scaleBySize(LINHA_FOLGA)
    return pos.x >= r.x - folga and pos.x <= r.x + r.w + folga and pos.y <= r.y + r.h + folga
end

--- Um toque na linha do topo abre o painel. Fora dela devolve false, e o KOReader
--- passa o toque adiante (para o menu de cima, por exemplo).
function Claudinho:tocou_linha(ges)
    local ok, na_linha = pcall(self.toque_na_linha, self, ges)
    if not ok then
        avisar("toque na linha", na_linha)
        return false
    end
    if not na_linha then return false end
    self:abrir_painel()
    return true
end

function Claudinho:pedir_linha(forcar)
    if not self.leitor or self.painel or self.fechado then return end
    local _, chave = self:linha_alvo()
    if not forcar and chave == self.linha_pintada then return end
    -- a largura muda ("9%" -> "10%", "×3"): refresca a faixa toda
    local r = self:linha_retangulo()
    local area = Geom:new{ x = 0, y = r.y, w = Screen:getWidth(), h = r.h }
    UIManager:setDirty(self.ui, function() return "ui", area end)
end

-- ------------------------------------------------------------------ espaco para a linha

-- O KOReader so tem as 4 margens da pagina: nao da para o texto contornar so a
-- linha. Entao a margem de cima sobe o bastante para ela ficar fora do texto. So a
-- margem aplicada muda: a que o KOReader grava no livro (configurable) continua a
-- sua, e volta quando voce desliga a linha.

--- A margem de cima que deixa a linha fora do texto, na unidade do menu de margens,
--- ou nil se as margens `m` (padrao: as da pagina agora) ja bastam.
--- So para livros de texto (EPUB, FB2...): os de pagina fixa (PDF) nao tem margem.
function Claudinho:margem_necessaria(m)
    local typeset = self.ui and self.ui.rolling and self.ui.typeset
    m = m or (typeset and typeset.unscaled_margins)
    if type(m) ~= "table" or not self:opt("overlay") or self:opt("pausado") then return nil end
    local r = self:linha_retangulo()
    local cab = self:cabecalho()
    local fim = r.y + r.h + math.floor(LINHA_RESPIRO * escala() + 0.5)
    if fim <= cab + Screen:scaleBySize(tonumber(m[2]) or 0) then return nil end
    return math.ceil((fim - cab) / escala())
end

--- As margens que voce escolheu no menu de baixo (as que o KOReader grava no livro).
function Claudinho:margens_suas()
    local c = self.ui and self.ui.document and self.ui.document.configurable
    if type(c) ~= "table" or type(c.h_page_margins) ~= "table" then return nil end
    return { c.h_page_margins[1], c.t_page_margin, c.h_page_margins[2], c.b_page_margin }
end

--- As margens que a pagina deveria ter: as suas, com a de cima aumentada se a linha
--- cobriria o texto. Depende so de a linha estar ligada, nao do que o Claude esta
--- fazendo: cada troca de margem faz o KOReader paginar o livro de novo.
function Claudinho:margens_alvo()
    local m = self:margens_suas()
    if not m then return nil end
    m[2] = self:margem_necessaria(m) or m[2]
    return m
end

--- Aplica as margens alvo, se a pagina estiver com outras (do mesmo jeito que o
--- ReaderTypeset faz). Chamado antes de paginar o livro e a cada mudanca de margem.
function Claudinho:ajustar_margem()
    local typeset = self.ui and self.ui.rolling and self.ui.typeset
    if not (typeset and typeset.unscaled_margins) then return end
    local alvo = self:margens_alvo()
    if not alvo then return end
    local atual = typeset.unscaled_margins
    if atual[1] == alvo[1] and atual[2] == alvo[2] and atual[3] == alvo[3] and atual[4] == alvo[4] then return end
    typeset.unscaled_margins = alvo
    self.ui:handleEvent(Event:new("SetPageMargins", alvo))
end

function Claudinho:reservar_espaco()
    local ok, err = pcall(self.ajustar_margem, self)
    if not ok then avisar("margem automatica", err) end
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
    if self:opt("pausado") then
        UIManager:show(InfoMessage:new{ text = L.t("pausado_painel"), timeout = 5 })
        return
    end
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
            self:reiniciar(self:intervalo())
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
    self.overlay_modulo = { paintTo = function(_, bb, x, y) self:pintar_linha(bb, x, y) end }
    self.ui.view:registerViewModule("claudinho", self.overlay_modulo)
    if self.ui.registerTouchZones then
        -- a zona vai na frente das do menu de cima e das de virar a pagina, mas so
        -- fica com o toque que cai na linha (ver tocou_linha)
        self.ui:registerTouchZones({ {
            id = "claudinho_linha_tap",
            ges = "tap",
            screen_zone = { ratio_x = 0, ratio_y = 0, ratio_w = 1, ratio_h = 1 / 8 },
            overrides = { "readermenu_ext_tap", "readermenu_tap", "tap_forward", "tap_backward" },
            handler = function(ges) return self:tocou_linha(ges) end,
        } })
    end
    self:reservar_espaco()
    self:reiniciar(2)
end

--- Antes da primeira paginacao do livro: reservando o espaco aqui, o livro e
--- paginado uma vez so ao abrir.
function Claudinho:onPreRenderDocument()
    self:reservar_espaco()
end

--- Margens mudaram (no menu de baixo, ou a barra de status apareceu): reserva o
--- espaco de novo.
function Claudinho:onSetPageMargins()
    if self.leitor and not self.fechado then
        UIManager:nextTick(function()
            if not self.fechado then self:reservar_espaco() end
        end)
    end
end

--- A tela mudou de tamanho ou girou: a linha e refeita na escala nova, e o espaco
--- dela na margem e reservado de novo (o painel aberto se refaz sozinho).
function Claudinho:onSetDimensions()
    if not self.leitor or self.fechado then return end
    if self.linha_img then
        self.linha_img:free()
        self.linha_img, self.linha_chave = nil, nil
    end
    UIManager:nextTick(function()
        if self.fechado then return end
        self:reservar_espaco()
        self:atualizar_linha(true)
    end)
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
    if self.linha_img then
        self.linha_img:free()
        self.linha_img, self.linha_chave = nil, nil
    end
end

-- O Dispatcher guarda estas tabelas como vieram (e ignora um segundo registro com o
-- mesmo nome); trocar o title nelas e o que atualiza o nome do gesto ao mudar o idioma.
local ACOES = {
    { "claudinho_painel", { category = "none", event = "ClaudinhoPainel", general = true }, "gesto_painel" },
    { "claudinho_overlay", { category = "none", event = "ClaudinhoOverlay", general = true }, "gesto_overlay" },
    { "claudinho_pausar", { category = "none", event = "ClaudinhoPausar", general = true, separator = true },
        "gesto_pausar" },
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

function Claudinho:onClaudinhoPausar()
    self:pausar(not self:opt("pausado"))
    return true
end

--- Pausa (ou retoma) tudo: nenhuma busca (nem lendo, nem com o painel, nem ao acordar),
--- sem linha do topo (a sua margem volta), sem aviso e sem painel. Para a bateria no
--- fim, ou o PC desligado: nada usa a rede ate voce retomar. Fica gravado.
function Claudinho:pausar(sim)
    self:salvar("pausado", sim)
    if sim and self.painel then UIManager:close(self.painel) end
    Notification:notify(L.t(sim and "pausado_sim" or "pausado_nao"), Notification.SOURCE_ALWAYS_SHOW)
    self:lugar_mudou()
    self:atualizar_linha(true)
    self:reiniciar(0)
end

function Claudinho:alternar_overlay()
    local ligado = not self:opt("overlay")
    self:salvar("overlay", ligado)
    Notification:notify(L.t(ligado and "overlay_ligado" or "overlay_desligado"), Notification.SOURCE_ALWAYS_SHOW)
    self:lugar_mudou()
    self:atualizar_linha(true)
    self:reiniciar(0)
end

-- ------------------------------------------------------------------ menu

--- Depois de ligar ou desligar a linha: reserva (ou devolve) o espaco dela.
function Claudinho:lugar_mudou()
    if not self.leitor or self.fechado then return end
    self:reservar_espaco()
end

function Claudinho:mudar(chave, valor, menu)
    self:salvar(chave, valor)
    if chave == "overlay" then self:lugar_mudou() end
    self:atualizar_linha(true)
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

--- `menu`: o menu aberto por baixo, redesenhado ao salvar (o item mostra o endereco).
function Claudinho:editar(titulo, chave, atual, ajuda, menu)
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
                if menu then menu:updateItems() end
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
    local function intervalos(chave, opcoes)
        local t = {}
        for _, s in ipairs(opcoes) do
            t[#t + 1] = self:item_radio(function()
                return s < 60 and L.t("segundos", s) or L.t("minutos", s / 60)
            end, chave, s, function() self:reiniciar(1) end)
        end
        return t
    end
    -- "Lendo": adaptativo ou um tempo fixo (uma escolha so)
    local lendo = intervalos("intervalo_leitura", { 30, 60, 120, 300 })
    table.insert(lendo, 1, self:item_radio("leitura_adaptativa", "intervalo_leitura", "adaptativo",
        function() self:reiniciar(1) end))
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
                enabled_func = function() return not self:opt("pausado") end,
                callback = function()
                    -- o menu fecha logo depois deste callback; abre o painel em seguida
                    UIManager:nextTick(function() self:abrir_painel() end)
                end,
            },
            {
                text_func = texto_de("menu_pausar"),
                checked_func = function() return self:opt("pausado") end,
                keep_menu_open = true,
                callback = function(menu)
                    self:pausar(not self:opt("pausado"))
                    if menu then menu:updateItems() end
                end,
                separator = true,
            },
            self:item_liga("menu_linha", "overlay", function() self:reiniciar(0) end),
            self:item_liga("menu_aviso", "aviso_chamando", function() self:reiniciar(0) end),
            submenu("menu_painel", {
                self:item_radio("menu_logo_esquerda", "painel_rotacao", 90),
                self:item_radio("menu_logo_direita", "painel_rotacao", 270),
                self:item_liga("menu_animar_mascote", "painel_animar"),
                self:item_liga("menu_acordado", "painel_acordado"),
            }),
            submenu("menu_atualizar", {
                submenu("menu_lendo", lendo),
                submenu("menu_com_painel", intervalos("intervalo_painel", { 15, 30, 60 })),
            }),
            submenu("menu_conexao", {
                {
                    text_func = function() return L.t("menu_endereco", self:url() ~= "" and self:url() or L.t("vazio")) end,
                    keep_menu_open = true,
                    callback = function(menu)
                        self:editar(L.t("endereco_titulo"), "url", self:url(), L.t("endereco_ajuda"), menu)
                    end,
                },
                {
                    text_func = texto_de("menu_token"),
                    keep_menu_open = true,
                    callback = function(menu)
                        self:editar(L.t("menu_token"), "token", self:token(), L.t("token_ajuda"), menu)
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
